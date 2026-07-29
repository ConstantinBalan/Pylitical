# Threat model — subscriptions and digest delivery

Scope: the Cloudflare Worker (`worker/`), its D1 database, the Pages site, and
the GitHub Actions pipeline that feeds them.

What is actually at stake, in order:

1. **Subscriber email addresses.** The only personal data in the system.
2. **The sending domain's reputation.** Abused once, delivery degrades for
   every legitimate reader, and recovery is slow.
3. **The ability to send mail as us.** A digest is a trusted, recurring message
   with links; that trust is what a phisher would want.
4. Availability and cost. Both are bounded by Cloudflare's free tier anyway.

---

## Attack surface

| Endpoint | Auth | Reachable by |
| --- | --- | --- |
| `POST /subscribe` | Turnstile only | anyone |
| `GET /confirm?t=` | single-use token | anyone with the token |
| `GET /unsubscribe?t=` | signed token | anyone with the token |
| `POST /unsubscribe?t=` | signed token | anyone with the token |
| `POST /admin/send-digest` | GitHub OIDC | the `main` branch of this repo |
| `GET /health` | none | anyone |

---

## Threats and mitigations

### T1 — Mail-bombing a third party via `/subscribe`

The classic abuse of any unauthenticated signup: submit a victim's address
repeatedly and let *our* domain deliver the harassment.

Five layers, deliberately overlapping because the cheap ones are approximate:

- Turnstile must be solved (`turnstile.ts`, fails closed on any error).
- Per-IP rate limit, 5/min.
- Per-address rate limit, 2/min, keyed on a hash of the address.
- **A 15-minute per-address cooldown in D1** — the authoritative one. The
  Workers rate limiter is per-datacenter and approximate, so a distributed
  attempt can slip past it; a `UNIQUE` row in D1 cannot be raced across colos.

  **This depends on D1 read replication staying disabled** (set explicitly in
  `infra/cloudflare/api.tf`). Replicas serve eventually-consistent reads, and a
  stale `last_confirm_sent_at` would let a distributed flood walk straight
  through the cooldown. If replication is ever enabled for latency, the Worker
  must adopt D1 session bookmarks for read-your-writes first.
- A daily global cap on confirmation emails (`MAX_CONFIRM_EMAILS_PER_DAY`).
  If everything above fails, this bounds the damage at a known number rather
  than the whole Resend quota.

Also: an address that is already confirmed triggers **no email at all**.
Sending "you're already subscribed" would hand an attacker a way to pester a
known subscriber forever.

### T2 — Subscriber enumeration

`POST /subscribe` returns a byte-identical `202` for a new address, a pending
one, an already-confirmed one, a previously unsubscribed one, and one dropped
for exceeding a cap. Without that, the endpoint is an oracle for "does this
person read this?".

Malformed-syntax rejections *do* return `400` — address syntax is not a secret,
and a silent failure there is a usability bug.

### T3 — Token theft or guessing

- Tokens are 256 bits from `crypto.getRandomValues`. Guessing is not a threat.
- **Confirm tokens are stored as SHA-256 only**, single-use, 24-hour expiry.
  Redemption is one atomic `UPDATE ... WHERE ... RETURNING`, so it cannot be
  raced into a double redemption.
- **Unsubscribe tokens are not stored at all** — they are `id.HMAC(key, id)`,
  derived on demand with a key held in Worker secrets. This was a design
  correction during the build: storing a hash is impossible (the sender needs
  the raw token to build each link) and storing plaintext would mean a leaked
  dump unsubscribes every reader.
- `Referrer-Policy: no-referrer` and `Cache-Control: no-store` on every
  token-bearing page, so tokens do not leak through `Referer` or shared caches.

**Residual risk:** anyone who can read a subscriber's inbox can unsubscribe
them. That is inherent to emailed unsubscribe links and is an acceptable
outcome (annoyance, not disclosure).

### T4 — Link prefetching silently unsubscribing readers

Mail providers and corporate security appliances routinely fetch every link in
a message. A `GET /unsubscribe` that acted immediately would drop readers who
never clicked.

`GET` renders a confirmation button and changes nothing. The state change is on
`POST`, which is also what RFC 8058 one-click clients send. Both
`List-Unsubscribe` and `List-Unsubscribe-Post` headers ship on every digest.

### T5 — Compromise of the CI pipeline

The worst case in the system: whoever can call `/admin/send-digest` can mail
every subscriber from a domain we own.

- Auth is a **per-run GitHub OIDC token**, not a static secret. It expires in
  minutes and is verified against GitHub's JWKS with `alg` pinned to RS256
  before any key material is touched (blocking `alg=none` and RS256→HS256
  confusion).
- Claims are pinned to `repository` **and** `ref`. Without the `ref` check, a
  pull request from a fork could mint a token for this repository.
- **The Worker renders the email itself.** CI supplies data only; every field
  is escaped and length-bounded, and bill links are restricted to
  `legislature.mi.gov`. So even a valid token cannot inject markup, scripts, or
  off-site links into DKIM-signed mail from our domain.
