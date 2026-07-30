"""The daily run: discover, fetch text, summarize, archive.

Open States decides *what* to look at; LegiScan supplies text for those bills
only. That ordering is deliberate and is what keeps the cold start cheap: the
LegiScan master list for a Michigan session holds ~3,900 bills, so a
change_hash sweep over all of them on a first run would cost roughly a quarter
of the monthly quota. Driving from Open States means we only ever touch the
few tens of bills that actually moved today.

Every expensive thing is cached by identity rather than by date:
  * document text by `doc_id` (LegiScan marks it Static -- it never changes)
  * summaries by the document's `text_hash`, so a bill that acts on five days
    is summarized once
"""

import logging
import re

from .legiscan import LegiScanError, pick_document
from .openstates import OpenStatesError
from .summarizer import SummarizerError
from .usage import QuotaExceededError

logger = logging.getLogger(__name__)

# Long bills (appropriations especially) run to hundreds of pages. Summarizing
# the opening section is honest and cheap; sending the whole thing is neither.
MAX_SUMMARY_INPUT_CHARS = 30000


def normalize_bill_number(identifier) -> str:
    """Reduce an identifier to a form both APIs agree on.

    Two differences to reconcile:
      * Open States spaces the identifier (`"SR 135"`), LegiScan does not
      * LegiScan zero-pads the number to four digits (`"SR0135"`)

    The padding mattered more than it looks. Michigan numbers House bills from
    4001, so they are naturally four digits and matched without stripping zeros
    -- while every Senate bill, which numbers from 1, silently failed to match
    and lost its summary. Lettered joint resolutions (`HJRF`) have no digits at
    all and pass through untouched.
    """
    cleaned = re.sub(r"[^A-Z0-9]", "", (identifier or "").upper())
    return re.sub(r"0*(\d+)", r"\1", cleaned)


class DailyRun:
    """One state, one day. Collects counters so the caller can report."""

    # pylint: disable=too-many-instance-attributes

    def __init__(self, state, day):
        self.state = state
        self.day = day
        self.bills = []
        self.summarized = 0
        self.summaries_reused = 0
        self.documents_fetched = 0
        self.documents_cached = 0
        self.text_unavailable = 0
        self.errors = []
        self.quota_stopped = False

    def as_report(self) -> dict:
        return {
            "state": self.state,
            "day": self.day,
            "bills": len(self.bills),
            "summarized": self.summarized,
            "summaries_reused": self.summaries_reused,
            "documents_fetched": self.documents_fetched,
            "documents_cached": self.documents_cached,
            "text_unavailable": self.text_unavailable,
            "errors": len(self.errors),
            "quota_stopped": self.quota_stopped,
        }


class _Collaborators:
    """The services a run needs, bundled so helpers take arguments, not a crowd."""

    def __init__(self, run, archive, legiscan, summarizer):
        self.run = run
        self.archive = archive
        self.legiscan = legiscan
        self.summarizer = summarizer


def run_day(  # pylint: disable=too-many-arguments
    *,
    state,
    jurisdiction,
    day,
    archive,
    openstates,
    legiscan=None,
    summarizer=None,
) -> DailyRun:
    """Fetch, enrich, summarize, and archive one state-day.

    `legiscan` and `summarizer` are optional: without them the run still
    produces a complete archive entry, just without summaries. That makes a
    metadata-only dry run possible without spending any LegiScan quota.
    """
    run = DailyRun(state, day)

    try:
        bills = openstates.bills_with_action_since(jurisdiction, day)
    except OpenStatesError:
        logger.exception("Open States discovery failed for %s on %s", state, day)
        raise

    # Keep only bills whose action actually landed on this day. `action_since`
    # is inclusive of later days too when backfilling.
    bills = [b for b in bills if not b.action_date or b.action_date == day]
    logger.info("%s %s: %d bill(s) with action", state, day, len(bills))

    if bills and legiscan is not None:
        _enrich_with_text(_Collaborators(run, archive, legiscan, summarizer), bills)

    run.bills = bills
    archive.save_day(state, day, [b.as_dict() for b in bills])
    return run


