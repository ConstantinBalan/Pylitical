terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
  backend "s3" {
    bucket       = "pylitical-tfstate-354594345353"
    key          = "prod/terraform.tfstate"
    region       = "us-east-2"
    use_lockfile = true
  }
}

provider "aws" {
  region = "us-east-2"
  default_tags {
    tags = {
      Project     = "pylitical"
      Environment = "prod"
    }
  }
}

module "static_site" {
  source = "../../modules/static_site"
}

module "builder" {
  source        = "../../modules/builder"
  output_bucket = module.static_site.bucket_name
  subnet_ids    = ["subnet-0218f35ff11dccccf", "subnet-0eb2456ad31cedab8", "subnet-0be5d18051aecbb29"]
}

output "cloudfront_url" {
  value = module.static_site.cloudfront_url
}

