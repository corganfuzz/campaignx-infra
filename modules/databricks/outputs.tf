output "sql_warehouse_id" {
  value = databricks_sql_endpoint.this.id
}


output "catalog_name" {
  value = databricks_catalog.mortgage.name
}

output "external_locations" {
  value = [for l in databricks_external_location.buckets : l.name]
}

output "model_serving_url" {
  value = "https://serving.databricks.com/endpoints/${databricks_model_serving.mortgage_expert.name}/invocations"
}