def _enrich_with_text(ctx, bills):
    """Attach summaries, spending as few LegiScan queries as possible."""
    run = ctx.run
    stored_hashes = ctx.archive.load_hashes(run.state)

    try:
        master = ctx.legiscan.master_list_raw(state=run.state.upper())
    except (LegiScanError, QuotaExceededError) as exc:
        # Without the master list there is no bill_id, so no text this run.
        # The archive entry is still written from Open States metadata.
        logger.warning("No LegiScan master list for %s: %s", run.state, exc)
        run.errors.append(str(exc))
        run.quota_stopped = isinstance(exc, QuotaExceededError)
        return

    lookup = {normalize_bill_number(number): entry for number, entry in master.items()}
    fresh_hashes = dict(stored_hashes)

    for bill in bills:
        key = normalize_bill_number(bill.name)
        entry = lookup.get(key)
        if not entry:
            logger.info("%s not in the LegiScan master list; no text", bill.name)
            run.text_unavailable += 1
            continue

        try:
            document = _document_for(ctx, bill, entry, stored_hashes, fresh_hashes)
        except QuotaExceededError as exc:
            logger.error("Quota ceiling reached; stopping text fetch: %s", exc)
            run.quota_stopped = True
            run.errors.append(str(exc))
            break
        except LegiScanError as exc:
            # One unavailable document should not sink the day.
            logger.warning("No text for %s: %s", bill.name, exc)
            run.errors.append(f"{bill.name}: {exc}")
            run.text_unavailable += 1
            continue

        if not document or not document.get("text"):
            run.text_unavailable += 1
            continue

        # Record the hash *and* the document it resolved to. Without the
        # doc_id, an unchanged bill still costs a getBill next run just to
        # rediscover a document we already have cached.
        fresh_hashes[key] = {
            "hash": entry.get("change_hash"),
            "doc_id": document.get("doc_id"),
        }

        if ctx.summarizer is not None:
            _summarize(ctx, bill, document)

    ctx.archive.save_hashes(run.state, fresh_hashes)
    _warn_on_systematic_misses(run, len(bills))


def _warn_on_systematic_misses(run, total) -> None:
    """A few unmatched bills are normal; most of them is a bug.

    Identifier formats differ between the two APIs, and a mismatch degrades
    silently -- the bills still publish, just without summaries. Worth shouting
    about rather than leaving to be noticed by eye.
    """
    if not total or not run.text_unavailable:
        return
    share = run.text_unavailable / total
    if share >= 0.25:
        logger.warning(
            "%s %s: %d of %d bills (%.0f%%) had no LegiScan match. That usually "
            "means an identifier format mismatch, not missing data.",
            run.state,
            run.day,
            run.text_unavailable,
            total,
            100 * share,
        )


def _document_for(ctx, bill, entry, stored_hashes, fresh_hashes):
    """Return the cached or freshly-fetched document for a bill.

    Three chances to avoid a query, cheapest first:
      1. the change hash is unchanged and we recorded which document it mapped
         to, so neither getBill nor getBillText is needed
      2. the bill moved, but the document it now points at is already cached
      3. neither -- fetch, and cache for good (getBillText is Static)
    """
    key = normalize_bill_number(bill.name)
    previous = stored_hashes.get(key) or {}
    # Tolerate the older flat form, where the value was just the hash string.
    if isinstance(previous, str):
        previous = {"hash": previous}

    if previous.get("hash") == entry.get("change_hash") and previous.get("doc_id"):
        cached = ctx.archive.get_document(previous["doc_id"])
        if cached:
            ctx.run.documents_cached += 1
            fresh_hashes[key] = previous
            return cached

    chosen = pick_document(ctx.legiscan.bill(entry["bill_id"]))
    if not chosen:
        return None

    doc_id = chosen["doc_id"]
    cached = ctx.archive.get_document(doc_id)
    if cached:
        ctx.run.documents_cached += 1
        return cached

    record = ctx.legiscan.bill_text(doc_id).as_dict()
    ctx.archive.put_document(doc_id, record)
    ctx.run.documents_fetched += 1
    return record


def _summarize(ctx, bill, document):
    """Reuse a summary when the document text is byte-identical."""
    run, archive, summarizer = ctx.run, ctx.archive, ctx.summarizer
    text_hash = document.get("text_hash")

    existing = archive.get_summary(text_hash)
    if existing:
        bill.summary = existing
        run.summaries_reused += 1
        return

    body = document.get("text") or ""
    truncated = len(body) > MAX_SUMMARY_INPUT_CHARS
    if truncated:
        body = body[:MAX_SUMMARY_INPUT_CHARS]

    try:
        summary = summarizer.summarize(bill, body, truncated=truncated)
    except SummarizerError as exc:
        # Quota or outage: likely to repeat, so record and move on rather than
        # hammering the API for every remaining bill.
        logger.warning("Summarization failed for %s: %s", bill.name, exc)
        run.errors.append(f"{bill.name}: {exc}")
        return

    if not summary:
        return

    bill.summary = summary
    archive.put_summary(
        text_hash,
        summary,
        meta={
            "bill": bill.name,
            "state": bill.state,
            "doc_id": document.get("doc_id"),
            "truncated": truncated,
        },
    )
    run.summarized += 1
