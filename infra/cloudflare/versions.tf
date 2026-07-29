terraform {
  required_version = ">= 1.10"

  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.19"
    }
  }

  # State lives in R2 (S3-compatible), so nothing here depends on the AWS
  # account that is still stuck in verification. The `skip_*` flags are needed
  # because R2 is not real S3: there is no STS, no regions, and no
  # account-id lookup.
  #
  # `use_lockfile` uses conditional writes (If-None-Match) rather than
  # DynamoDB. R2 supports those, but verify locking actually engages before
  # trusting it from CI -- run a `terraform plan` in one shell while another
  # holds `terraform apply` and confirm the second blocks.
  #
  # NOTE: this state contains the Turnstile secret key (see turnstile.tf).
  # Treat the bucket as secret material: private, no public access, and do not
  # copy state files around.
  backend "s3" {
    bucket = "pylitical-tfstate"
    key    = "cloudflare/terraform.tfstate"
    region = "auto"

    endpoints = {
      s3 = "https://ddb9358a81e53dd4a30ac4e789367f12.r2.cloudflarestorage.com"
    }

    use_lockfile                = true
    skip_credentials_validation = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    skip_metadata_api_check     = true
    skip_s3_checksum            = true
    use_path_style              = true
  }
}

# The provider reads CLOUDFLARE_API_TOKEN from the environment on purpose.
# Declaring it as a Terraform variable would invite it into a .tfvars file and
# from there into shell history, editor backups, and eventually a commit.
provider "cloudflare" {}
