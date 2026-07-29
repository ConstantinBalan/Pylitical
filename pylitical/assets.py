"""Static assets emitted alongside the HTML.

CSS and JS live in their own files rather than inline so the site's
Content-Security-Policy can stay at `'self'` with no `unsafe-inline`. That is
the single most valuable header here: the page interpolates AI-generated
summaries of scraped legislative documents, so an injection reaching the HTML
would otherwise be able to run script.

Design constraints, deliberately: one light theme (no dark mode), nothing under
16px, no uppercase letter-spaced eyebrows, no horizontally scrolling menus, and
status conveyed by grouping rather than per-item labels.
"""

STYLESHEET = """\
:root {
  --bg: #ffffff;
  --panel: #f5f7f9;
  --ink: #14161a;
  --ink-2: #454d57;
  --ink-3: #6a727c;
  --rule: #dde2e8;
  --rule-strong: #c3ccd6;
  --accent: #0f4c81;
}

* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
  font-size: 17px;
  line-height: 1.5;
}
.wrap { max-width: 44rem; margin: 0 auto; padding: 0 1.25rem; }
a { color: var(--accent); }

.masthead { padding: 2.25rem 0 0; }
.masthead h1 { font-size: 2rem; line-height: 1.15; margin: 0 0 .3rem; letter-spacing: -0.02em; }
.masthead h1 a { color: var(--ink); text-decoration: none; }
.masthead p { margin: 0; color: var(--ink-2); font-size: 1.0625rem; }

/* Wraps rather than scrolling sideways. */
.states {
  display: flex; flex-wrap: wrap; gap: .4rem 1.4rem;
  margin: 1.4rem 0 0; padding: 0 0 .9rem;
  border-bottom: 2px solid var(--rule-strong); list-style: none;
}
.states a { color: var(--ink-2); text-decoration: none; font-size: 1.0625rem; }
.states a:hover { color: var(--accent); }
.states a[aria-current="page"] { color: var(--ink); font-weight: 700; }
.states .pending { color: var(--ink-3); }

.daynav {
  display: flex; align-items: baseline; justify-content: space-between;
  gap: 1rem; flex-wrap: wrap; margin: 1.6rem 0 .3rem;
}
.daynav h2 { margin: 0; font-size: 1.5rem; letter-spacing: -0.01em; }
.daynav .links { font-size: 1rem; margin: 0; }
.daynav .links a { text-decoration: none; }
.daynav .links a:hover { text-decoration: underline; }
.daynav .links span { color: var(--ink-3); }
.count { color: var(--ink-2); font-size: 1rem; margin: .3rem 0 2rem; }

.group { margin: 0 0 2.25rem; }
.group > h3 {
  font-size: 1.0625rem; font-weight: 700; margin: 0;
  padding-bottom: .4rem; border-bottom: 1px solid var(--rule);
}

.bill { padding: 1.15rem 0; border-bottom: 1px solid var(--rule); }
.bill:last-child { border-bottom: 0; }
.bill h4 { margin: 0 0 .15rem; font-size: 1.1875rem; letter-spacing: -0.01em; }
.bill h4 a { color: var(--ink); text-decoration: none; }
.bill h4 a:hover { color: var(--accent); text-decoration: underline; }
.bill .official { margin: 0 0 .7rem; color: var(--ink-2); font-size: 1rem; }
.bill .summary {
  margin: 0; font-family: Georgia, "Iowan Old Style", serif;
  font-size: 1.0625rem; line-height: 1.6; white-space: pre-wrap;
}
.bill .absent { margin: 0; color: var(--ink-3); font-size: 1rem; }
.bill .meta { margin: .7rem 0 0; font-size: .9375rem; color: var(--ink-3); }
.bill .meta a { color: var(--ink-3); }

.nothing {
  border: 1px solid var(--rule); background: var(--panel);
  padding: 1.5rem; font-size: 1.0625rem; color: var(--ink-2); margin: 1.15rem 0 0;
}

.archive { list-style: none; padding: 0; margin: 1rem 0 0; }
.archive li { padding: .6rem 0; border-bottom: 1px solid var(--rule); font-size: 1.0625rem; }
.archive li a { text-decoration: none; }
.archive li a:hover { text-decoration: underline; }
.archive .n { color: var(--ink-3); font-size: 1rem; }

.subscribe {
  background: var(--panel); border: 1px solid var(--rule);
  padding: 1.5rem; margin: 2.5rem 0 0;
}
.subscribe h3 { margin: 0 0 .8rem; font-size: 1.25rem; }
.subscribe label.email { display: block; font-size: 1rem; margin-bottom: .35rem; }
.row { display: flex; gap: .5rem; flex-wrap: wrap; }
.row input {
  flex: 1 1 15rem; font: inherit; padding: .6rem .7rem;
  border: 1px solid var(--rule-strong); background: #fff; color: var(--ink);
}
.row button {
  font: inherit; font-weight: 600; padding: .6rem 1.4rem;
  border: 1px solid var(--accent); background: var(--accent); color: #fff; cursor: pointer;
}
.row button[disabled] { opacity: .6; cursor: default; }
.picker { border: 0; padding: 0; margin: 1.1rem 0 0; }
.picker legend { padding: 0; font-size: 1rem; margin-bottom: .4rem; }
.picker div { display: flex; gap: 1.2rem; flex-wrap: wrap; }
.picker label { font-size: 1rem; }
.fineprint { margin: 1.1rem 0 0; font-size: .9375rem; color: var(--ink-3); }
.status { margin: .9rem 0 0; font-size: 1rem; }
.status.error { color: #a3231b; }

.sitefoot {
  margin: 3rem 0 4rem; padding-top: 1.2rem; border-top: 1px solid var(--rule);
  font-size: .9375rem; color: var(--ink-3);
}
.sitefoot a { color: var(--ink-3); }
.sitefoot p { margin: 0 0 .35rem; }

.visually-hidden {
  position: absolute; width: 1px; height: 1px;
  overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap;
}
"""

