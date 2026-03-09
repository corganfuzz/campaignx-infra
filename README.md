# Concrete Focus

An enterprise-grade AI pipeline designed to automate the generation of localized, brand-compliant social media creative assets. It leverages **Amazon Bedrock** (Claude 3.5 Haiku & Nova Canvas) to transform a simple campaign brief into a complete set of marketing assets across multiple aspect ratios.

## Key Features

-   **Intelligent Brief Ingestion:** Supports manual entry or drag-and-drop ingestion of **JSON** and **YAML** campaign briefs.
-   **Multi-Product Support:** Orchestrates creative generation for multiple products within a single campaign.
-   **Localized Creative Pipeline:** Automatically translates and adapts messaging based on target market brand guidelines.
-   **AI-Driven Compliance:** Integrates Bedrock Guardrails to ensure all ad copy meets legal and brand safety standards.
-   **Human-in-the-Loop:** Built-in approval workflow for creative review before final asset export.
-   **Knowledge Base (RAG):** Real-time learning from brand guidelines and regional market trends stored in an OpenSearch vector database.
-   **Direct Asset Download:** High-performance download utility using S3 CORS and browser-side Blob fetching for professional fidelity.

## Architecture

The system is built on a serverless AWS architecture for maximum scalability and zero maintenance:

-   **API Layer:** AWS API Gateway (REST v1) with API Key security.
-   **Compute:** AWS Lambda (Python 3.12) with SQS decoupling for heavy image processing tasks.
-   **AI Engine:** Amazon Bedrock (Agents, Knowledge Bases, and Guardrails).
-   **Vector Store:** Amazon OpenSearch Serverless.
-   **Storage:** Amazon S3 with standardized CORS policies for frontend integration.
-   **Database:** Amazon DynamoDB for campaign state management and analytics.

## Infrastructure Setup

The infrastructure is managed entirely via **Terraform**.

### Prerequisites
-   AWS CLI configured with appropriate credentials.
-   Terraform >= 1.5.0.
-   Python 3.12 (for Lambda layer builds).

### Deployment
1.  Initialize and apply the Terraform configuration:
    ```bash
    cd env/dev
    terraform init
    terraform apply
    ```
2.  Sync the Knowledge Base (populate with product and brand data):
    ```bash
    # Get the sync command from terraform output
    terraform output knowledge_base_sync_command
    # Run the provided script
    ./scripts/sync_kb.sh <KB_ID> <DS_ID>
    ```

## Testing the Pipeline

We provide pre-configured YAML briefs in `test-briefs/` to verify the multi-product and localization logic:
- `summit-trek.yaml`: 2 products, USA market.
- `ergopro-desk.yaml`: 2 products, Germany market (localized).
- `dove-shampoo.yaml`: 2 products, Brazil market (localized).

## 📅 Roadmap (v3.1+)

-   [ ] **Automatic Logo Watermarking:** Integration with the Pillow Lambda layer to overlay brand logos on generated assets.
-   [ ] **Bulk Export:** Zip-based batch download for entire campaign folders.
-   [ ] **Video Generation:** Integration with Amazon Nova Reel for social video assets.

---
© 2026 Concrete Focus | GR