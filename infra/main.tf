terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
    local = {
      source  = "hashicorp/local"
      version = "~> 2.5"
    }
  }
}
resource "local_sensitive_file" "camera_env" {
  filename        = "${path.module}/../edge/.env"
  file_permission = "0600"
  content         = <<-EOT
    S3_BUCKET_NAME=${aws_s3_bucket.sec_camera.bucket}
    AWS_REGION=us-east-1
    AWS_ACCESS_KEY_ID=${aws_iam_access_key.uploader.id}
    AWS_SECRET_ACCESS_KEY=${aws_iam_access_key.uploader.secret}
  EOT
}
provider "aws" {
  region = "us-east-1"
}

variable "alert_email" {
  type = string
}

data "aws_caller_identity" "current" {}

resource "random_id" "suffix" {
  byte_length = 4
}

# ---------- storage ----------

resource "aws_s3_bucket" "sec_camera" {
  bucket        = "sec-camera-${random_id.suffix.hex}"
  force_destroy = true
}
resource "aws_s3_bucket_public_access_block" "sec_camera" {
  bucket                  = aws_s3_bucket.sec_camera.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "expire" {
  bucket = aws_s3_bucket.sec_camera.id
  rule {
    id     = "expire-old-snapshots"
    status = "Enabled"
    filter { prefix = "snapshots/" }
    expiration { days = 30 }
  }
}

# ---------- uploader identity (used by the camera script) ----------

resource "aws_iam_user" "uploader" {
  name = "sec-camera-uploader"
}

resource "aws_iam_user_policy" "uploader_put_only" {
  name = "sec-camera-put-object-only"
  user = aws_iam_user.uploader.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "s3:PutObject"
        Resource = "${aws_s3_bucket.sec_camera.arn}/snapshots/*"
      }
    ]
  })
}

resource "aws_iam_access_key" "uploader" {
  user = aws_iam_user.uploader.name
}

output "bucket_name" {
  value = aws_s3_bucket.sec_camera.bucket
}

output "access_key_id" {
  value = aws_iam_access_key.uploader.id
}

output "secret_access_key" {
  value     = aws_iam_access_key.uploader.secret
  sensitive = true
}

# ---------- alert email with the picture (S3 -> Lambda -> SES) ----------

# SES sends a verification email to this address; it must be clicked once.
# New SES accounts are in "sandbox" mode and can only send to verified addresses,
# which is fine here because sender and recipient are the same address.
resource "aws_ses_email_identity" "alert" {
  email = var.alert_email
}

data "archive_file" "alert_lambda" {
  type        = "zip"
  source_file = "${path.module}/lambda/alert.py"
  output_path = "${path.module}/lambda/alert.zip"
}

resource "aws_iam_role" "alert_lambda" {
  name = "sec-camera-alert-lambda"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "alert_lambda_logs" {
  role       = aws_iam_role.alert_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "alert_lambda" {
  name = "read-snapshots-send-email"
  role = aws_iam_role.alert_lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "${aws_s3_bucket.sec_camera.arn}/snapshots/*"
      },
      {
        # Resource "*" because I was not sure which identity ARNs SES checks in sandbox mode.
        # The role can still only send from addresses verified in this account.
        Effect   = "Allow"
        Action   = "ses:SendRawEmail"
        Resource = "*"
      }
    ]
  })
}

resource "aws_lambda_function" "alert" {
  function_name    = "sec-camera-alert"
  role             = aws_iam_role.alert_lambda.arn
  runtime          = "python3.12"
  handler          = "alert.handler"
  filename         = data.archive_file.alert_lambda.output_path
  source_code_hash = data.archive_file.alert_lambda.output_base64sha256
  timeout          = 15

  environment {
    variables = {
      ALERT_EMAIL = var.alert_email
    }
  }
}

resource "aws_lambda_permission" "allow_s3" {
  statement_id   = "AllowS3Invoke"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.alert.function_name
  principal      = "s3.amazonaws.com"
  source_arn     = aws_s3_bucket.sec_camera.arn
  source_account = data.aws_caller_identity.current.account_id
}

# Only the first snapshot of each motion event (*_0.jpg) triggers an email.
resource "aws_s3_bucket_notification" "snapshots" {
  bucket = aws_s3_bucket.sec_camera.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.alert.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "snapshots/"
    filter_suffix       = "_0.jpg"
  }

  depends_on = [aws_lambda_permission.allow_s3]
}
