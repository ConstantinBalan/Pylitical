"""LegiScan API client, used only for bill text.

Open States handles discovery and metadata; LegiScan supplies the document text
that Open States links to but does not host, and that Michigan's own site
serves behind a bot-protection interstitial.

Quota discipline is built in rather than bolted on. The public-service key
allows 30,000 queries a month with no way to ask how many remain, so:
  * every call is counted and checked against a ceiling before it is spent
  * `getBillText` is marked Static by LegiScan, so a document fetched once is
    never fetched again -- callers are expected to persist it
  * `getMasterListRaw` change hashes let us skip bills that have not moved
"""

import base64
import logging
import os
import time

import requests
from bs4 import BeautifulSoup

from .usage import UsageTracker

logger = logging.getLogger(__name__)

BASE_URL = "https://api.legiscan.com/"
USER_AGENT = "Pylitical/2.0 (+https://github.com/ConstantinBalan/Pylitical)"

FETCH_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 5
REQUEST_INTERVAL_SECONDS = 1.0

# Preference order when a bill has several documents. HTML and plain text are
# cheap and lossless to extract; PDF needs a parser and produces messier text.
_MIME_PREFERENCE = ("text/html", "text/plain", "application/pdf")


class LegiScanError(Exception):
    """Raised when the LegiScan API cannot be queried or returns an error."""


class BillText:
    """A decoded bill document."""

    # pylint: disable=too-many-arguments

    def __init__(self, *, doc_id, mime, text, date=None, doc_type=None, text_hash=None):
        self.doc_id = doc_id
        self.mime = mime
        self.text = text
        self.date = date
        self.doc_type = doc_type
        self.text_hash = text_hash

    def as_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "mime": self.mime,
            "text": self.text,
            "date": self.date,
            "doc_type": self.doc_type,
            "text_hash": self.text_hash,
        }

    def __repr__(self):
        return f"BillText(doc_id={self.doc_id!r}, mime={self.mime!r}, chars={len(self.text)})"


