"""Answers the question that decides the whole Open States migration:

    does this state actually publish usable bill abstracts?

Open States links to bill documents rather than hosting their text, and for
Michigan those links point at the CAPTCHA-blocked legislature site. So the only
text we can summarize is the official abstract. If coverage is high, summaries
stay rich. If it is low, most bills would show titles only, and the product
needs rethinking before any more is built on top of it.

Usage:
    export OPENSTATES_API_KEY=...
    ./venv/bin/python probe_openstates.py Michigan [Ohio ...]
"""

import logging
import sys

from dotenv import load_dotenv

from pylitical.openstates import (
    OpenStatesClient,
    OpenStatesError,
    derive_status,
    probe_abstracts,
    summarizable_text,
)

DEFAULT_JURISDICTIONS = ["Michigan"]
SAMPLE_COUNT = 3


def main():
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    load_dotenv()

    jurisdictions = sys.argv[1:] or DEFAULT_JURISDICTIONS

    try:
        client = OpenStatesClient()
    except OpenStatesError as exc:
        print(f"\n{exc}\n")
        return 1

    for jurisdiction in jurisdictions:
        try:
            stats = probe_abstracts(client, jurisdiction, days=30)
        except OpenStatesError as exc:
            print(f"\n{jurisdiction}: {exc}\n")
            continue

        total = stats["total_bills"]
        print(f"\n{'=' * 62}\n{jurisdiction} — last {stats['days']} days\n{'=' * 62}")
        if not total:
            print("No bills with activity. Try a longer window or another state.")
            continue

        print(f"  bills with activity : {total}")
        print(
            f"  with an abstract    : {stats['with_abstract']} "
            f"({stats['abstract_coverage']:.0%})"
        )
        print(f"  title only          : {stats['title_only']}")
        print(f"  nothing usable      : {stats['nothing_usable']}")
        print(
            f"  abstract length     : median {stats['median_abstract_chars']}, "
            f"range {stats['shortest_abstract']}–{stats['longest_abstract']} chars"
        )

        verdict = _verdict(stats)
        print(f"\n  VERDICT: {verdict}")

        _print_samples(client, jurisdiction, stats["days"])

    return 0


def _verdict(stats) -> str:
    coverage = stats["abstract_coverage"]
    median = stats["median_abstract_chars"]
    if coverage >= 0.8 and median >= 200:
        return "Good. Abstracts are present and substantial; summaries will be useful."
    if coverage >= 0.8:
        return (
            f"Mixed. Nearly all bills have an abstract, but the median is only {median} "
            "chars — summaries may just restate it. Consider showing abstracts directly "
            "and skipping the LLM for short ones."
        )
    if coverage >= 0.4:
        return (
            f"Thin. Only {coverage:.0%} have abstracts; the rest would show titles only. "
            "Worth deciding whether a title-only entry is acceptable on the page."
        )
    return (
        f"Poor. Just {coverage:.0%} have abstracts. Summarizing is not viable from this "
        "source alone — reconsider the approach before building further."
    )


def _print_samples(client, jurisdiction, days):
    from datetime import date, timedelta  # pylint: disable=import-outside-toplevel

    since = date.today() - timedelta(days=days)
    raw_bills = client.raw_bills_with_action_since(jurisdiction, since, max_pages=1)

    print(f"\n  --- {min(SAMPLE_COUNT, len(raw_bills))} sample(s) ---")
    for raw in raw_bills[:SAMPLE_COUNT]:
        status, action_date, description = derive_status(raw, since.isoformat())
        text = summarizable_text(raw)
        print(f"\n  {raw.get('identifier')} · {status} · {action_date}")
        print(f"    latest action: {(description or '')[:80]}")
        print(f"    text to summarize ({len(text)} chars):")
        print(f"      {text[:300]}{'...' if len(text) > 300 else ''}")


if __name__ == "__main__":
    sys.exit(main())
