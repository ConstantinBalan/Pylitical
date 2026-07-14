resource "aws_ecr_repository" "builder" {
  name                 = "pylitical"
  image_tag_mutability = "MUTABLE"
}

resource "aws_cloudwatch_log_group" "builder" {
  name              = "/ecs/pylitical"
  retention_in_days = 30
}