class LegiScanClient:
    """Thin client over the four operations this project needs."""

    def __init__(self, api_key=None, tracker=None, base_url=BASE_URL):
        self._api_key = api_key or os.environ.get("LEGISCAN_API_KEY")
        if not self._api_key:
            raise LegiScanError(
                "No LegiScan API key. Set LEGISCAN_API_KEY or pass api_key. "
                "Request one at https://legiscan.com/legiscan"
            )
        self._base_url = base_url
        self._tracker = tracker if tracker is not None else UsageTracker()
        self._session = requests.Session()
        self._session.headers["User-Agent"] = USER_AGENT
        self._last_request = 0.0

    @property
    def tracker(self) -> UsageTracker:
        return self._tracker

    def session_list(self, state) -> list:
        """Sessions for a state. Refresh weekly, not daily -- sessions rarely change."""
        return self._call("getSessionList", state=state).get("sessions") or []

    def master_list_raw(self, state=None, session_id=None) -> dict:
        """`{bill_number: {"bill_id": int, "change_hash": str}}` for a session.

        The change hash is the whole point: store it, and on the next run only
        bills whose hash moved need a `getBill` call.
        """
        params = {}
        if session_id is not None:
            params["id"] = session_id
        elif state is not None:
            params["state"] = state
        else:
            raise LegiScanError("master_list_raw needs a state or a session_id")

        payload = self._call("getMasterListRaw", **params)
        raw = payload.get("masterlist") or {}

        bills = {}
        for key, entry in raw.items():
            # The payload mixes a "session" metadata object in with the bills.
            if key == "session" or not isinstance(entry, dict):
                continue
            number = entry.get("number")
            if not number:
                continue
            bills[number] = {
                "bill_id": entry.get("bill_id"),
                "change_hash": entry.get("change_hash"),
            }
        return bills

    def bill(self, bill_id) -> dict:
        return self._call("getBill", id=bill_id).get("bill") or {}

    def bill_text(self, doc_id) -> BillText:
        """Fetch and decode a document. Static -- cache the result forever."""
        payload = self._call("getBillText", id=doc_id).get("text") or {}
        encoded = payload.get("doc") or ""
        mime = (payload.get("mime") or "").lower()

        try:
            raw = base64.b64decode(encoded)
        except (ValueError, TypeError) as exc:
            raise LegiScanError(f"Could not base64-decode doc_id {doc_id}") from exc

        return BillText(
            doc_id=payload.get("doc_id", doc_id),
            mime=mime,
            text=extract_text(raw, mime),
            date=payload.get("date"),
            doc_type=payload.get("type"),
            text_hash=payload.get("text_hash"),
        )

    def _call(self, operation, **params) -> dict:
        # Check before spending: the ceiling is meaningless if it is only
        # consulted after the request has already gone out.
        self._tracker.check(1)

        query = {"key": self._api_key, "op": operation, **params}
        last_exc = None
        for attempt in range(1, FETCH_ATTEMPTS + 1):
            self._pace()
            try:
                response = self._session.get(self._base_url, params=query, timeout=45)
                response.raise_for_status()
                payload = response.json()
            except requests.exceptions.RequestException as exc:
                last_exc = exc
                if attempt < FETCH_ATTEMPTS:
                    logger.warning("LegiScan %s failed (%s); retrying", operation, exc)
                    time.sleep(RETRY_DELAY_SECONDS * attempt)
                continue

            # A response was served, so the query is spent whether or not the
            # API liked it. Count it before inspecting the envelope.
            self._tracker.record(operation)

            if payload.get("status") != "OK":
                alert = payload.get("alert") or {}
                raise LegiScanError(
                    f"LegiScan {operation} returned "
                    f"{payload.get('status')}: {alert.get('message', 'no detail')}"
                )
            return payload

        raise LegiScanError(f"LegiScan {operation} failed after retries") from last_exc

    def _pace(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < REQUEST_INTERVAL_SECONDS:
            time.sleep(REQUEST_INTERVAL_SECONDS - elapsed)
        self._last_request = time.monotonic()


def pick_document(bill) -> dict:
    """Choose which of a bill's documents to fetch text for.

    Prefers the newest, breaking ties toward formats that extract cleanly.
    Returns an empty dict when the bill has no documents.
    """
    texts = [t for t in (bill.get("texts") or []) if t.get("doc_id")]
    if not texts:
        return {}

    def rank(entry):
        mime = (entry.get("mime") or "").lower()
        preference = (
            _MIME_PREFERENCE.index(mime)
            if mime in _MIME_PREFERENCE
            else len(_MIME_PREFERENCE)
        )
        return (entry.get("date") or "", -preference)

    return max(texts, key=rank)


def extract_text(raw_bytes, mime) -> str:
    """Turn a decoded document into plain text."""
    mime = (mime or "").lower()

    if "html" in mime:
        return _collapse(BeautifulSoup(raw_bytes, "html.parser").get_text(" "))
    if "pdf" in mime:
        return _collapse(_pdf_to_text(raw_bytes))
    if mime.startswith("text/") or not mime:
        return _collapse(raw_bytes.decode("utf-8", errors="replace"))

    logger.warning("Unsupported document MIME %r; skipping text extraction", mime)
    return ""


def _pdf_to_text(raw_bytes) -> str:
    # Lazy: most documents are HTML, so pypdf should not be a hard requirement
    # for anyone running the pipeline.
    try:
        import pypdf  # pylint: disable=import-outside-toplevel
    except ImportError:
        logger.warning("pypdf not installed; cannot extract PDF text")
        return ""

    import io  # pylint: disable=import-outside-toplevel

    try:
        reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("PDF extraction failed: %s", exc)
        return ""


def _collapse(text) -> str:
    return " ".join(text.split())
