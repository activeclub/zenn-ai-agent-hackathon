###############################################################################
# Github Actions OIDC service account
###############################################################################
resource "google_service_account" "github_actions" {
  account_id   = "github-actions-oidc"
  display_name = "Github Actions"
  description  = "Service account for Github Actions"
}

resource "google_service_account_iam_member" "github_actions" {
  service_account_id = google_service_account.github_actions.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github_actions.name}/attribute.repository/activeclub/zenn-ai-agent-hackathon"
}

resource "google_iam_workload_identity_pool" "github_actions" {
  workload_identity_pool_id = "github-actions-oidc"
  display_name              = "GitHub Actions OIDC Pool"
  description               = "Pool for GitHub Actions OIDC"
}

resource "google_iam_workload_identity_pool_provider" "github_actions" {
  workload_identity_pool_provider_id = "github-oidc-provider"
  workload_identity_pool_id          = google_iam_workload_identity_pool.github_actions.workload_identity_pool_id
  display_name                       = "GitHub OIDC Provider"
  attribute_condition                = "assertion.repository_owner==\"activeclub\""

  attribute_mapping = {
    "google.subject"             = "assertion.sub"
    "attribute.actor"            = "assertion.actor"
    "attribute.repository"       = "assertion.repository"
    "attribute.repository_owner" = "assertion.repository_owner"
  }


  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}
