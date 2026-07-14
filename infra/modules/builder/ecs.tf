resource "aws_ecs_cluster" "builder" {
  name = "pylitical"
}

data "aws_region" "current" {}

resource "aws_ecs_task_definition" "builder" {
  family                   = "pylitical"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  container_definitions = jsonencode([{
    name      = "pylitical"
    image     = "${aws_ecr_repository.builder.repository_url}:latest"
    essential = true

    environment = [{
      name  = "OUTPUT_BUCKET",
      value = var.output_bucket

    }]

    secrets = [{
      name      = "GOOGLE_API_KEY",
      valueFrom = data.aws_ssm_parameter.gemini_key.arn
    }]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.builder.name
        "awslogs-region"        = data.aws_region.current.region
        "awslogs-stream-prefix" = "builder"
      }
    }
    }
  ])
}

resource "aws_scheduler_schedule" "daily" {
  name                         = "pylitical-daily"
  schedule_expression          = "cron(30 22 * * ? *)"
  schedule_expression_timezone = "America/Detroit"
  flexible_time_window {
    mode = "OFF"
  }
  target {
    arn      = aws_ecs_cluster.builder.arn
    role_arn = aws_iam_role.scheduler.arn
    ecs_parameters {
      task_definition_arn = aws_ecs_task_definition.builder.arn
      launch_type         = "FARGATE"
      network_configuration {
        subnets          = var.subnet_ids
        assign_public_ip = true

      }
    }
  }
}
