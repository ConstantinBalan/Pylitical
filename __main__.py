"""Daily run: collect one day per state, then rebuild the whole site.

    ./venv/bin/python __main__.py --states mi

Discovery comes from Open States, bill text from LegiScan, summaries from
Gemini, and everything is persisted to the archive store so the site can be
rebuilt from history rather than from a single scrape.
"""

import argparse
import logging
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from pylitical import (
    Archive,
    BillSummarizer,
    LegiScanClient,
    LegiScanError,
    OpenStatesClient,
    OpenStatesError,
    StoreError,
    UsageStore,
    legiscan_tracker,
    make_store,
    openstates_tracker,
    render_site,
    run_day,
    write_digest,
)
from pylitical.states import DEFAULT_STATE, SUPPORTED, by_code

# The legislature's day is a local concept, and the job runs late evening
# Eastern -- which is already tomorrow in UTC.
REPORT_TIMEZONE = ZoneInfo("America/Detroit")


def parse_args():
    parser = argparse.ArgumentParser(
        prog="pylitical",
        description="Collect and publish state legislative activity.",
    )
    parser.add_argument(
        "--states",
        default=DEFAULT_STATE,
        help=f"Comma-separated state codes (default: {DEFAULT_STATE})",
    )
    parser.add_argument(
        "--date", help="Day to collect, YYYY-MM-DD (default: today, Eastern)"
    )
    parser.add_argument(
        "--output-dir", default="output", help="Where to write the site"
    )
    parser.add_argument(
        "--store",
        choices=("local", "r2"),
        help="Archive backend (default: r2 when R2_BUCKET is set, else local)",
    )
    parser.add_argument(
        "--skip-text",
        action="store_true",
        help="Skip LegiScan and Gemini; metadata only, spends no quota",
    )
    parser.add_argument(
        "--skip-summaries",
        action="store_true",
        help="Fetch bill text but skip Gemini summarization",
    )
    parser.add_argument(
        "--digest-file", default="", help="Write the email digest payload here"
    )
    parser.add_argument(
        "--quota-summary",
        default="",
        help="Write a Markdown quota report here (e.g. $GITHUB_STEP_SUMMARY)",
    )
    return parser.parse_args()


def main():
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    load_dotenv()
    args = parse_args()

    day = args.date or datetime.now(REPORT_TIMEZONE).date().isoformat()
    states = _resolve_states(args.states)
    if states is None:
        return 2

    try:
        store = make_store(args.store)
    except StoreError:
        logging.exception("Could not open the archive store")
        return 1
    archive = Archive(store)

    os_tracker = openstates_tracker(UsageStore(store, "openstates"))
    ls_tracker = legiscan_tracker(UsageStore(store, "legiscan"))

    try:
        openstates = OpenStatesClient(tracker=os_tracker)
    except OpenStatesError as exc:
        logging.error("%s", exc)
        return 1

    legiscan, summarizer = _text_pipeline(args, ls_tracker)

    collected = []
    try:
        for state in states:
            report = run_day(
                state=state.code,
                jurisdiction=state.jurisdiction,
                day=day,
                archive=archive,
                openstates=openstates,
                legiscan=legiscan,
                summarizer=summarizer,
            )
            logging.info("%s", report.as_report())
            collected.extend(report.bills)
    except OpenStatesError:
        logging.exception("Collection failed; not republishing the site")
        return 1
    finally:
        os_tracker.flush()
        ls_tracker.flush()
        _write_quota_summary(args.quota_summary, os_tracker, ls_tracker)

    render_site(
        archive=archive,
        output_dir=args.output_dir,
        states=tuple(states),
        api_origin=os.environ.get("PYLITICAL_API_ORIGIN", ""),
        turnstile_sitekey=os.environ.get("PYLITICAL_TURNSTILE_SITEKEY", ""),
        default_state=states[0].code,
    )

    # No bills means no digest file, which is how the workflow knows to send
    # nothing. Quiet days are normal when legislatures are out of session.
    if args.digest_file:
        if collected:
            write_digest(collected, args.digest_file, day)
        else:
            logging.info("No activity on %s; skipping digest payload", day)

    logging.info("Done: open %s/index.html", args.output_dir)
    return 0


def _resolve_states(codes):
    """Parse `--states`, or None if any code is unknown."""
    resolved = []
    for code in (c.strip() for c in codes.split(",") if c.strip()):
        state = by_code(code)
        if state is None:
            logging.error(
                "Unknown state %r. Known: %s",
                code,
                ", ".join(s.code for s in SUPPORTED),
            )
            return None
        resolved.append(state)
    return resolved


def _text_pipeline(args, tracker):
    """LegiScan client and summarizer, or (None, None) when text is skipped.

    A missing LegiScan key is a warning rather than an error: the site still
    publishes Open States metadata, just without summaries.
    """
    if args.skip_text:
        return None, None
    try:
        legiscan = LegiScanClient(tracker=tracker)
    except LegiScanError as exc:
        logging.warning("%s -- continuing without bill text", exc)
        return None, None
    return legiscan, (None if args.skip_summaries else BillSummarizer())


def _write_quota_summary(path, *trackers) -> None:
    if not path:
        for tracker in trackers:
            logging.info("%s", tracker.projection())
        return
    with open(path, "a", encoding="utf-8") as handle:
        for tracker in trackers:
            handle.write(tracker.summary_markdown())
            handle.write("\n\n")


if __name__ == "__main__":
    sys.exit(main())
