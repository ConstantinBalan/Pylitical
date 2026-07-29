# Pylitical DevOps Build-out — Progress Tracker

Full plan: `michigan-bills-devops-plan.md` (reconciled) and `~/.claude/plans/ethereal-tumbling-patterson.md`.
Working style: Constantin drives the new-skill parts (Docker/Terraform/IAM/CI) with Claude as senior reviewer;
Claude types Python; Constantin runs all AWS/console actions and writes all commits.

## Done

### Phase 0 — Git & repo hygiene
- Rescued detached HEAD onto branch `pyl-5-structure-refactoring`
- .gitignore covers Python, macOS, output, `.env`, Terraform (`.terraform/`, `*.tfstate*`)
- Deleted tkinter `user_interface.py`

### Phase 1 — Package refactor (new_work.md)
- `pylitical/` package: `bill.py` (keyword-only-arg record), `scraper.py` (`BillScraper.find()` →
  `list[Bill]`, Pool fan-out over 4 status sections), `summarizer.py` (**google-genai SDK**,
  `gemini-2.5-flash`), `renderer.py` (`bills.json` + `index.html`, html-escaped), thin argparse
  `__main__.py` with `--skip-summaries`
- Fixed legacy bugs: datetime-in-URL interpolation, inverted date validation, unbound
  `table_element`, library `sys.exit()` calls
- Frozen real deps in `requirements.txt`; `requirements-dev.txt` (black, pylint); Makefile
  (bootstrap/run/lint/fmt — tabs fixed); README rewritten; pylint CI installs from requirements
- Lint policy: lean style — missing-docstring checks disabled in `.pylintrc`; pylint 10/10
- Resilience (added after live failures): scraper retries ×3 with backoff, 30s timeout, per-page
  and per-section fail-soft, `requests.Session` per worker, custom User-Agent, 1s page pacing;
  summarizer raises `SummarizerError`, `__main__` renders partial results on API failure
- Gemini: Constantin enabled paid billing (free tier = 20 req/day was insufficient);
  `SUMMARY_DELAY_SECONDS` lowered to 2

### Phase 2 — Containerization
- `Dockerfile` (Constantin wrote it): `python:3.12-slim`, requirements-first layer ordering,
  exec-form `ENTRYPOINT ["python", "__main__.py"]`
- `.dockerignore`: venv, pycache, output, `.env`, `.git`, docs
- Verified: build + `docker run --env-file .env -v "$PWD/output:/app/output" pylitical --skip-summaries`
  works; cache reuse confirmed on rebuild
- `pylitical/publisher.py`: uploads output to S3 when `OUTPUT_BUCKET` env var is set, with explicit
  ContentType (S3 doesn't sniff); no credential code — boto3 chain / IAM role
- VERIFIED 2026-07-13: rebuilt image, ran container with OUTPUT_BUCKET + short-lived creds in .env
  (`aws configure export-credentials`); both files in site bucket with correct ContentTypes.
  Scraper retry/fail-soft observed working live (RemoteDisconnected → retry → success).

## Pending on Constantin
- [x] Commit Phase 2 work — done in 94d1172
- [x] Phase 3 prereqs (2026-07-09): Terraform 1.15.8 via hashicorp/tap (core formula frozen at
      1.5.7 post-BSL), AWS CLI 2.35; account 354594345353, IAM user `constantin` (AdministratorAccess),
      CLI auth via `aws login` short-lived creds; `aws sts get-caller-identity` verified
- [ ] Billing budget/alert — confirm set before first apply
- [ ] Add `prevent_destroy` lifecycle to state bucket (config-only, no apply diff)

## Phase 3 — Terraform (Constantin-driven, in progress)
Planned layout:
```
infra/
  bootstrap/        # DONE (applied 2026-07-10): S3 state bucket pylitical-tfstate-354594345353,
                    # versioning on, local state. No DynamoDB — TF >=1.10 native S3 locking
                    # (`use_lockfile = true` in envs/prod backend block) replaces it.
  modules/builder/     # COMPLETE in code (applied through 2026-07-14): ECR (image pushed),
                       # log group (30d), 3 IAM roles (execution: managed policy + SSM read;
                       # task: S3 put; scheduler: RunTask + PassRole), cluster, Fargate task
                       # def (256/512, GOOGLE_API_KEY via SSM valueFrom, OUTPUT_BUCKET env,
                       # awslogs), EventBridge Scheduler daily 22:30 America/Detroit.
                       # Decision: no session-calendar gating — empty days cost ~nothing
                       # (Gemini is per-bill); run late evening instead.
  modules/static_site/ # private S3 + CloudFront with OAC, default cert
                       # S3 half DONE (applied 2026-07-13): bucket pylitical-site-354594345353
                       # + public access block; outputs bucket_name.
                       # CloudFront WRITTEN but BLOCKED: new-account verification required —
                       # AWS support ticket submitted 2026-07-13; account ALSO blocked from
                       # running Fargate tasks (same verification), ticket updated 2026-07-14.
                       # When AWS confirms: `terraform apply`, then manual `aws ecs run-task`
                       # end-to-end test (watch `aws logs tail /ecs/pylitical --follow`),
                       # then open cloudfront_url output in browser.
  envs/prod/           # DONE as shell: s3 backend key prod/terraform.tfstate (use_lockfile),
                       # provider w/ default_tags, instantiates static_site
```
Detour learned: initial backend key was mistakenly `bootstrap/...` — fixed via
`init -reconfigure` + deleted stray S3 object. Registry module (terraform-aws-modules/s3-bucket)
rejected in favor of hand-written resources for learning.
- Gemini key → SSM SecureString: DONE 2026-07-13, `/pylitical/gemini-api-key` created by hand
  (Version 1, Standard tier); referenced as TF data source; injected into task def via
  `valueFrom` (no SSM code in Python)
- Networking: default VPC, public subnets, `assign_public_ip = true` (no NAT — documented trade-off)
- Open with: Terraform mental model (state, plan/apply, providers), then bootstrap module first

## Then: Phase 4 — GitHub Actions (plan-on-PR/apply-on-merge + tflint/tfsec; image build-push to
ECR; auth via GitHub OIDC → IAM role, no long-lived keys). Phase 5 — README architecture/cost docs.