# Every user-visible message is written with textContent, never innerHTML, so a
# hostile API response cannot inject markup into the page.
SUBSCRIBE_SCRIPT = """\
(function () {
  "use strict";

  var form = document.getElementById("subscribe-form");
  if (!form) return;

  var apiOrigin = form.getAttribute("data-api-origin");
  var email = document.getElementById("subscribe-email");
  var button = document.getElementById("subscribe-button");
  var status = document.getElementById("subscribe-status");

  function show(message, isError) {
    status.textContent = message;
    status.className = isError ? "status error" : "status";
  }

  function selectedStates() {
    var boxes = form.querySelectorAll("input[name='states']:checked");
    var out = [];
    for (var i = 0; i < boxes.length; i++) out.push(boxes[i].value);
    return out;
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();

    var states = selectedStates();
    if (states.length === 0) {
      show("Pick at least one state.", true);
      return;
    }

    var token = "";
    var widget = form.querySelector("[name='cf-turnstile-response']");
    if (widget) token = widget.value;
    if (!token) {
      show("Please complete the challenge and try again.", true);
      return;
    }

    button.disabled = true;
    show("Sending\\u2026", false);

    fetch(apiOrigin + "/subscribe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: email.value,
        states: states,
        turnstile_token: token
      })
    })
      .then(function (response) {
        return response.json().then(function (body) {
          return { ok: response.ok, body: body };
        });
      })
      .then(function (result) {
        if (result.ok) {
          show("Check your inbox for a confirmation link.", false);
          form.reset();
        } else if (result.body && result.body.error === "invalid_email") {
          show("That does not look like a valid email address.", true);
        } else if (result.body && result.body.error === "rate_limited") {
          show("Too many attempts. Try again in a minute.", true);
        } else {
          show("Could not sign you up right now. Try again later.", true);
        }
      })
      .catch(function () {
        show("Could not reach the server. Try again later.", true);
      })
      .then(function () {
        button.disabled = false;
        if (window.turnstile) window.turnstile.reset();
      });
  });
})();
"""

TURNSTILE_SCRIPT_ORIGIN = "https://challenges.cloudflare.com"


def build_headers_file(api_origin, has_subscribe_form) -> str:
    """Cloudflare Pages `_headers`: security headers on every response."""
    script_src = ["'self'"]
    frame_src = ["'none'"]
    connect_src = ["'none'"]

    if has_subscribe_form:
        script_src.append(TURNSTILE_SCRIPT_ORIGIN)
        frame_src = [TURNSTILE_SCRIPT_ORIGIN]
        connect_src = [api_origin]

    csp = "; ".join(
        [
            "default-src 'none'",
            f"script-src {' '.join(script_src)}",
            "style-src 'self'",
            "img-src 'self' data:",
            f"connect-src {' '.join(connect_src)}",
            f"frame-src {' '.join(frame_src)}",
            # The form submits with fetch(), never a native POST, so navigation
            # to any action URL should never be permitted.
            "form-action 'none'",
            "base-uri 'none'",
            "frame-ancestors 'none'",
        ]
    )

    return "\n".join(
        [
            "/*",
            f"  Content-Security-Policy: {csp}",
            "  X-Content-Type-Options: nosniff",
            "  Referrer-Policy: no-referrer",
            "  X-Frame-Options: DENY",
            "  Permissions-Policy: geolocation=(), microphone=(), camera=()",
            "  Strict-Transport-Security: max-age=63072000; includeSubDomains",
            "",
        ]
    )
