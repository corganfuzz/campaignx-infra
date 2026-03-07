resource "databricks_model_serving" "mortgage_expert" {
  name = "${var.project_name}-${var.environment}-expert"

  config {
    served_entities {
      entity_name           = "databricks-meta-llama-3-1-8b-instruct"
      entity_version        = "1"
      workload_type         = "CPU"
      workload_size         = "Small"
      scale_to_zero_enabled = true
    }
  }
}
