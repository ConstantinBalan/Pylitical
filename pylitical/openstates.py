"""Open States API v3 client.

Replaces the legislature.mi.gov scraper, which broke when the site put a
CAPTCHA interstitial in front of every page (see BotChallengeError).

One important limitation carried over: Open States stores *links* to bill
documents, not their text (`BillDocumentLink` is only `url` + `media_type`),
and for Michigan those links point back at the blocked site. So summaries are
built from `abstracts` -- the official abstract the state supplies -- falling
back to the title. How well that works depends entirely on how consistently a
given state populates abstracts, which `probe_abstracts` measures.
"""

import logging
import os
import time
from datetime import date, timedelta

import requests

from .bill import Bill
from .usage import openstates_tracker

logger = logging.getLogger(__name__)

BASE_URL = "https://v3.openstates.org"
USER_AGENT = "Pylitical/2.0 (+https://github.com/ConstantinBalan/Pylitical)"

MAX_PER_PAGE = 20
FETCH_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 5
# Open States asks for gentle use on the free tier. One request per second is
# well inside any published limit and keeps us a good citizen of a free
# public-interest API.
REQUEST_INTERVAL_SECONDS = 1.0

INCLUDES = ("abstracts", "actions", "sponsorships", "sources", "versions")


class OpenStatesError(Exception):
    """Raised when the Open States API cannot be queried."""


# Open States action classifications, mapped onto the handful of stages a
# reader actually cares about. Ordered most-significant first: a bill that was
# both read and passed on the same day should read as "Passed a Chamber".
_STATUS_RULES = (
    ("Signed into Law", ("became-law", "executive-signature")),
    ("Vetoed", ("executive-veto",)),
    ("Failed", ("failure", "withdrawal")),
    ("Sent to Governor", ("enrolled", "executive-receipt")),
    ("Passed a Chamber", ("passage", "committee-passage")),
    ("In Committee", ("referral-committee", "committee-passage-favorable")),
    ("Introduced", ("introduction", "filing", "reading-1")),
)
FALLBACK_STATUS = "Other Action"

# Display order on the page, matching the legislative process.
STATUS_ORDER = (
    "Introduced",
    "In Committee",
    "Passed a Chamber",
    "Sent to Governor",
    "Signed into Law",
    "Vetoed",
    "Failed",
    FALLBACK_STATUS,
)


