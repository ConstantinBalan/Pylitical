"""API quota accounting for both upstream APIs.

Neither reports how much of your allowance remains, so the count has to be
ours. They have different shapes: LegiScan allows 30,000 queries per *month*,
Open States' default tier 500 per *day*. The daily one is the easier of the two
to exhaust by accident, since a multi-day backfill hits it immediately. Losing track
means the daily job starts failing partway through a month with no warning,
which is exactly the silent-degradation failure we already got bitten by.

Two jobs here:
  * keep an auditable month-to-date count, broken down by operation
  * refuse to spend past a safety margin, so a runaway backfill cannot burn the
    month's allowance in an afternoon
"""

import calendar
import json
import logging
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

LEGISCAN_MONTHLY_QUOTA = 30000

# Open States' default tier for new keys. Much tighter than LegiScan's, and a
# daily window rather than a monthly one -- a multi-day backfill is the thing
# most likely to exhaust it.
OPENSTATES_DAILY_QUOTA = 500

# Stop well short of the wall. The remaining headroom is what lets you run a
# manual backfill or re-run a failed day without being locked out.
DEFAULT_STOP_AT = 0.90
DEFAULT_WARN_AT = 0.70

PERIOD_FORMATS = {"month": "%Y-%m", "day": "%Y-%m-%d"}


class QuotaExceededError(Exception):
    """Raised when a call would push usage past the configured stop threshold."""


class LocalUsageStore:
    """Period-keyed JSON on disk. Fine for local runs; CI uses the R2 store."""

    def __init__(self, path="usage", label="legiscan"):
        self._dir = Path(path) / label

    def load(self, month) -> dict:
        target = self._dir / f"{month}.json"
        if not target.exists():
            return {}
        try:
            return json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Could not read usage for %s; starting from zero", month)
            return {}

    def save(self, month, data) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        (self._dir / f"{month}.json").write_text(
            json.dumps(data, indent=2, sort_keys=True), encoding="utf-8"
        )


class UsageTracker:
    """Counts API calls for the current month and enforces a spend ceiling."""

    # pylint: disable=too-many-instance-attributes

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        store=None,
        quota=LEGISCAN_MONTHLY_QUOTA,
        stop_at=DEFAULT_STOP_AT,
        warn_at=DEFAULT_WARN_AT,
        today=None,
        period="month",
        label="LegiScan",
    ):
        if period not in PERIOD_FORMATS:
            raise ValueError(f"period must be one of {sorted(PERIOD_FORMATS)}")
        self._store = store or LocalUsageStore()
        self._quota = quota
        self._stop_at = stop_at
        self._warn_at = warn_at
        self._today = today or date.today()
        self._period = period
        self._label = label
        self._month = self._today.strftime(PERIOD_FORMATS[period])
        self._data = self._store.load(self._month)
        self._data.setdefault("operations", {})
        self._data.setdefault("total", 0)
        self._warned = False

    @property
    def total(self) -> int:
        return self._data["total"]

    @property
    def remaining(self) -> int:
        return max(0, self._quota - self.total)

    @property
    def ceiling(self) -> int:
        """The self-imposed stop, below the hard quota."""
        return int(self._quota * self._stop_at)

    def check(self, needed=1) -> None:
        """Raise if spending `needed` more calls would cross the ceiling."""
        if self.total + needed > self.ceiling:
            raise QuotaExceededError(
                f"{self._label} usage {self.total}/{self._quota} for {self._month} "
                f"would cross the {self._stop_at:.0%} safety ceiling ({self.ceiling}). "
                f"Reduce states per run, or wait for the {self._period} to roll over."
            )

    def record(self, operation, count=1) -> None:
        self._data["total"] += count
        operations = self._data["operations"]
        operations[operation] = operations.get(operation, 0) + count

        if not self._warned and self.total >= self._quota * self._warn_at:
            self._warned = True
            logger.warning(
                "%s usage at %d/%d (%.0f%%) for %s",
                self._label,
                self.total,
                self._quota,
                100 * self.total / self._quota,
                self._month,
            )

    def flush(self) -> None:
        self._data["month"] = self._month
        self._data["quota"] = self._quota
        self._data["updated"] = self._today.isoformat()
        self._store.save(self._month, self._data)

    def projection(self) -> dict:
        """Usage so far, extrapolated to the end of the window where meaningful.

        Extrapolation only makes sense monthly. A daily quota resets before any
        trend could be acted on, so it reports the raw count instead.
        """
        if self._period == "day":
            days_in_month, elapsed, projected = 1, 1, self.total
        else:
            days_in_month = calendar.monthrange(self._today.year, self._today.month)[1]
            elapsed = self._today.day
            projected = round(self.total / elapsed * days_in_month) if elapsed else 0
        return {
            "label": self._label,
            "period": self._period,
            "month": self._month,
            "used": self.total,
            "quota": self._quota,
            "remaining": self.remaining,
            "ceiling": self.ceiling,
            "percent_used": (self.total / self._quota) if self._quota else 0.0,
            "days_elapsed": elapsed,
            "days_in_month": days_in_month,
            "projected_month_end": projected,
            "on_track": projected <= self.ceiling,
            "operations": dict(self._data["operations"]),
        }

    def summary_markdown(self) -> str:
        """Rendered into the GitHub Actions run page each night."""
        p = self.projection()
        status = (
            "✅ on track" if p["on_track"] else "⚠️ projected to exceed the ceiling"
        )
        lines = [
            f"### {p['label']} quota — {p['month']}",
            "",
            f"**{p['used']:,} / {p['quota']:,} used ({p['percent_used']:.1%})** · {status}",
            "",
            "| | |",
            "|---|---|",
            f"| Remaining | {p['remaining']:,} |",
            f"| Safety ceiling | {p['ceiling']:,} |",
        ]
        if p["period"] == "month":
            lines += [
                f"| Day of month | {p['days_elapsed']} of {p['days_in_month']} |",
                f"| Projected month end | {p['projected_month_end']:,} |",
            ]
        if p["operations"]:
            lines += ["", "| Operation | Calls |", "|---|---|"]
            for name, count in sorted(p["operations"].items(), key=lambda kv: -kv[1]):
                lines.append(f"| `{name}` | {count:,} |")
        return "\n".join(lines)


def legiscan_tracker(store=None, **kwargs) -> UsageTracker:
    """30,000 per calendar month."""
    return UsageTracker(
        store=store or LocalUsageStore(label="legiscan"),
        quota=LEGISCAN_MONTHLY_QUOTA,
        period="month",
        label="LegiScan",
        **kwargs,
    )


def openstates_tracker(store=None, **kwargs) -> UsageTracker:
    """500 per day on the default tier, so a backfill is the real risk."""
    return UsageTracker(
        store=store or LocalUsageStore(label="openstates"),
        quota=OPENSTATES_DAILY_QUOTA,
        period="day",
        label="Open States",
        **kwargs,
    )
