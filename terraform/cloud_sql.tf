resource "google_sql_database" "database" {
  name     = "${var.app_name}-db"
  instance = google_sql_database_instance.instance.name
}

resource "google_sql_database_instance" "instance" {
  name             = "${var.app_name}-db-instance"
  region           = var.region
  database_version = "POSTGRES_16"

  settings {
    edition = "ENTERPRISE"
    # ref: https://cloud.google.com/sql/docs/mysql/instance-settings?hl=ja
    tier = "db-custom-4-15360"

    ip_configuration {
      ipv4_enabled    = true
      private_network = null

      authorized_networks {
        value = var.authorized_ip
      }
    }
  }
}

resource "google_sql_user" "users" {
  name     = var.app_name
  instance = google_sql_database_instance.instance.name
  password = random_password.db.result
}

resource "random_password" "db" {
  length  = 16
  special = true
}

resource "google_project_iam_member" "db_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.cloudrun.email}"
}
