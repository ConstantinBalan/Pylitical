import html
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Michigan Bill Summaries</title>
<style>
  body {{ font-family: Georgia, serif; max-width: 46rem; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }}
  h2 {{ border-bottom: 1px solid #ccc; padding-bottom: 0.25rem; margin-top: 2.5rem; }}
  article {{ margin: 1.5rem 0; }}
  .summary {{ white-space: pre-wrap; background: #f7f7f4; padding: 1rem; border-radius: 6px; }}
  footer {{ margin-top: 3rem; color: #666; font-size: 0.85rem; }}
</style>
</head>
<body>
<h1>Michigan Bill Summaries</h1>
{sections}
<footer>Generated {generated_at} · Summaries are AI-generated and may contain errors.
Source: <a href="https://legislature.mi.gov/Bills/DailyReport">legislature.mi.gov</a></footer>
</body>
</html>
"""


def render(bills, output_dir) -> Path:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    bills_json = json.dumps([bill.as_dict() for bill in bills], indent=2)
    (out / "bills.json").write_text(bills_json, encoding="utf-8")
    (out / "index.html").write_text(_render_html(bills), encoding="utf-8")
    logger.info("Rendered %d bill(s) to %s", len(bills), out)
    return out


def _render_html(bills) -> str:
    sections = []
    for status in _statuses_in_order(bills):
        articles = [_render_bill(bill) for bill in bills if bill.status == status]
        sections.append(f"<h2>{html.escape(status)}</h2>\n" + "\n".join(articles))
    if not sections:
        sections.append("<p>No bills were reported for this period.</p>")

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return PAGE_TEMPLATE.format(sections="\n".join(sections), generated_at=generated_at)


def _render_bill(bill) -> str:
    title = html.escape(bill.name)
    if bill.source_url:
        title = f'<a href="{html.escape(bill.source_url)}">{title}</a>'
    summary = html.escape(bill.summary) if bill.summary else "No summary available."
    return (
        f'<article>\n<h3>{title}</h3>\n<div class="summary">{summary}</div>\n</article>'
    )


def _statuses_in_order(bills):
    return list(dict.fromkeys(bill.status for bill in bills))
