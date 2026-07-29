"""Static site generation.

Pages are rendered from the archive rather than from a single day's scrape, so
the whole history is rebuilt on every run. That is deliberate: it costs a few
seconds, keeps every page consistent when the design changes, and means a
corrupted page is fixed by the next run rather than persisting until someone
notices.

    /                          latest day for the default state
    /{state}/                  latest day for that state
    /{state}/{YYYY-MM-DD}/     one day
    /{state}/archive/          every day, newest first
    /{state}/{YYYY-MM-DD}/bills.json
"""

import html
import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path

from .assets import (
    STYLESHEET,
    SUBSCRIBE_SCRIPT,
    TURNSTILE_SCRIPT_ORIGIN,
    build_headers_file,
)
from .openstates import STATUS_ORDER
from .states import DEFAULT_STATE, SUPPORTED

logger = logging.getLogger(__name__)

ATTRIBUTION = (
    'Bill data from <a href="https://openstates.org/">Open States</a> and '
    '<a href="https://legiscan.com/">LegiScan</a>, licensed under '
    '<a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>.'
)


def render_site(  # pylint: disable=too-many-arguments
    *,
    archive,
    output_dir,
    states=SUPPORTED,
    api_origin="",
    turnstile_sitekey="",
    default_state=DEFAULT_STATE,
) -> Path:
    """Rebuild the entire site from the archive."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    has_form = bool(api_origin and turnstile_sitekey)
    if not has_form:
        logger.info("No API origin or Turnstile sitekey; rendering without signup form")

    out.joinpath("styles.css").write_text(STYLESHEET, encoding="utf-8")
    out.joinpath("_headers").write_text(
        build_headers_file(api_origin, has_form), encoding="utf-8"
    )
    if has_form:
        out.joinpath("subscribe.js").write_text(SUBSCRIBE_SCRIPT, encoding="utf-8")

    context = {
        "states": states,
        "api_origin": api_origin,
        "sitekey": turnstile_sitekey,
        "has_form": has_form,
    }

    pages = sum(_render_state(out, state, archive, context) for state in states)
    _write(out / "index.html", _root_page(archive, default_state, depth=0, **context))
    logger.info("Rendered %d day page(s) across %d state(s)", pages, len(states))
    return out


# ---------------------------------------------------------------- pages


def _render_state(out, state, archive, context) -> int:
    """Write every page for one state. Returns how many day pages were written."""
    days = archive.list_days(state.code)

    for position, entry in enumerate(days):
        day = entry["date"]
        bills = archive.load_day(state.code, day)
        newer = days[position - 1]["date"] if position > 0 else None
        older = days[position + 1]["date"] if position + 1 < len(days) else None

        _write(
            out / state.code / day / "index.html",
            _day_page(state, day, bills, newer, older, depth=2, **context),
        )
        _write_json(out / state.code / day / "bills.json", bills)

    _write(
        out / state.code / "archive" / "index.html",
        _archive_page(state, days, depth=2, **context),
    )

    # The state root mirrors its latest day so /mi/ is always current.
    if days:
        latest = days[0]["date"]
        _write(
            out / state.code / "index.html",
            _day_page(
                state,
                latest,
                archive.load_day(state.code, latest),
                None,
                days[1]["date"] if len(days) > 1 else None,
                depth=1,
                **context,
            ),
        )
    return len(days)


def _root_page(archive, default_state, *, depth, states, **context):
    state = next((s for s in states if s.code == default_state), states[0])
    days = archive.list_days(state.code)
    if not days:
        return _day_page(
            state, None, [], None, None, depth=depth, states=states, **context
        )
    latest = days[0]["date"]
    older = days[1]["date"] if len(days) > 1 else None
    return _day_page(
        state,
        latest,
        archive.load_day(state.code, latest),
        None,
        older,
        depth=depth,
        states=states,
        **context,
    )


def _day_page(
    state, day, bills, newer, older, *, depth, states, api_origin, sitekey, has_form
):
    # pylint: disable=too-many-arguments,too-many-positional-arguments
    root = "../" * depth
    heading = _pretty_date(day) if day else "No activity yet"

    if bills:
        # "recorded", not "happened". Legislatures journal actions in batches,
        # so a governor's signature dated today may describe an event from a
        # week ago -- the action description carries the real date.
        count = f"{len(bills)} item{'s' if len(bills) != 1 else ''} recorded."
        body = _grouped_bills(bills)
    else:
        count = ""
        body = (
            '<p class="nothing">'
            f"The {html.escape(state.name)} legislature recorded nothing on "
            f"{html.escape(_pretty_date(day))}."
            "</p>"
            if day
            else '<p class="nothing">Nothing has been archived yet.</p>'
        )

    main = f"""    <div class="daynav">
      <h2>{html.escape(heading)}</h2>
      <p class="links">{_day_nav(state, root, newer, older)}</p>
    </div>
    <p class="count">{count} <a href="{root}{state.code}/archive/">Browse earlier days</a></p>
{body}
{_subscribe_block(states, state, api_origin, sitekey, has_form)}"""

    return _shell(
        state, states, main, root, has_form, title=f"{state.name} — {heading}"
    )


def _day_nav(state, root, newer, older) -> str:
    links = []
    if older:
        links.append(
            f'<a href="{root}{state.code}/{older}/">&larr; '
            f"{_pretty_date(older, short=True)}</a>"
        )
    if newer:
        links.append(
            f'<a href="{root}{state.code}/{newer}/">'
            f"{_pretty_date(newer, short=True)} &rarr;</a>"
        )
    return " &nbsp; ".join(links) or "<span>No other days yet</span>"


def _archive_page(state, days, *, depth, states, api_origin, sitekey, has_form):
    # pylint: disable=too-many-arguments,too-many-positional-arguments
    root = "../" * depth
    if days:
        items = "\n".join(
            f'      <li><a href="{root}{state.code}/{d["date"]}/">'
            f'{html.escape(_pretty_date(d["date"]))}</a> <span class="n">'
            f'{d["count"]} item{"s" if d["count"] != 1 else ""}</span></li>'
            for d in days
        )
        listing = f'    <ul class="archive">\n{items}\n    </ul>'
    else:
        listing = '    <p class="nothing">Nothing archived yet.</p>'

    main = f"""    <div class="daynav">
      <h2>{html.escape(state.name)} archive</h2>
      <p class="links"><a href="{root}{state.code}/">Latest day</a></p>
    </div>
    <p class="count">{len(days)} day{'s' if len(days) != 1 else ''} recorded.</p>
{listing}
{_subscribe_block(states, state, api_origin, sitekey, has_form)}"""

    return _shell(state, states, main, root, has_form, title=f"{state.name} archive")


# ---------------------------------------------------------------- parts


def _shell(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    state, states, main, root, has_form, title
):
    tabs = "\n".join(
        f'      <li><a href="{root}{s.code}/"'
        f'{" aria-current=\"page\"" if s.code == state.code else ""}>{html.escape(s.name)}</a></li>'
        for s in states
    )
    scripts = (
        f'<script src="{TURNSTILE_SCRIPT_ORIGIN}/turnstile/v0/api.js" async defer></script>\n'
        f'<script src="{root}subscribe.js" defer></script>'
        if has_form
        else ""
    )
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<link rel="stylesheet" href="{root}styles.css">
</head>
<body>
<div class="wrap">

  <header class="masthead">
    <h1><a href="{root}">Pylitical</a></h1>
    <p>Plain-English summaries of state legislative activity.</p>
    <ul class="states">
{tabs}
    </ul>
  </header>

  <main>
{main}
  </main>

  <footer class="sitefoot">
    <p>Summaries are AI-generated and may contain errors. Read the bill before relying on it.</p>
    <p>{ATTRIBUTION}</p>
    <p>Generated {generated}.</p>
  </footer>

</div>
{scripts}
</body>
</html>
"""


