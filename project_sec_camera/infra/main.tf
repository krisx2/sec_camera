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
  }
}

provider "aws" {
  region = "us-east-1"
}

# Random suffix so the bucket name is globally unique (S3 names are unique
# across ALL of AWS, not just your account)
resource "random_id" "suffix" {
  byte_length = 4
}

resource "aws_s3_bucket" "sec_camera" {
  bucket = "sec-camera-${random_id.suffix.hex}"
}

resource "aws_s3_bucket_public_access_block" "sec_camera" {
  bucket                  = aws_s3_bucket.sec_camera.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

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