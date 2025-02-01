variable "project_id" {
  description = "This is the name of the project where your webapp will be deployed."
}

variable "region" {
  description = "This is the cloud hosting region where your webapp will be deployed."
}

variable "app_name" {
  description = "This is the name of the app that will be deployed."
}

variable "authorized_ip" {
  description = "This is the IP address that will be allowed to connect to the database."
}