def _grouped_bills(bills):
    known = list(STATUS_ORDER)
    seen = {b.get("status") for b in bills}
    order = [s for s in known if s in seen] + sorted(seen - set(known))

    sections = []
    for status in order:
        entries = [b for b in bills if b.get("status") == status]
        rendered = "\n".join(_bill_entry(b) for b in entries)
        sections.append(
            f'    <section class="group">\n'
            f"      <h3>{html.escape(status or 'Other')}</h3>\n{rendered}\n    </section>"
        )
    return "\n".join(sections)


def _bill_entry(bill):
    name = html.escape(bill.get("name") or "Untitled")
    url = bill.get("source_url")
    heading = f'<a href="{html.escape(url)}">{name}</a>' if url else name

    title = bill.get("title")
    title_line = (
        f'\n        <p class="official">{html.escape(title)}</p>' if title else ""
    )

    summary = bill.get("summary")
    if summary:
        body = f'<p class="summary">{html.escape(summary)}</p>'
    else:
        body = '<p class="absent">No summary available for this item.</p>'

    meta = []
    if bill.get("sponsor"):
        meta.append(f"Sponsored by {html.escape(bill['sponsor'])}.")
    if bill.get("action_description"):
        meta.append(html.escape(bill["action_description"]))
    meta_line = f'\n        <p class="meta">{" ".join(meta)}</p>' if meta else ""

    return f"""      <article class="bill">
        <h4>{heading}</h4>{title_line}
        {body}{meta_line}
      </article>"""


def _subscribe_block(states, current, api_origin, sitekey, has_form):
    if not has_form:
        return ""
    boxes = "\n".join(
        f'            <label><input type="checkbox" name="states" value="{s.code}"'
        f'{" checked" if s.code == current.code else ""}> {html.escape(s.name)}</label>'
        for s in states
    )
    return f"""
    <section class="subscribe">
      <h3>Get this by email</h3>
      <form id="subscribe-form" data-api-origin="{html.escape(api_origin, quote=True)}">
        <label class="email" for="subscribe-email">Email address</label>
        <div class="row">
          <input id="subscribe-email" type="email" name="email" required
                 autocomplete="email" placeholder="you@example.com" maxlength="254">
          <button type="submit" id="subscribe-button">Subscribe</button>
        </div>
        <fieldset class="picker">
          <legend>States</legend>
          <div>
{boxes}
          </div>
        </fieldset>
        <div class="cf-turnstile" data-sitekey="{html.escape(sitekey, quote=True)}"></div>
        <p class="fineprint">Nothing is sent on days without activity. Unsubscribe from any email.</p>
        <p class="status" id="subscribe-status"></p>
      </form>
    </section>"""


# ---------------------------------------------------------------- helpers


def _pretty_date(value, short=False) -> str:
    if not value:
        return ""
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        return value
    return parsed.strftime("%a, %b %-d") if short else parsed.strftime("%A, %B %-d, %Y")


def _write(path, content) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json(path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