class OpenStatesClient:
    """Thin, paginated client for the /bills endpoint."""

    def __init__(self, api_key=None, base_url=BASE_URL, tracker=None):
        self._api_key = api_key or os.environ.get("OPENSTATES_API_KEY")
        if not self._api_key:
            raise OpenStatesError(
                "No Open States API key. Set OPENSTATES_API_KEY or pass api_key. "
                "Register free at https://open.pluralpolicy.com/"
            )
        self._base_url = base_url
        self._tracker = tracker if tracker is not None else openstates_tracker()
        self._session = requests.Session()
        self._session.headers.update(
            {"X-API-KEY": self._api_key, "User-Agent": USER_AGENT}
        )
        self._last_request = 0.0

    def raw_bills_with_action_since(self, jurisdiction, since, max_pages=25) -> list:
        """Raw API dicts for bills in `jurisdiction` active on or after `since`.

        The unparsed form exists so `probe_abstracts` can inspect fields that
        the Bill model deliberately drops.
        """
        since_str = since.isoformat() if isinstance(since, date) else str(since)

        raw_bills, page = [], 1
        while page <= max_pages:
            payload = self._get(
                "/bills",
                {
                    "jurisdiction": jurisdiction,
                    "action_since": since_str,
                    "include": list(INCLUDES),
                    "sort": "latest_action_desc",
                    "page": page,
                    "per_page": MAX_PER_PAGE,
                },
            )
            raw_bills.extend(payload.get("results") or [])

            pagination = payload.get("pagination") or {}
            if page >= (pagination.get("max_page") or 1):
                break
            page += 1

        logger.info(
            "Open States: %d bill(s) with action since %s in %s",
            len(raw_bills),
            since_str,
            jurisdiction,
        )
        return raw_bills

    def bills_with_action_since(self, jurisdiction, since, max_pages=25) -> list:
        """Bills in `jurisdiction` that saw activity on or after `since`.

        Returns Bill objects describing the most significant action in the
        window, not the bill's whole history.
        """
        since_str = since.isoformat() if isinstance(since, date) else str(since)
        state = _jurisdiction_code(jurisdiction)
        raw_bills = self.raw_bills_with_action_since(jurisdiction, since, max_pages)

        bills = []
        for raw in raw_bills:
            bill = _to_bill(raw, state, since_str)
            if bill is not None:
                bills.append(bill)
        return bills

    @property
    def tracker(self):
        return self._tracker

    def _get(self, path, params) -> dict:
        # Checked before the request goes out; the default tier allows only 500
        # a day, so a backfill can exhaust it in a couple of minutes.
        self._tracker.check(1)
        last_exc = None
        for attempt in range(1, FETCH_ATTEMPTS + 1):
            self._pace()
            try:
                response = self._session.get(
                    f"{self._base_url}{path}", params=params, timeout=30
                )
                # 429 is a quota problem, not a transient one. Back off hard
                # rather than burning the remaining allowance.
                if response.status_code == 429:
                    raise OpenStatesError(
                        "Open States rate limit hit. Reduce the number of states "
                        "per run or request a higher quota."
                    )
                response.raise_for_status()
                self._tracker.record(path.strip("/") or "root")
                return response.json()
            # OpenStatesError deliberately not caught here: it is not a
            # RequestException, so the 429 above propagates without retrying.
            except requests.exceptions.RequestException as exc:
                last_exc = exc
                if attempt < FETCH_ATTEMPTS:
                    logger.warning("Open States request failed (%s); retrying", exc)
                    time.sleep(RETRY_DELAY_SECONDS * attempt)
        raise OpenStatesError(f"Failed to query {path}") from last_exc

    def _pace(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < REQUEST_INTERVAL_SECONDS:
            time.sleep(REQUEST_INTERVAL_SECONDS - elapsed)
        self._last_request = time.monotonic()


def summarizable_text(raw) -> str:
    """Best available text to summarize: the official abstract, else the title.

    Deliberately does not follow `versions[].links[].url` -- those point at the
    state's own site, which is what we moved away from.
    """
    for abstract in raw.get("abstracts") or []:
        text = (abstract.get("abstract") or "").strip()
        if text:
            return text
    return (raw.get("title") or "").strip()


def probe_abstracts(client, jurisdiction, days=30) -> dict:
    """Measure how usable a jurisdiction's abstracts are.

    This is the question that decides whether the summaries are worth
    generating at all, so it is worth answering with data rather than hope.
    """
    since = date.today() - timedelta(days=days)
    raw_bills = client.raw_bills_with_action_since(jurisdiction, since)

    lengths, missing, titles_only = [], 0, 0
    for raw in raw_bills:
        abstract = ""
        for entry in raw.get("abstracts") or []:
            abstract = (entry.get("abstract") or "").strip()
            if abstract:
                break
        if abstract:
            lengths.append(len(abstract))
        elif (raw.get("title") or "").strip():
            titles_only += 1
        else:
            missing += 1

    total = len(raw_bills)
    return {
        "jurisdiction": jurisdiction,
        "days": days,
        "total_bills": total,
        "with_abstract": len(lengths),
        "title_only": titles_only,
        "nothing_usable": missing,
        "abstract_coverage": (len(lengths) / total) if total else 0.0,
        "median_abstract_chars": _median(lengths),
        "shortest_abstract": min(lengths) if lengths else 0,
        "longest_abstract": max(lengths) if lengths else 0,
    }


def derive_status(raw, since_str) -> tuple:
    """Bucket a bill by its most significant action in the window."""
    relevant = [
        action
        for action in (raw.get("actions") or [])
        if (action.get("date") or "")[:10] >= since_str
    ]
    if not relevant:
        relevant = raw.get("actions") or []
    if not relevant:
        return FALLBACK_STATUS, None, None

    classifications = {
        c for action in relevant for c in (action.get("classification") or [])
    }
    status = FALLBACK_STATUS
    for label, triggers in _STATUS_RULES:
        if classifications.intersection(triggers):
            status = label
            break

    latest = max(relevant, key=lambda a: a.get("date") or "")
    return status, (latest.get("date") or "")[:10], latest.get("description")


def _to_bill(raw, state, since_str):
    identifier = (raw.get("identifier") or "").strip()
    if not identifier:
        return None

    status, action_date, action_description = derive_status(raw, since_str)

    sponsor = None
    for sponsorship in raw.get("sponsorships") or []:
        if sponsorship.get("primary"):
            sponsor = sponsorship.get("name")
            break

    document_urls = [
        link.get("url")
        for version in (raw.get("versions") or [])
        for link in (version.get("links") or [])
        if link.get("url")
    ]

    return Bill(
        name=identifier,
        status=status,
        source_url=raw.get("openstates_url"),
        document_urls=document_urls,
        state=state,
        title=(raw.get("title") or "").strip() or None,
        sponsor=sponsor,
        action_date=action_date,
        action_description=action_description,
        classification=(raw.get("classification") or [None])[0],
    )


def _jurisdiction_code(jurisdiction) -> str:
    """'Michigan' or 'ocd-jurisdiction/country:us/state:mi/government' -> 'mi'."""
    text = str(jurisdiction).lower()
    if "state:" in text:
        return text.split("state:")[1].split("/")[0]
    return _STATE_CODES.get(text, text[:2])


_STATE_CODES = {
    "michigan": "mi",
    "ohio": "oh",
    "wisconsin": "wi",
    "indiana": "in",
    "illinois": "il",
    "minnesota": "mn",
}


def _median(values):
    if not values:
        return 0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) // 2
