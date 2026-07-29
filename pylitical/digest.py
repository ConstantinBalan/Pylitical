"""Builds the payload POSTed to the Worker's /admin/send-digest endpoint.

Deliberately data-only: no HTML, no rendered email body. The Worker renders and
escapes the message itself, so a compromised CI pipeline cannot put arbitrary
markup or off-site links into mail signed by our domain. Keep it that way.

The file is written outside the site output directory so it is never deployed
to Pages -- not because the contents are sensitive (they are public
legislative records) but because the site should only ever contain the site.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# The legislature's "daily report" is a Michigan-local concept, and the job runs
# at 02:30 UTC -- which is still the previous evening in Detroit. Using the
# runner's UTC clock would label every digest a day ahead of the bills in it,
# and would desynchronize the Worker's per-date replay guard from the content.
REPORT_TIMEZONE = ZoneInfo("America/Detroit")


def local_report_date():
    return datetime.now(REPORT_TIMEZONE).date()


def build_payload(bills, digest_date=None) -> dict:
    return {
        "date": (digest_date or local_report_date()).isoformat(),
        "bills": [
            {
                "name": bill.name,
                "status": bill.status,
                "source_url": bill.source_url,
                "summary": bill.summary,
            }
            for bill in bills
        ],
    }


def write_digest(bills, path, digest_date=None) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = build_payload(bills, digest_date)
    destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info(
        "Wrote digest payload with %d bill(s) to %s", len(payload["bills"]), destination
    )
    return destination
