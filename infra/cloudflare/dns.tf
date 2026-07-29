# Email authentication.
#
# These three mechanisms are what stop somebody spoofing mail as your domain,
# and what stop the digest landing in spam:
#   SPF   - which servers may send for the domain
#   DKIM  - cryptographic signature over the message (Resend's keys)
#   DMARC - what receivers should do when SPF and DKIM disagree, plus reporting
#
# The SPF and DKIM values are generated per-domain by Resend, so they arrive
# through var.resend_dns_records rather than being hardcoded.

resource "cloudflare_dns_record" "resend" {
  for_each = local.has_domain ? {
    for record in var.resend_dns_records :
    "${record.type}:${record.name}" => record
  } : {}

  zone_id  = var.zone_id
  name     = each.value.name
  type     = each.value.type
  content  = each.value.content
  priority = each.value.priority
  ttl      = 3600
  # Never proxy mail-authentication records: proxying rewrites the answer and
  # breaks verification.
  proxied = false
  comment = "Managed by Terraform - Resend email authentication"
}

resource "cloudflare_dns_record" "dmarc" {
  count = local.has_domain ? 1 : 0

  zone_id = var.zone_id
  name    = "_dmarc.${var.domain}"
  type    = "TXT"
  ttl     = 3600
  proxied = false
  comment = "Managed by Terraform - DMARC policy"

  content = join("; ", compact([
    "v=DMARC1",
    "p=${var.dmarc_policy}",
    var.dmarc_report_email != "" ? "rua=mailto:${var.dmarc_report_email}" : "",
    "fo=1",
  ]))
}
