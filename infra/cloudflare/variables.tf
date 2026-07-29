variable "account_id" {
  description = "Cloudflare account ID."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{32}$", var.account_id))
    error_message = "account_id must be a 32-character hex string."
  }

  # The placeholder in terraform.tfvars.example is itself 32 hex characters, so
  # the format check above waves it straight through and the failure only shows
  # up as an opaque 401/403 from the API. Name it explicitly.
  validation {
    condition     = var.account_id != join("", ["0123456789", "abcdef", "0123456789", "abcdef"])
    error_message = "account_id is still the example placeholder. Use your real account ID (Cloudflare dashboard, right-hand Account details panel, or the R2 S3 endpoint hostname)."
  }
}

variable "project_name" {
  description = "Base name for the Pages project and D1 database."
  type        = string
  default     = "pylitical"
}

variable "zone_id" {
  description = <<-EOT
    Cloudflare zone ID for the custom domain. Leave empty to deploy without a
    custom domain -- the site is then served from <project>.pages.dev and the
    API from the workers.dev subdomain, and no DNS records are managed here.
    Email requires a real domain, so this is empty only before you register one.
  EOT
  type        = string
  default     = ""
}

variable "domain" {
  description = "Apex domain (e.g. pylitical.dev). Empty when zone_id is empty."
  type        = string
  default     = ""

  validation {
    condition     = var.domain == "" || can(regex("^[a-z0-9.-]+\\.[a-z]{2,}$", var.domain))
    error_message = "domain must be a bare hostname such as pylitical.dev (no scheme, no trailing dot)."
  }
}

variable "api_subdomain" {
  description = "Hostname label for the Worker API."
  type        = string
  default     = "api"
}

variable "turnstile_domains" {
  description = <<-EOT
    Hostnames allowed to solve the Turnstile widget. Keep this tight: a widget
    that accepts any domain can be embedded on an attacker's page and farmed
    for valid tokens.
  EOT
  type        = list(string)
  default     = []
}

variable "resend_dns_records" {
  description = <<-EOT
    Domain-verification records copied from the Resend dashboard (DKIM CNAMEs,
    the SPF TXT, and the MX record for the sending subdomain). Left as data
    rather than hardcoded because Resend generates per-domain values.
  EOT
  type = list(object({
    name     = string
    type     = string
    content  = string
    priority = optional(number)
  }))
  default = []
}

variable "dmarc_policy" {
  description = <<-EOT
    DMARC policy. Start at "none" to collect reports without risking delivery,
    then tighten to "quarantine" and finally "reject" once the aggregate
    reports show only Resend signing your mail. Shipping straight to "reject"
    on a fresh domain risks silently losing every confirmation email.
  EOT
  type        = string
  default     = "none"

  validation {
    condition     = contains(["none", "quarantine", "reject"], var.dmarc_policy)
    error_message = "dmarc_policy must be one of: none, quarantine, reject."
  }
}

variable "dmarc_report_email" {
  description = "Mailbox for DMARC aggregate reports. Empty omits the rua tag."
  type        = string
  default     = ""
}
