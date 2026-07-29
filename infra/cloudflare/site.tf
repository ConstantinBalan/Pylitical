locals {
  has_domain   = var.zone_id != "" && var.domain != ""
  api_hostname = local.has_domain ? "${var.api_subdomain}.${var.domain}" : ""
}

# Direct-upload project: no `source` block, because deployments come from
# `wrangler pages deploy` in CI rather than a Cloudflare-side git integration.
# That keeps build execution on GitHub's runners, where the build logs and the
# Gemini key are already governed, instead of granting Cloudflare read access
# to the repository.
resource "cloudflare_pages_project" "site" {
  account_id        = var.account_id
  name              = var.project_name
  production_branch = "main"
}

resource "cloudflare_pages_domain" "site" {
  count = local.has_domain ? 1 : 0

  account_id   = var.account_id
  project_name = cloudflare_pages_project.site.name
  name         = var.domain
}

# Pages does not create the DNS record itself. Proxied so the origin is never
# contacted directly and Cloudflare's TLS terminates in front of it.
resource "cloudflare_dns_record" "site_apex" {
  count = local.has_domain ? 1 : 0

  zone_id = var.zone_id
  name    = var.domain
  type    = "CNAME"
  content = "${cloudflare_pages_project.site.name}.pages.dev"
  ttl     = 1 # 1 means "automatic"; required field, ignored when proxied.
  proxied = true
  comment = "Managed by Terraform - Pages site"

  depends_on = [cloudflare_pages_domain.site]
}
