"""End-to-end LegiScan smoke test. Costs 4 API queries.

Walks the full chain the daily pipeline will use -- session, master list,
bill detail, document text -- and reports what MIME type the state actually
serves, which decides whether pypdf becomes a real dependency.

Usage:
    export LEGISCAN_API_KEY=...        # or put it in .env
    ./venv/bin/python probe_legiscan.py [MI]
"""

import logging
import sys

from dotenv import load_dotenv

from pylitical.legiscan import LegiScanClient, LegiScanError, pick_document
from pylitical.usage import QuotaExceededError, UsageTracker


def main():
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    load_dotenv()

    state = (sys.argv[1] if len(sys.argv) > 1 else "MI").upper()

    tracker = UsageTracker()
    try:
        client = LegiScanClient(tracker=tracker)
    except LegiScanError as exc:
        print(f"\n{exc}\n")
        return 1

    print(f"Starting month-to-date usage: {tracker.total}\n")

    try:
        sessions = client.session_list(state)
        if not sessions:
            print(f"No sessions returned for {state}.")
            return 1
        current = max(sessions, key=lambda s: s.get("year_end") or 0)
        years = f"{current.get('year_start')}-{current.get('year_end')}"
        print(
            f"1. session : {current.get('session_name')} "
            f"(id {current.get('session_id')}, {years})"
        )

        master = client.master_list_raw(session_id=current.get("session_id"))
        print(f"2. masterlist: {len(master)} bills, each with a change_hash")
        sample_number = next(iter(master))
        sample = master[sample_number]
        print(f"   e.g. {sample_number} -> {sample}")

        bill = client.bill(sample["bill_id"])
        print(
            f"3. bill    : {bill.get('bill_number')} — {(bill.get('title') or '')[:70]}"
        )
        print(f"   documents available: {len(bill.get('texts') or [])}")

        document = pick_document(bill)
        if not document:
            print("\n   No documents on this bill. Try another, or another state.")
            return 0
        chosen = f"{document.get('mime')}, {document.get('date')}"
        print(f"   chose doc_id {document.get('doc_id')} ({chosen})")

        text = client.bill_text(document["doc_id"])
        print(f"4. text    : {len(text.text)} chars, mime {text.mime}")
        print(f"\n   --- first 400 chars ---\n   {text.text[:400]}\n")

        if not text.text:
            print("   WARNING: no text extracted. If mime is a PDF, install pypdf.")
        if "pdf" in (text.mime or ""):
            print("   NOTE: this state serves PDFs — add pypdf to requirements.txt.")

    except QuotaExceededError as exc:
        print(f"\nStopped by the quota guard: {exc}\n")
        return 1
    except LegiScanError as exc:
        print(f"\nLegiScan error: {exc}\n")
        return 1
    finally:
        tracker.flush()

    print(f"Queries spent this run: {tracker.total}")
    print(f"\n{tracker.summary_markdown()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