---

# PIVOT (2026-07-28): Cloudflare instead of AWS

AWS never answered the account-verification ticket, so both CloudFront and Fargate stayed
blocked. Rather than keep waiting, the deployment target moved to Cloudflare. **The AWS
`infra/` tree is left intact** — it is finished work and the ticket may still resolve.

Decision record: Firebase/GCP was the other candidate and maps 1:1 onto the existing
container (Cloud Run Jobs ≈ Fargate), but the Gemini key came from AI Studio without a
linked billing account, so GCP risked the same verification wall. Cloudflare's free tier
needs no verification. Cost of that choice: Cloudflare cannot run the Docker image on the
free tier, so the daily job moved to a GitHub Actions cron.

**Working style for this phase reversed by request:** Claude wrote the Cloudflare
infrastructure and Worker; Constantin reviews. Security explicitly prioritised.

## Architecture

```
GitHub Actions (cron 02:30 UTC ≈ 22:30 America/Detroit)
  └─ python __main__.py  → output/ (site) + digest.json (payload)
       ├─ wrangler pages deploy → Cloudflare Pages
       └─ POST /admin/send-digest (GitHub OIDC) → Worker → Resend
                                                    ↕
                                                D1 (subscribers)
```

## Built (all typechecked / linted / tested; none of it deployed yet)

- `worker/` — TypeScript Worker: `POST /subscribe`, `GET /confirm`,
  `GET|POST /unsubscribe`, `POST /admin/send-digest`, `GET /health`.
  `npm test` → 15 passing. `tsc --noEmit` clean.
- `worker/migrations/0001_init.sql` — subscribers, sent_digests, daily_counters.
- `infra/cloudflare/` — D1, Pages project, Turnstile widget, optional custom domains and
  Resend/DMARC DNS. `terraform validate` passes. R2-backed state.
- `.github/workflows/daily-digest.yml` — cron + manual, actions pinned to SHAs.
- Python: `pylitical/assets.py` (external CSS/JS + `_headers`), `pylitical/digest.py`,
  reworked `renderer.py`, new `__main__.py` flags. pylint 10/10.
- `docs/THREAT_MODEL.md`, `docs/DEPLOY_RUNBOOK.md`.

## Security decisions worth reviewing

1. **`/admin/send-digest` uses GitHub OIDC, not a shared secret** — per-run token, `alg`
   pinned to RS256, claims pinned to repository *and* `ref`.
2. **The Worker renders the email; CI supplies data only.** Bill links are restricted to
   `legislature.mi.gov`, so a compromised pipeline cannot phish from our domain.
3. **Unsubscribe tokens are derived (`id.HMAC(key, id)`), not stored.** Corrected
   mid-build: a stored hash cannot be reversed to build the link, and stored plaintext
   would mean a D1 dump unsubscribes everyone.
4. **GET /unsubscribe changes nothing** — POST does. Mail scanners prefetch links.
5. **Five overlapping anti-mail-bomb layers**, because the Workers rate limiter is
   per-colo and approximate; the D1 cooldown is the authoritative one.
6. `CLOUDFLARE_API_TOKEN` in CI must be scoped **Pages:Edit only**, separate from the
   Terraform token.

## VERIFIED LIVE 2026-07-28

Runbook phases 1–3 done. Account `ddb9358a81e53dd4a30ac4e789367f12`.

- D1 `pylitical` (c45af3f8-8490-4165-8a04-df026f8e3145), Pages project, Turnstile widget
  all applied. R2 state backend works.
- Worker live at `https://pylitical-api.constantinbalan96.workers.dev`; `workers_dev=true`,
  `preview_urls=false` (previews bind to prod D1 — see T9).
- Site live at `https://pylitical.pages.dev`; `_headers` applied, full CSP with no
  `unsafe-inline` confirmed over the wire.
