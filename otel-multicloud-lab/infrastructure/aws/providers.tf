provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "otel-multicloud-lab"
      Environment = "university-lab"
    }
  }
}
