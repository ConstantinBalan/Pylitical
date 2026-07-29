# Deployment runbook

Every step here is one you run by hand. Nothing in this repo creates a
Cloudflare account, a token, or a domain on your behalf.

There is one **circular dependency** worth knowing before you start: Terraform
creates the Turnstile widget whose sitekey the site needs, and the Worker's
`API_ORIGIN` depends on a custom domain that Terraform can only attach *after*
`wrangler deploy` has created the script. The order below breaks that cycle by
deploying twice — once on the `workers.dev` hostname, once on the real one.

---

## Phase 1 — Account and state bucket

1. Create a Cloudflare account (no billing verification required for the free
   tier; this is the wall AWS is stuck behind).

2. Create an R2 bucket named `pylitical-tfstate`. Private, no public access.
   Note the account ID from the dashboard URL.

3. Create an **R2 API token** (S3-compatible credentials) and export them —
   Terraform's S3 backend reads the standard AWS variable names even against
   R2:

   ```bash
   export AWS_ACCESS_KEY_ID=<r2 access key>
   export AWS_SECRET_ACCESS_KEY=<r2 secret>
   ```

4. Create a **Cloudflare API token** for Terraform with only:
   `Account: D1 Edit`, `Account: Pages Edit`, `Account: Turnstile Edit`,
   `Account: Workers Scripts Edit`, `Zone: DNS Edit` (zone scope only once you
   have a domain).

   ```bash
   export CLOUDFLARE_API_TOKEN=<token>
   ```

5. Edit `infra/cloudflare/versions.tf` and replace `REPLACE_ACCOUNT_ID` in the
   R2 endpoint with your account ID.

## Phase 2 — First apply (no custom domain yet)

```bash
cd infra/cloudflare
cp terraform.tfvars.example terraform.tfvars   # fill in account_id; leave zone_id/domain empty
terraform init
terraform plan
terraform apply
```

This creates the D1 database, the Pages project, and the Turnstile widget.

**Predict before you apply:** how many resources should this create, and which
one would destroy data if it were ever replaced? (Answer at the bottom.)

Record the outputs:

```bash
terraform output d1_database_id
terraform output site_origin
terraform output turnstile_sitekey
```

## Phase 3 — Worker

1. Put the D1 id into `worker/wrangler.jsonc` (`database_id`), and set
   `SITE_ORIGIN` to the `site_origin` output.

2. Install and migrate:

   ```bash
   cd worker
   npm install
   npm approve-scripts esbuild workerd   # needed once for local `wrangler dev`
   npm run migrate:remote
   ```

3. Set the three secrets. Piping straight from Terraform keeps the Turnstile
   secret out of your shell history:

   ```bash
   terraform -chdir=../infra/cloudflare output -raw turnstile_secret \
     | npx wrangler secret put TURNSTILE_SECRET_KEY

   openssl rand -base64 32 | npx wrangler secret put UNSUBSCRIBE_SIGNING_KEY

   npx wrangler secret put RESEND_API_KEY   # paste the Resend key when prompted
   ```

   `UNSUBSCRIBE_SIGNING_KEY` is generated once and never rotated casually —
   rotating it invalidates every unsubscribe link already in someone's inbox.

4. Deploy, and note the `workers.dev` URL it prints:

   ```bash
   npm run deploy
   ```

5. Set `API_ORIGIN` in `wrangler.jsonc` to that URL and deploy again. The
   value must match exactly — it is both the CORS origin the browser sees and
   the OIDC audience the Worker checks.

6. Smoke-test:

   ```bash
   curl -s https://<worker>.workers.dev/health
   curl -s -X POST https://<worker>.workers.dev/admin/send-digest \
     -H 'Content-Type: application/json' -d '{}'      # expect 401
   ```

## Phase 4 — GitHub

Repository **secrets**:

| Name | Value |
| --- | --- |
| `GOOGLE_API_KEY` | existing Gemini key |
| `CLOUDFLARE_API_TOKEN` | **a second, separate token — `Pages:Edit` only** |
| `CLOUDFLARE_ACCOUNT_ID` | account ID |

Do **not** reuse the Terraform token here. CI only needs to upload static
files; a token that can also touch Workers, D1, or DNS turns a CI compromise
into a full account compromise.

Repository **variables** (not secrets — all public values):

| Name | Value |
| --- | --- |
| `PYLITICAL_API_ORIGIN` | the Worker origin |
| `PYLITICAL_TURNSTILE_SITEKEY` | `turnstile_sitekey` output |
| `CLOUDFLARE_PAGES_PROJECT` | `pylitical` |

Then run the workflow manually with **skip_email = true** and confirm the site
deploys. Run it again without the flag once email works.

## Phase 5 — Domain and email

Nothing before this point needs a domain. Email does: Resend will only send to
your own verified address until a sending domain is verified.

1. Register a domain (Cloudflare Registrar sells at cost) and let it use
   Cloudflare DNS. Note the zone ID.

2. Add the domain in Resend, copy the DKIM/SPF/MX records it shows into
   `resend_dns_records` in `terraform.tfvars`, and set `zone_id`, `domain`, and
   `turnstile_domains`.

3. `terraform apply`. This adds the Pages custom domain, the API custom domain,
   the Resend records, and DMARC at `p=none`.

   The API custom domain requires the Worker script to already exist — it does,
   from Phase 3.

4. Update `SITE_ORIGIN` and `API_ORIGIN` in `wrangler.jsonc` to the real
   hostnames, `npm run deploy`, and update the two GitHub variables to match.

5. Verify the domain in Resend, then subscribe yourself end to end: signup →
   confirmation email → confirm link → digest → one-click unsubscribe.

6. After a couple of weeks of clean DMARC reports, raise `dmarc_policy` to
   `quarantine`, then `reject`.

---

## Rotating a secret

- **Resend key:** revoke in Resend, `wrangler secret put RESEND_API_KEY`.
- **Cloudflare CI token:** roll in the dashboard, update the GitHub secret.
- **Turnstile:** `terraform taint cloudflare_turnstile_widget.subscribe`,
  apply, then push the new secret *and* the new sitekey (site + GitHub var).
- **Unsubscribe signing key:** only with intent. Every outstanding unsubscribe
  link dies, which is a compliance problem, not just an inconvenience.

## Deliberate omissions

- Terraform does not manage the Worker script. `wrangler` owns it, so
  iterating on code does not mean `terraform apply`, and the CI credential
  stays narrow.
- Terraform does not manage any secret values beyond the Turnstile one it is
  forced to export.

---

*Phase 2 answer: three resources — `cloudflare_d1_database`,
`cloudflare_pages_project`, `cloudflare_turnstile_widget`. The D1 database is
the destructive one; it carries `prevent_destroy` because replacing it drops
every subscriber, the only state here the scraper cannot rebuild.*
