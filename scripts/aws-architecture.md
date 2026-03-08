# CampaignX — AWS Architecture Diagram

```mermaid
flowchart LR
    %% ─── Frontend ───
    Frontend["React Frontend\n(Vite + Spectrum S2)"]

    %% ─── API Gateway ───
    subgraph APIGW ["API Gateway — REST v1 + API Key"]
        R1["POST /brief"]
        R2["POST /briefs/batch"]
        R3["GET /campaigns"]
        R4["GET /campaigns/{id}"]
        R5["PATCH /campaigns/{id}/approval"]
        R6["GET /insights"]
    end

    %% ─── API Lambdas ───
    subgraph API_Lambdas ["API Lambdas"]
        L1["Lambda 1\nSubmitBrief\n10s / 256MB"]
        L4["Lambda 4\nGetCampaigns\n10s / 256MB"]
        L7["Lambda 7\nUpdateApproval\n10s / 256MB"]
        L5["Lambda 5\nGetInsights\n30s / 256MB"]
    end

    %% ─── Async Pipeline ───
    SQS["SQS Queue\ncampaignx-gen\n+ DLQ + Alarm"]
    L2["Lambda 2\nGenerateCampaign\n300s / 1024MB / ARM64\nmaxConcurrency: 10"]

    %% ─── Bedrock AI ───
    subgraph Bedrock ["Amazon Bedrock"]
        Agent["Bedrock Agent\nClaude 3.5 Sonnet"]
        L3["Lambda 3\nCheckCompliance\nGuardrails"]
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

    %% ─── Analytics ───
    subgraph Analytics ["Analytics Pipeline"]
        Firehose["Kinesis Firehose\nJSON → Parquet"]
        S3A[("S3: Analytics\nPartitioned by date")]
        Glue["Glue Catalog\nPartition Projection"]
        Athena["Athena\nSQL over S3"]
    end

    %% ─── Scheduling & Notifications ───
    SNS["SNS\nEmail Notifications"]
    EB["EventBridge\nDaily Cron"]
    L6["Lambda 6\nRefreshKnowledge\n300s / 512MB"]

    %% ═══ Connections ═══

    %% Frontend → API Gateway
    Frontend -- HTTPS --> APIGW

    %% Routes → Lambdas
    R1 & R2 --> L1
    R3 & R4 --> L4
    R5 --> L7
    R6 --> L5

    %% Submit flow
    L1 -- "write status: pending" --> DDB
    L1 -- "enqueue campaign_id" --> SQS

    %% Generation flow
    SQS -- "trigger\nmaxConcurrency: 10" --> L2
    L2 -- "conditional write\nstatus: generating" --> DDB
    L2 -- "check existing images" --> S3In
    L2 -- "invoke agent" --> Agent
    Agent -- "RAG query" --> KB
    KB -- "read chunks" --> S3RAG
    Agent -- "action group" --> L3
    L2 -- "generate image" --> Nova
    L2 -- "save 6 PNGs" --> S3Out
    L2 -- "status: complete\napproval: pending_review" --> DDB
    L2 -- "emit event" --> Firehose

    %% Read flow
    L4 -- "query + presign URLs" --> DDB
    L4 -- "presigned URLs" --> S3Out

    %% Approval flow
    L7 -- "write approval" --> DDB
    L7 -- "notify reviewer" --> SNS
    L7 -- "emit event" --> Firehose

    %% Insights flow
    L5 -- "SQL query" --> Athena

    %% Analytics pipeline
    Firehose -- "batch + convert" --> S3A
    S3A --- Glue
    Athena -- "read partitions" --> Glue

    %% Learning loop
    EB -- "daily midnight" --> L6
    L6 -- "query patterns" --> Athena
    L6 -- "write learnings.md" --> S3RAG
    L6 -- "re-index KB" --> KB

    %% ═══ Styles ═══
    classDef lambda fill:#f5a623,stroke:#d4881e,color:#000
    classDef storage fill:#3b82f6,stroke:#2563eb,color:#fff
    classDef bedrock fill:#8b5cf6,stroke:#7c3aed,color:#fff
    classDef queue fill:#10b981,stroke:#059669,color:#fff
    classDef route fill:#e2e8f0,stroke:#94a3b8,color:#334155

    class L1,L2,L3,L4,L5,L6,L7 lambda
    class DDB,S3Out,S3In,S3RAG,S3A storage
    class Agent,KB,Nova bedrock
    class SQS,Firehose,SNS queue
    class R1,R2,R3,R4,R5,R6 route
```

### Component Legend

| Color | Meaning | Components |
|:------|:--------|:-----------|
| 🟠 Orange | Lambda Functions | L1–L7 (all 7 functions) |
| 🔵 Blue | Storage (S3 / DynamoDB) | 4 S3 buckets + CampaignTable |
| 🟣 Purple | Bedrock AI Services | Agent, Knowledge Base, Nova Canvas |
| 🟢 Green | Queues / Streaming | SQS, Kinesis Firehose, SNS |
| ⬜ Gray | API Routes | All 6 REST endpoints |

### API Route Map

| Route | Lambda | Action |
|:------|:-------|:-------|
| `POST /brief` | Lambda 1 | Validate brief → DynamoDB + SQS |
| `POST /briefs/batch` | Lambda 1 | Validate up to 50 briefs → DynamoDB + SQS |
| `GET /campaigns` | Lambda 4 | List campaigns from DynamoDB |
| `GET /campaigns/{id}` | Lambda 4 | Get campaign detail + presigned image URLs |
| `PATCH /campaigns/{id}/approval` | Lambda 7 | Set approved/rejected → DynamoDB + SNS + Firehose |
| `GET /insights` | Lambda 5 | Athena query (cached 1hr in DynamoDB) |
