data "aws_ssm_parameter" "gemini_key" {
  name = var.ssm_param_name
}

data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "execution_ssm" {
  statement {
    actions   = ["ssm:GetParameters"]
    resources = [data.aws_ssm_parameter.gemini_key.arn]
  }
}

data "aws_iam_policy_document" "task_s3" {
  statement {
    actions   = ["s3:PutObject"]
    resources = ["arn:aws:s3:::${var.output_bucket}/*"]
  }
}

data "aws_iam_policy_document" "scheduler_run" {
  statement {
    actions   = ["ecs:RunTask"]
    resources = [aws_ecs_task_definition.builder.arn]
  }
  statement {
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.execution.arn, aws_iam_role.task.arn]
  }
}

resource "aws_iam_role" "execution" {
  name               = "pylitical-execution-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role" "task" {
  name               = "pylitical-task-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role" "scheduler" {
  name               = "pylitical-scheduler-role"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}


resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "execution_ssm" {
  name   = "read-gemini-key"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution_ssm.json
}

resource "aws_iam_role_policy" "task_s3" {
  name   = "put-site-output"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task_s3.json
}

resource "aws_iam_role_policy" "scheduler_run" {
  name   = "run-pylitical-task"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler_run.json
}
