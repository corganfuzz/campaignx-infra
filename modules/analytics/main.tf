resource "aws_glue_catalog_database" "main" {
  name = "${var.project_name}_${var.environment}_analytics"
}

resource "aws_glue_catalog_table" "events" {
  name          = "campaign_events"
  database_name = aws_glue_catalog_database.main.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    EXTERNAL                    = "TRUE"
    "parquet.compression"       = "SNAPPY"
    "projection.enabled"        = "true"
    "projection.year.type"      = "integer"
    "projection.year.range"     = "2025,2035"
    "projection.month.type"     = "integer"
    "projection.month.range"    = "1,12"
    "projection.month.digits"   = "2"
    "projection.day.type"       = "integer"
    "projection.day.range"      = "1,31"
    "projection.day.digits"     = "2"
    "storage.location.template" = "s3://${var.bucket_name}/events/year=$${year}/month=$${month}/day=$${day}"
  }

  partition_keys {
    name = "year"
    type = "string"
  }
  partition_keys {
    name = "month"
    type = "string"
  }
  partition_keys {
    name = "day"
    type = "string"
  }

  storage_descriptor {
    location      = "s3://${var.bucket_name}/events/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      name                  = "parquet"
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    columns {
      name = "campaign_id"
      type = "string"
    }
    columns {
      name = "product_name"
      type = "string"
    }
    columns {
      name = "region"
      type = "string"
    }
    columns {
      name = "audience"
      type = "string"
    }
    columns {
      name = "event_type"
      type = "string"
    }
    columns {
      name = "generation_time_ms"
      type = "bigint"
    }
    columns {
      name = "cost_usd"
      type = "double"
    }
    columns {
      name = "input_tokens"
      type = "int"
    }
    columns {
      name = "output_tokens"
      type = "int"
    }
    columns {
      name = "nova_canvas_calls"
      type = "int"
    }
    columns {
      name = "compliance_pass"
      type = "int"
    }
    columns {
      name = "compliance_warn"
      type = "int"
    }
    columns {
      name = "compliance_fail"
      type = "int"
    }
    columns {
      name = "approval_status"
      type = "string"
    }
    columns {
      name = "created_at"
      type = "string"
    }
  }
}

resource "aws_kinesis_firehose_delivery_stream" "main" {
  name        = "${var.project_name}-${var.environment}-${var.analytics_key}"
  destination = "extended_s3"

  extended_s3_configuration {
    role_arn            = var.firehose_role_arn
    bucket_arn          = var.bucket_arn
    prefix              = "events/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/"
    error_output_prefix = "errors/!{firehose:error-output-type}/"

    data_format_conversion_configuration {
      input_format_configuration {
        deserializer {
          open_x_json_ser_de {}
        }
      }
      output_format_configuration {
        serializer {
          parquet_ser_de {
            compression = "SNAPPY"
          }
        }
      }
      schema_configuration {
        database_name = aws_glue_catalog_database.main.name
        role_arn      = var.firehose_role_arn
        table_name    = aws_glue_catalog_table.events.name
      }
    }
  }
}
