"""Persistent store for archive data, caches, and quota state.

The pipeline runs on ephemeral CI, so anything that must survive between runs
lives here: the daily archive the site renders from, LegiScan change hashes,
cached document text, generated summaries, and the API quota ledger.

Two backends behind one interface -- R2 for CI, the local filesystem for
development -- so the daily job can be exercised end to end without touching
the network.

Layout:
    days/{state}/{YYYY-MM-DD}.json   one day's bills, with summaries
    index/{state}.json               dates present, for archive navigation
    hashes/{state}.json              bill_number -> LegiScan change_hash
    docs/{doc_id}.json               extracted document text (never refetched)
    summaries/{text_hash}.json       LLM summary, keyed by document hash
    usage/{api}/{window}.json        API quota ledgers, one per upstream

Two of those keys are deliberate:

  * documents are keyed by `doc_id` because LegiScan marks getBillText Static --
    a document never changes, so once stored it is never fetched again.
  * summaries are keyed by the document's `text_hash`, not by bill or date, so
    a bill that acts on five days is summarized once. That is what makes
    "summarize once a day, keep everything" actually hold.
"""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


class StoreError(Exception):
    """Raised when the backing store cannot be reached."""


class LocalStore:
    """Filesystem-backed store for development."""

    def __init__(self, root="store_data"):
        self._root = Path(root)

    def _path(self, key) -> Path:
        return self._root / key

    def get_json(self, key):
        target = self._path(key)
        if not target.exists():
            return None
        try:
            return json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StoreError(f"Could not read {key}") from exc

    def put_json(self, key, data) -> None:
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    def exists(self, key) -> bool:
        return self._path(key).exists()

    def verify(self) -> None:
        """Matches the R2 interface so callers need not care which backend."""
        probe = "_preflight/roundtrip.json"
        self.put_json(probe, {"ok": True})
        if self.get_json(probe) != {"ok": True}:
            raise StoreError(f"Local store roundtrip failed under {self._root}")

    def list_prefix(self, prefix) -> list:
        base = self._path(prefix)
        if not base.exists():
            return []
        return sorted(
            str(p.relative_to(self._root)) for p in base.rglob("*") if p.is_file()
        )


class R2Store:
    """Cloudflare R2 via its S3-compatible API.

    Credentials use R2_-prefixed variables on purpose. Reusing AWS_ACCESS_KEY_ID
    would collide with the Terraform state backend and with boto3's default
    chain -- a collision that has already cost us one confusing failure.
    """

    def __init__(self, bucket=None, account_id=None, access_key=None, secret_key=None):
        self._bucket = bucket or os.environ.get("R2_BUCKET")
        account = account_id or os.environ.get("R2_ACCOUNT_ID")
        access = access_key or os.environ.get("R2_ACCESS_KEY_ID")
        secret = secret_key or os.environ.get("R2_SECRET_ACCESS_KEY")

        missing = [
            name
            for name, value in (
                ("R2_BUCKET", self._bucket),
                ("R2_ACCOUNT_ID", account),
                ("R2_ACCESS_KEY_ID", access),
                ("R2_SECRET_ACCESS_KEY", secret),
            )
            if not value
        ]
        if missing:
            raise StoreError(f"R2 store missing configuration: {', '.join(missing)}")

        # Imported here so the local store works without boto3 installed.
        # pylint: disable=import-outside-toplevel
        import boto3
        from botocore.config import Config
        from botocore.exceptions import ClientError

        # Kept on the instance because boto3 is not imported at module scope.
        self._client_error = ClientError

        self._client = boto3.client(
            "s3",
            endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
            aws_access_key_id=access,
            aws_secret_access_key=secret,
            region_name="auto",
            config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
        )

    def _explain(self, exc, key, operation):
        """Turn an opaque S3 error code into something actionable.

        R2 has two credential systems and this project uses two buckets, so a
        raw `AccessDenied` traceback almost never points at the real mistake --
        which is usually the wrong one of four similar-looking values.
        """
        code = (getattr(exc, "response", {}).get("Error") or {}).get("Code", "")
        hints = {
            "AccessDenied": (
                f"credentials are valid but not authorised to {operation} in "
                f"bucket {self._bucket!r}. The token must be scoped to THIS "
                "bucket with Object Read & Write. The pylitical-tfstate token "
                "will not work here -- they are separate tokens."
            ),
            "NoSuchBucket": f"bucket {self._bucket!r} does not exist in this account.",
            "InvalidAccessKeyId": (
                "R2_ACCESS_KEY_ID is not recognised. It must be the 32-character "
                "Access Key ID from the S3-compatible section, not the token value."
            ),
            "SignatureDoesNotMatch": (
                "R2_SECRET_ACCESS_KEY does not match the access key ID "
                "(expected 64 hex characters)."
            ),
        }
        detail = hints.get(code) or f"{code or type(exc).__name__}: {exc}"
        return StoreError(f"R2 {operation} failed for {key!r}: {detail}")

    def get_json(self, key):
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            return json.loads(response["Body"].read().decode("utf-8"))
        except self._client.exceptions.NoSuchKey:
            return None
        except json.JSONDecodeError as exc:
            raise StoreError(f"Corrupt JSON at {key}") from exc
        except self._client_error as exc:
            raise self._explain(exc, key, "read") from exc

    def put_json(self, key, data) -> None:
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=json.dumps(data, sort_keys=True).encode("utf-8"),
                ContentType="application/json",
            )
        except self._client_error as exc:
            raise self._explain(exc, key, "write") from exc

    def exists(self, key) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except Exception:  # pylint: disable=broad-except
            return False

    def verify(self) -> None:
        """Read/write roundtrip against a scratch key. Raises StoreError if not.

        Cheaper to run at startup than to discover mid-collection, after the
        APIs have already been queried.
        """
        probe = "_preflight/roundtrip.json"
        self.put_json(probe, {"ok": True})
        if self.get_json(probe) != {"ok": True}:
            raise StoreError(f"R2 roundtrip mismatch in bucket {self._bucket!r}")

    def list_prefix(self, prefix) -> list:
        keys = []
        token = None
        while True:
            kwargs = {"Bucket": self._bucket, "Prefix": prefix}
            if token:
                kwargs["ContinuationToken"] = token
            response = self._client.list_objects_v2(**kwargs)
            keys.extend(item["Key"] for item in response.get("Contents", []))
            if not response.get("IsTruncated"):
                break
            token = response.get("NextContinuationToken")
        return sorted(keys)


