"""CLI entrypoint: scrape MI legislature bills, summarize, render a static site."""

import argparse
import logging
import time

from dotenv import load_dotenv

from pylitical import (
    BillScraper,
    BillSummarizer,
    ScraperError,
    SummarizerError,
    render,
)

SUMMARY_DELAY_SECONDS = 2


def parse_args():
    parser = argparse.ArgumentParser(
        prog="pylitical",
        description="Summarize bills from the Michigan legislature daily report.",
    )
    parser.add_argument("--start-date", help="Range start, YYYY-MM-DD (default: today)")
    parser.add_argument("--end-date", help="Range end, YYYY-MM-DD")
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Where to write bills.json and index.html",
    )
    parser.add_argument(
        "--skip-summaries",
        action="store_true",
        help="Scrape and render without calling the Gemini API (no key needed)",
    )
    return parser.parse_args()


def main():
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    load_dotenv()
    args = parse_args()

    scraper = BillScraper()
    bills = scraper.find(args.start_date, args.end_date)
    logging.info("Scraped %d bill(s)", len(bills))

    if bills and not args.skip_summaries:
        summarizer = BillSummarizer()
        for index, bill in enumerate(bills):
            if index:
                time.sleep(SUMMARY_DELAY_SECONDS)
            try:
                bill.summary = summarizer.summarize(bill, scraper.get_bill_text(bill))
            except ScraperError:
                # A single unreachable document shouldn't sink the run.
                logging.exception("Skipping %r", bill.name)
            except SummarizerError:
                # API failures (quota, outage) will likely repeat; stop
                # calling but still render the summaries we already have.
                logging.exception("Summarization stopped early")
                break

    output_dir = render(bills, args.output_dir)
    logging.info("Done: open %s/index.html", output_dir)


if __name__ == "__main__":
    main()
