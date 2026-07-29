resource "cloudflare_d1_database" "subscribers" {
  account_id = var.account_id
  name       = var.project_name

  # Readers and the legislature are both in the eastern US; keeping the primary
  # there avoids a transatlantic hop on every subscribe request.
  primary_location_hint = "enam"

  # Disabled deliberately, not merely to satisfy the provider (which rejects a
  # null here). Read replicas serve eventually-consistent reads, and this
  # database's anti-abuse controls depend on reads being authoritative:
  # the 15-minute per-address confirmation cooldown is the one defence against
  # mail-bombing that works across datacenters, and it is only as good as the
  # freshness of `last_confirm_sent_at`. A stale replica read would let a
  # distributed signup flood slip past it. The subscriber list is small and
  # read rarely, so replication buys nothing to offset that.
  read_replication = {
    mode = "disabled"
  }

  lifecycle {
    # Replacing a D1 database destroys every row. The subscriber list is the
    # one piece of state here that cannot be rebuilt by re-running the scraper,
    # so make Terraform refuse rather than silently recreate it.
    prevent_destroy = true
  }
}

# "managed" lets Cloudflare decide between an invisible check and an
# interactive challenge based on signal quality -- the right default for a
# public signup form, where the alternative is either annoying every human or
# waving through obvious bots.
resource "cloudflare_turnstile_widget" "subscribe" {
  account_id = var.account_id
  name       = "${var.project_name} subscribe form"
  mode       = "managed"
  region     = "world"

  # Falls back to the pages.dev hostname before a custom domain exists. An
  # empty list would mean "any domain", which is exactly the misconfiguration
  # that lets someone farm valid tokens from their own page.
  domains = length(var.turnstile_domains) > 0 ? var.turnstile_domains : compact([
    "${cloudflare_pages_project.site.name}.pages.dev",
    var.domain,
  ])
}

# Binds api.<domain> to the Worker and provisions its certificate.
#
# ORDERING: this resource requires the Worker script to already exist, and the
# script is deployed by wrangler, not Terraform. Run `npm run deploy` in
# worker/ before the first apply that includes this. Terraform deliberately
# does not own the script -- iterating on Worker code through `terraform apply`
# is far worse than `wrangler deploy`, and splitting them keeps the deploy
# credential in CI scoped to Workers rather than to the whole account.
resource "cloudflare_workers_custom_domain" "api" {
  count = local.has_domain ? 1 : 0

  account_id = var.account_id
  hostname   = local.api_hostname
  service    = "${var.project_name}-api"
  zone_id    = var.zone_id
}