def make_store(kind=None, **kwargs):
    """`local` or `r2`; defaults to whichever the environment is configured for."""
    kind = (
        kind
        or os.environ.get("PYLITICAL_STORE")
        or ("r2" if os.environ.get("R2_BUCKET") else "local")
    )
    if kind == "r2":
        return R2Store(**kwargs)
    if kind == "local":
        return LocalStore(**kwargs)
    raise StoreError(f"Unknown store kind: {kind!r}")


class UsageStore:
    """Adapts a store to the interface UsageTracker expects.

    Labelled so the two APIs keep separate ledgers -- they have different
    quotas and different reset windows, and merging them would make both
    meaningless.
    """

    def __init__(self, store, label="legiscan"):
        self._store = store
        self._label = label

    def load(self, bucket) -> dict:
        return self._store.get_json(f"usage/{self._label}/{bucket}.json") or {}

    def save(self, bucket, data) -> None:
        self._store.put_json(f"usage/{self._label}/{bucket}.json", data)


class Archive:
    """Domain operations over whichever store is configured."""

    def __init__(self, store):
        self._store = store

    # ---- daily archive -------------------------------------------------

    def load_day(self, state, day) -> list:
        return self._store.get_json(f"days/{state}/{day}.json") or []

    def save_day(self, state, day, bill_dicts) -> None:
        self._store.put_json(f"days/{state}/{day}.json", bill_dicts)
        self._touch_index(state, day, len(bill_dicts))

    def _touch_index(self, state, day, count) -> None:
        """Keep a per-state date index so the site can build navigation.

        Maintained incrementally rather than by listing the bucket: listing
        grows linearly with the archive and costs a request per 1000 keys.
        """
        key = f"index/{state}.json"
        index = self._store.get_json(key) or {"state": state, "days": {}}
        index["days"][day] = count
        self._store.put_json(key, index)

    def list_days(self, state) -> list:
        """`[{"date": ..., "count": ...}]`, newest first."""
        index = self._store.get_json(f"index/{state}.json") or {"days": {}}
        return [
            {"date": day, "count": count}
            for day, count in sorted(index["days"].items(), reverse=True)
        ]

    # ---- LegiScan change hashes ----------------------------------------

    def load_hashes(self, state) -> dict:
        return self._store.get_json(f"hashes/{state}.json") or {}

    def save_hashes(self, state, hashes) -> None:
        self._store.put_json(f"hashes/{state}.json", hashes)

    # ---- document text cache -------------------------------------------

    def get_document(self, doc_id):
        return self._store.get_json(f"docs/{doc_id}.json")

    def put_document(self, doc_id, document) -> None:
        self._store.put_json(f"docs/{doc_id}.json", document)

    # ---- summaries ------------------------------------------------------

    def get_summary(self, text_hash):
        if not text_hash:
            return None
        record = self._store.get_json(f"summaries/{text_hash}.json")
        return (record or {}).get("summary")

    def put_summary(self, text_hash, summary, meta=None) -> None:
        if not text_hash:
            return
        record = {"summary": summary}
        if meta:
            record.update(meta)
        self._store.put_json(f"summaries/{text_hash}.json", record)
