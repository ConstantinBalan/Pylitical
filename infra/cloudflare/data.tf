# Archive store: daily bill data, LegiScan change hashes, cached document text,
# generated summaries, and the API quota ledger.
#
# Separate from the Terraform state bucket on purpose. Different lifecycle,
# different blast radius, and CI needs write access to this one but must never
# get near state.
resource "cloudflare_r2_bucket" "data" {
  account_id = var.account_id
  name       = "${var.project_name}-data"
  # Eastern North America: same region as the readers and the D1 primary.
  # Only honoured at creation time.
  location = "enam"

  lifecycle {
    # Everything here except the archive can be rebuilt from the APIs, but the
    # archive cannot -- past days are gone from "what happened today" feeds.
    # Make Terraform refuse rather than silently recreate.
    prevent_destroy = true
  }
}
