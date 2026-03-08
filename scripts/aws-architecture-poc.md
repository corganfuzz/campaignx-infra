# CampaignX — Lean POC AWS Architecture Diagram

```mermaid
flowchart LR
    %% ─── Frontend ───
    Frontend["React Frontend\n(Vite + Spectrum S2)"]

    %% ─── API Gateway ───
    subgraph APIGW ["API Gateway — REST v1 + API Key"]
        R1["POST /brief"]
        R3["GET /campaigns"]
        R5["PATCH /campaigns/{id}/approval"]
        R6["GET /insights"]
    end

    %% ─── API Lambdas ───
    subgraph API_Lambdas ["API Lambdas"]
        L1["Lambda 1\nSubmitBrief\n10s / 256MB"]
        L2["Lambda 2\nGetCampaigns\n10s / 256MB"]
        L3["Lambda 3\nUpdateApproval\n10s / 256MB"]
        L4["Lambda 4\nGetInsights\n30s / 256MB"]
    end

    %% ─── Async Pipeline ───
    SQS["SQS Queue\ncampaignx-gen\n+ DLQ"]
    L5["Lambda 5\nGenerateCampaign\n300s / 1024MB / ARM64\nmaxConcurrency: 10"]

    %% ─── Bedrock AI ───
    subgraph Bedrock ["Amazon Bedrock"]
        Agent["Bedrock Agent\nClaude 3.5 Sonnet"]
        Guard["Bedrock Guardrails\nSafety & Compliance"]
        L6["Lambda 6\nCheckCompliance\nAction Group"]
        KB["Knowledge Base\nOpenSearch Serverless\nTitan Embed v2"]
        Nova["Nova Canvas\nImage Generation"]
    end

    %% ─── Data Stores ───
    subgraph Data ["Data Stores"]
        DDB[("DynamoDB\nCampaignTable\nGSI: status-created")]
        S3Out[("S3: Outputs\n/outputs/{id}/{product}")]
        S3In[("S3: Assets Input\n/products/{name}/hero.png")]
        S3RAG[("S3: RAG Docs\n/brand-guidelines/\n/regional-trends/")]
    end

    %% ═══ Connections ═══

    %% Frontend → API Gateway
    Frontend -- "HTTPS / JSON" --> APIGW

    %% Routes → Lambdas
    R1 --> L1
    R3 --> L2
    R5 --> L3
    R6 --> L4

    %% Submit flow
    L1 -- "write status: pending" --> DDB
    L1 -- "enqueue campaign_id" --> SQS

    %% Generation flow
    SQS -- "trigger\nmaxConcurrency: 10" --> L5
    L5 -- "conditional write\nstatus: generating" --> DDB
    L5 -- "check existing images" --> S3In
    L5 -- "invoke agent" --> Agent
    Agent -- "enforce policy" --> Guard
    Agent -- "RAG query" --> KB
    KB -- "read chunks" --> S3RAG
    Agent -- "action group" --> L6
    L5 -- "generate image" --> Nova
    L5 -- "save variations" --> S3Out
    L5 -- "status: complete\napproval: pending_review" --> DDB

    %% Read flow
    L2 -- "query DynamoDB" --> DDB
    L2 -- "presign URLs" --> S3Out

    %% Approval flow
    L3 -- "write approval status" --> DDB

    %% Insights flow (Lean POC)
    L4 -- "direct query / aggregation" --> DDB

    %% Styles
    classDef lambda fill:#f5a623,stroke:#d4881e,color:#000
    classDef storage fill:#3b82f6,stroke:#2563eb,color:#fff
    classDef bedrock fill:#8b5cf6,stroke:#7c3aed,color:#fff
    classDef queue fill:#10b981,stroke:#059669,color:#fff
    classDef route fill:#e2e8f0,stroke:#94a3b8,color:#334155

    class L1,L2,L3,L4,L5,L6 lambda
    class DDB,S3Out,S3In,S3RAG storage
    class Agent,KB,Nova,Guard bedrock
    class SQS queue
    class R1,R3,R5,R6 route
```

### Updated Architecture Summary (Lean POC)

The architecture has been streamlined to focus exclusively on the **Creative Automation Pipeline** while maintaining high quality via Bedrock AI.

| Component | Status | Decision |
|:----------|:-------|:---------|
| **Kinesis / Glue / Athena** | 🔴 Removed | Overkill. Insights now queried directly from DynamoDB. |
| **SNS (Email)** | 🔴 Removed | POC relies on Dashboard UI polling/refreshes. |
| **EventBridge Scheduler** | 🔴 Removed | KB sync triggered manually via Console/CLI for POC. |
| **Analytics Bucket** | 🔴 Removed | Data footprint reduced to pure campaign assets. |
| **Bedrock Agent / KB** | 🟢 Kept | Core to the Generative AI demonstration. |
| **CheckCompliance** | 🟢 Kept | Demonstrates integration of "Nice to have" brand safety requirements. |

### Updated API Route Map

| Route | Handler | Action |
|:------|:--------|:-------|
| `POST /brief` | Lambda 1 | Validates brief → Creates DynamoDB item → Enqueues SQS message. |
| `GET /campaigns` | Lambda 2 | Fetches campaign lists and details from DynamoDB. |
| `PATCH /campaigns/{id}/approval` | Lambda 3 | Updates the processing status in DynamoDB (Approve/Reject). |
| `GET /insights` | Lambda 4 | Aggregates campaign metrics directly from the DynamoDB table. |
| `SQS Trigger` | Lambda 5 | Main worker: Bedrock Agent orchestration + Image generation. |
