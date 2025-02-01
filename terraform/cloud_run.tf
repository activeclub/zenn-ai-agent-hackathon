resource "google_cloud_run_v2_service" "web" {
  name     = "web"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.web.name}/wondy-web"

      env {
        name  = "DATABASE_URL"
        value = "postgresql://${google_sql_user.users.name}:${urlencode(random_password.db.result)}@localhost/${google_sql_database.database.name}?host=/cloudsql/${google_sql_database_instance.instance.connection_name}"
      }
    }
    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.instance.connection_name]
      }
    }
    service_account = google_service_account.cloudrun.email
  }
}

resource "google_service_account" "cloudrun" {
  account_id   = "cloudrun-sa"
  display_name = "Cloud Run Service Account"
}

resource "google_cloud_run_v2_service_iam_member" "allow_unauthenticated" {
  project  = google_cloud_run_v2_service.web.project
  location = google_cloud_run_v2_service.web.location
  name     = google_cloud_run_v2_service.web.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_artifact_registry_repository" "web" {
  location      = var.region
  repository_id = "${var.app_name}-web"
  format        = "DOCKER"
}

resource "google_artifact_registry_repository_iam_binding" "github_actions" {
  repository = google_artifact_registry_repository.web.name
  role       = "roles/artifactregistry.writer"
  members = [
    "serviceAccount:${google_service_account.github_actions.email}"
  ]
}
