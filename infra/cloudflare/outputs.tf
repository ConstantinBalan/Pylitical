output "d1_database_id" {
  description = "Paste into worker/wrangler.jsonc as d1_databases[0].database_id."
  value       = cloudflare_d1_database.subscribers.uuid
}

output "pages_project_name" {
  description = "Target for `wrangler pages deploy --project-name`."
  value       = cloudflare_pages_project.site.name
}

output "site_origin" {
  description = "Set as SITE_ORIGIN in worker/wrangler.jsonc."
  value       = local.has_domain ? "https://${var.domain}" : "https://${cloudflare_pages_project.site.name}.pages.dev"
}

output "api_origin" {
  description = <<-EOT
    Set as API_ORIGIN in worker/wrangler.jsonc and use as the OIDC audience in
    the workflow. Without a custom domain this is the workers.dev URL, which
    Terraform cannot know -- read it from `wrangler deploy` output instead.
  EOT
  value       = local.has_domain ? "https://${local.api_hostname}" : "(no custom domain; use the workers.dev URL from wrangler deploy)"
}

output "turnstile_sitekey" {
  description = "Public key; safe to embed in the page HTML."
  value       = cloudflare_turnstile_widget.subscribe.sitekey
}

# Read with `terraform output -raw turnstile_secret | wrangler secret put TURNSTILE_SECRET_KEY`
# so the value goes straight from state into Worker secrets without a detour
# through the shell history or a file.
output "turnstile_secret" {
  description = "Turnstile secret key. Also present in Terraform state."
  value       = cloudflare_turnstile_widget.subscribe.secret
  sensitive   = true
}

output "data_bucket_name" {
  description = "Set as R2_BUCKET for the pipeline. Needs its own R2 token, scoped to this bucket with Object Read & Write -- not the Terraform state credentials."
  value       = cloudflare_r2_bucket.data.name
}
