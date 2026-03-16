terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "us-central1"
}

variable "gemini_api_key" {
  description = "Gemini API key"
  type        = string
  sensitive   = true
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# ─── Enable Required APIs ───────────────────────────────

resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",
    "cloudbuild.googleapis.com",
    "secretmanager.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudscheduler.googleapis.com",
  ])
  service            = each.value
  disable_on_destroy = false
}

# ─── Secrets ────────────────────────────────────────────

resource "google_secret_manager_secret" "gemini_key" {
  secret_id = "gaxis-gemini-key"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "gemini_key_version" {
  secret      = google_secret_manager_secret.gemini_key.id
  secret_data = var.gemini_api_key
}

# ─── Cloud Run Service ──────────────────────────────────

resource "google_cloud_run_v2_service" "gaxis" {
  name     = "gaxis"
  location = var.region

  template {
    containers {
      image = "gcr.io/${var.project_id}/gaxis:latest"

      resources {
        limits = {
          cpu    = "2"
          memory = "2Gi"
        }
      }

      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "HEADLESS"
        value = "true"
      }
      env {
        name = "GOOGLE_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.gemini_key.id
            version = "latest"
          }
        }
      }

      ports {
        container_port = 8080
      }

      # Mount analytics volume for session persistence
      volume_mounts {
        name       = "analytics-data"
        mount_path = "/app/.analytics"
      }
    }

    volumes {
      name = "analytics-data"
      empty_dir {}
    }

    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }

    timeout = "300s"
  }

  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret_version.gemini_key_version,
  ]
}

# ─── Public Access ──────────────────────────────────────

resource "google_cloud_run_v2_service_iam_member" "public" {
  name     = google_cloud_run_v2_service.gaxis.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ─── Scheduled Jobs (Analytics) ─────────────────────────

# Daily analysis job — runs at midnight UTC
resource "google_cloud_scheduler_job" "daily_analysis" {
  name      = "gaxis-daily-analysis"
  schedule  = "0 0 * * *"
  time_zone = "UTC"

  http_target {
    uri         = "${google_cloud_run_v2_service.gaxis.uri}/api/run-daily-analysis"
    http_method = "POST"

    oidc_token {
      service_account_email = google_cloud_run_v2_service.gaxis.template[0].service_account
    }
  }

  depends_on = [google_project_service.apis]
}

# Weekly report job — runs Sunday 11 PM UTC
resource "google_cloud_scheduler_job" "weekly_report" {
  name      = "gaxis-weekly-report"
  schedule  = "0 23 * * 0"
  time_zone = "UTC"

  http_target {
    uri         = "${google_cloud_run_v2_service.gaxis.uri}/api/run-weekly-report"
    http_method = "POST"

    oidc_token {
      service_account_email = google_cloud_run_v2_service.gaxis.template[0].service_account
    }
  }

  depends_on = [google_project_service.apis]
}

# ─── Outputs ────────────────────────────────────────────

output "service_url" {
  value       = google_cloud_run_v2_service.gaxis.uri
  description = "G-Axis backend URL"
}

output "health_url" {
  value       = "${google_cloud_run_v2_service.gaxis.uri}/health"
  description = "Health check endpoint"
}
