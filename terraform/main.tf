terraform {
  backend "remote" {
    hostname     = "app.terraform.io"
    organization = "nszknao"

    workspaces {
      name = "wondy"
    }
  }

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "6.18.1"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

data "google_project" "current" {}