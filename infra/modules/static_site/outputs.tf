output "bucket_name" {
  value = aws_s3_bucket.site.bucket
}

output "cloudfront_url" {
  value = aws_cloudfront_distribution.site.domain_name
}