- Sends are idempotent per date. A replayed request is a no-op.
- Actions are pinned to commit SHAs, not tags — a tag is mutable by whoever
  owns the action's repo, and that code would run with access to this job's
  secrets. `wrangler` is pinned to an exact version for the same reason.
- Workflow permissions are `contents: read` + `id-token: write`.

**Residual risk:** `CLOUDFLARE_API_TOKEN` is long-lived, because Cloudflare has
no OIDC support. Scope it to **Pages:Edit on one account** and nothing else —
then the worst it can do is deface the static site, which the next scheduled
run overwrites. It must not carry Workers, D1, or DNS permissions.

### T6 — XSS on the public site

Bill names and summaries come from a scraped site and an LLM. Both are
untrusted.

- All interpolation goes through `html.escape` (server side) and `textContent`
  (client side); the page never uses `innerHTML`.
- CSS and JS are in separate files so the CSP carries **no `unsafe-inline`**:
  `default-src 'none'`, `script-src 'self' + challenges.cloudflare.com`,
  `form-action 'none'`, `frame-ancestors 'none'` (emitted as `_headers`).
- Worker-rendered pages use a per-response CSP **nonce** for their one inline
  `<style>`, so injected markup cannot execute even there.

### T7 — SQL injection

Every statement in `db.ts` is `prepare()` with bound parameters. There is no
string interpolation into SQL anywhere in the file. Email addresses are
additionally validated against a strict pattern before any query.

### T8 — Secret exposure

| Secret | Lives in | Notes |
| --- | --- | --- |
| `RESEND_API_KEY` | Worker secrets | never in Terraform, never in CI |
| `UNSUBSCRIBE_SIGNING_KEY` | Worker secrets | rotating invalidates all unsubscribe links |
| `TURNSTILE_SECRET_KEY` | Worker secrets | **also in Terraform state** — see below |
| `GOOGLE_API_KEY` | GitHub secrets | scraper only |
| `CLOUDFLARE_API_TOKEN` | GitHub secrets | scope to Pages:Edit only |
| Turnstile **site** key | committed / `vars` | public by design |

`cloudflare_turnstile_widget` exports `secret` as an attribute, so it lands in
Terraform state. The state bucket must therefore be treated as secret material:
private R2 bucket, no public access, no copying state files around. The
alternative — creating the widget by hand and referencing it — trades IaC
completeness for one less secret in state; that is a reasonable call to make
differently, matching how the Gemini key was handled by hand on AWS.

`CLOUDFLARE_API_TOKEN` is read from the environment by the provider and is
deliberately **not** a Terraform variable, so it cannot drift into a `.tfvars`
file and from there into a commit.

### T9 — Extra public origins for the same Worker

Cloudflare enables two things by default that both widen the front door:

- **`workers.dev`** — the `*.workers.dev` hostname. Currently the only route to
  the API, so it stays on. Set `workers_dev = false` once `api.<domain>` is
  live; two public origins serving one API is just more to reason about.
- **Preview URLs** — a public URL per deployed *version*. Disabled
  (`preview_urls = false`) because versions bind to the same D1 UUID and the
  same secrets as production; there is no separate preview database. Left on,
  shipping a security fix would not retire the vulnerable version — it would
  remain publicly reachable and still writing to the live subscriber table.

The OIDC audience check and the CORS origin check both pin to `API_ORIGIN`, so
`/admin/send-digest` and browser calls already fail on any other hostname.
`/subscribe` does not have that protection — Turnstile is its gate — which is
what makes the preview surface worth closing rather than tolerating.

### T10 — Prompt injection through bill text

A bill document could contain text aimed at steering Gemini's summary. The
blast radius is a wrong or silly summary on a page that already says summaries
are AI-generated and may contain errors. Output is escaped, so it cannot become
markup. Accepted.

### T11 — Cost and availability

Every layer is on a free tier with hard caps rather than overage billing.
`MAX_SUBSCRIBERS` and the daily counters bound growth. Resend's free tier is
the practical ceiling on list size; crossing it is a deliberate upgrade, not a
surprise bill.

---

## Known gaps

- **No bounce/complaint handling.** `bounce_count` exists and is respected by
  the sender, but nothing increments it yet. Wire a Resend webhook before the
  list grows past a few hundred, or repeated hard bounces will erode domain
  reputation.
- **No alerting.** `subscriber_cap_reached`, `confirm_email_budget_exhausted`,
  and `digest_budget_exhausted` are logged but nobody is paged.
- **R2 state locking is unverified.** `use_lockfile` relies on conditional
  writes; confirm it actually blocks a concurrent apply before trusting it.
- **Test coverage is partial.** `worker/test/security.test.ts` (`npm test`)
  covers the pure logic: email validation, token generation and verification,
  unsubscribe signature tampering, digest payload validation, and escaping.
  Not covered: the OIDC verifier (needs a JWKS fixture and a signing key), the
  D1 statements, and the rate-limit interactions — all of which need either
  `miniflare` or live bindings.
