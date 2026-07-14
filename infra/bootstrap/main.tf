terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = "us-east-2"

}

resource "aws_s3_bucket" "bootstrap" {
  bucket = "pylitical-tfstate-354594345353"
  tags = {
    Name = "pylitical-tfstate"
  }
}

resource "aws_s3_bucket_versioning" "bootstrap" {
  bucket = aws_s3_bucket.bootstrap.id
  versioning_configuration {
    status = "Enabled"
  }
}

output "state_bucket" {
  value = aws_s3_bucket.bootstrap.bucket
}