- **Signup proven end to end**: Turnstile → D1 pending → Resend confirmation →
  confirm link → `status='confirmed'`. Negative paths correct (forged unsubscribe HMAC
  410, unknown confirm token 410, unknown route 404, `/admin/send-digest` 401 without
  OIDC, `/subscribe` 403 without Turnstile).
- `MAIL_FROM` is `onboarding@resend.dev` — pre-domain this only delivers to the Resend
  account address.

Fixes made while bringing it up: `boto3` import made lazy (the AWS SDK was a hard
requirement for a Cloudflare-only render); stale `OUTPUT_BUCKET` retired from `.env`
(it made runs call the dead S3 path, and `AWS_ACCESS_KEY_ID` is overloaded between R2
and AWS); `account_id` placeholder guard added to the Terraform variable.

## ⚠ BLOCKER FOUND 2026-07-28: legislature.mi.gov is behind bot protection

The data source now serves a **Radware Bot Manager** interstitial (`BNIS_x-bni-jas` /
`x-bni-ci` cookies, `<title>Validation request</title>`, image CAPTCHA at
`/captcha_resp`, "error code 426", blocked by client IP). Even `robots.txt` returns it.

**It returns HTTP 200.** So `_get()` succeeded, BeautifulSoup parsed the ~1KB challenge
page, found no `h3` sections, and the run reported "0 bills" — indistinguishable from a
genuine quiet day. Left alone, the daily job would have published an empty site and sent
no digest every morning, silently, with nothing in the logs.

Mitigation shipped: `BotChallengeError` (subclass of `ScraperError`) raised from `_get()`
on detecting the interstitial. Deliberately **fatal, not fail-soft**, and deliberately
**not retried** — the block is per-IP, so retrying neither helps nor is decent behaviour
toward a public site. Verified: run exits 1, nothing rendered, site not clobbered.

Working around the CAPTCHA is not on the table. Legitimate options, best first:

1. **Open States API v3** (`docs.openstates.org/api-v3`) — free with an API key from
   `open.pluralpolicy.com`, covers all 50 states including Michigan, purpose-built for
   this. Would replace `scraper.py` with an API client and remove the scraping
   fragility (and the retry/pacing/User-Agent machinery) entirely.
2. Ask the Michigan Legislature web team to allowlist a clearly-identified civic
   project, or point at official bulk data.
3. Open States **bulk data** downloads, if the API's freshness is not enough.

Recommendation: option 1. It is a smaller, more reliable codebase than the scraper, and
it ends this class of failure permanently.

## Adding a state later (deferred by choice, 2026-07-29)

Michigan only for now. The code is multi-state throughout — `pylitical/states.py`
holds the roster, and `--states mi,oh` already works — but **three things must be
done before a second state goes live**, or subscribers get mail they did not ask for:

1. **D1 + Worker per-state subscriptions.** The signup form already sends
   `states: ["mi"]`, and the Worker ignores it. Needs a `states` column on
   `subscribers`, validation in `/subscribe`, and per-state filtering in the
   digest fan-out. Harmless with one state; wrong the moment there are two.
2. **Group the digest email by state.** `digest.json` is currently one flat list
   and the Worker renders it ungrouped, so a Michigan reader would receive Ohio
   bills in an unlabelled block. This is the fastest route to a spam complaint,
   which is the single worst outcome for a small sending domain.
3. **Check the Open States daily quota.** The default tier is 500 requests/day
   and each state costs roughly one request per 20 bills. Michigan alone uses 3.
   Ten states would still fit, but a backfill across them would not — the daily
   ceiling in `usage.py` will stop it, loudly.

Also worth knowing per state before enabling it: whether it publishes abstracts
to Open States (`probe_openstates.py <State>`). Ohio, Indiana, Illinois, New
York, California and Florida do; Michigan, Wisconsin, Minnesota and Texas do
not, and depend entirely on LegiScan text. Candidates are listed in
`states.py` under `CANDIDATES`, already coded, just not in `SUPPORTED`.

## Not yet exercised

- The digest send path (needs GitHub OIDC — nothing has called `/admin/send-digest`)
- A real unsubscribe (the link only ships in a digest)
- Gemini summaries in a deployed build (first runs used `--skip-summaries`)

## Pending on Constantin

- [ ] Review the above, especially the OIDC verifier and the Terraform token scoping
- [ ] Get the work onto `main` — local branch is `master`, default is `main`;
      `workflow_dispatch`, scheduled runs, and the OIDC `ref` claim all require `main`
- [ ] Register a domain — **email cannot ship without one** (Resend needs a verified
      sending domain; the site does not)
- [ ] Decide whether to split boto3 out of `requirements.txt` into `requirements-aws.txt`
- [ ] Work `docs/DEPLOY_RUNBOOK.md` phase 4, then 5 once the domain exists
- [ ] Decide: Turnstile widget in Terraform (its secret lands in state) vs created by
      hand like the Gemini SSM parameter was
- [ ] Verify R2 state locking actually blocks a concurrent apply
- [ ] Wire a Resend bounce webhook before the list grows past a few hundred
