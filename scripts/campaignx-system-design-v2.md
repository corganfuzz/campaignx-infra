# CampaignX — AI Creative Automation Pipeline
## System Design & Implementation Guide — v2

> **Changelog from v1:** This revision addresses all inconsistencies and improvements identified in the v1 review. Key changes: REST API v1 alignment, status/approval_status state machine fix, embedding model standardization (Titan Embed v2), analytics pipeline deduplication, Lambda concurrency controls, idempotency guards, GSI redesign, batch size limits, Parquet analytics, Pillow layer build fix, frontend error handling, and DLQ alarms.

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Requirements](#2-requirements)
3. [Back-of-the-Envelope Estimation](#3-back-of-the-envelope-estimation)
4. [High-Level Design](#4-high-level-design)
5. [Deep Dive — Data Flow](#5-deep-dive--data-flow)
6. [Deep Dive — Component Design](#6-deep-dive--component-design)
7. [Deep Dive — Database Design](#7-deep-dive--database-design)
8. [Deep Dive — API Design](#8-deep-dive--api-design)
9. [Deep Dive — Frontend Architecture](#9-deep-dive--frontend-architecture)
10. [Deep Dive — AI Pipeline](#10-deep-dive--ai-pipeline)
11. [Deep Dive — Analytics & Feedback Loop](#11-deep-dive--analytics--feedback-loop)
12. [Deep Dive — Approval Workflow](#12-deep-dive--approval-workflow)
13. [Infrastructure as Code](#13-infrastructure-as-code)
14. [How to Recreate From Scratch](#14-how-to-recreate-from-scratch)
15. [Key Design Decisions & Trade-offs](#15-key-design-decisions--trade-offs)
16. [Known Limitations](#16-known-limitations)
17. [Future Improvements](#17-future-improvements)

---

## 1. Problem Statement

A global consumer goods company launches hundreds of localized social ad campaigns every month across dozens of markets.

Today this is done manually:
- A creative team writes briefs
- Agencies produce assets per region
- Legal and brand teams review
- Stakeholders in each market approve
- Assets get scheduled and published

This process is slow (weeks per campaign), expensive (agencies + revisions), inconsistent (off-brand creative slips through), and impossible to learn from (siloed performance data).

**The business goal:** design a system that takes a campaign brief as input and produces brand-compliant, legally-vetted, localized creative assets for three social platforms — fully automated.

---

## 2. Requirements

### Functional Requirements

| ID | Requirement |
|----|-------------|
| FR1 | Accept a campaign brief (JSON or YAML) with product name(s), target region, audience, core message, and preferred language |
| FR2 | Generate hero images for each product in three aspect ratios: 1:1 (Instagram), 9:16 (TikTok/Reels), 16:9 (YouTube) |
| FR3 | Overlay localized text on each generated image |
| FR4 | Save all assets in an organized folder structure: `/outputs/{campaign_id}/{product_name}/{ratio}.png` |
| FR5 | Enforce brand compliance on all generated creative |
| FR6 | Enforce legal compliance — no prohibited claims or terms |
| FR7 | Support an approval workflow — campaigns must be reviewed and approved before being considered final |
| FR8 | Provide analytics: cost, compliance rates, top markets, generation performance |
| FR9 | Support batch submission — submit many briefs at once (max 50 per request) |
| FR10 | The system must learn over time — past campaign patterns should inform future creative decisions |

### Non-Functional Requirements

| ID | Requirement |
|----|-------------|
| NFR1 | Hundreds of campaigns per month — scale horizontally without infrastructure changes |
| NFR2 | Generation of one campaign (2 products × 3 ratios = 6 images) must complete within 10 minutes |
| NFR3 | Brand and legal guardrails must apply to 100% of outputs with no exceptions |
| NFR4 | Reproducible across environments (dev, staging, prod) via Infrastructure as Code |
| NFR5 | All generated assets must be durable — S3 with versioning enabled |
| NFR6 | Generation must be idempotent — SQS retries must not duplicate work or double-charge Bedrock |

### Out of Scope

- Ad platform integration (Meta, TikTok, Google) — publish step is manual or a future phase
- A/B testing of creatives
- Real-time performance data ingestion (CTR, conversions) — the analytics pipeline is architected to accept this in a future phase

---

## 3. Back-of-the-Envelope Estimation

```
Campaigns per month:              ~500
Products per campaign:            2 (minimum)
Images per product:               3 aspect ratios
Total images per month:           500 × 2 × 3 = 3,000 images

Nova Canvas image generation:     ~10–20s per image
Total generation time (serial):   3,000 × 15s = 45,000s = 12.5 hrs
Total generation time (parallel): ~15 minutes at 50 concurrent

→ Parallelism via SQS + Lambda concurrency is NOT optional.
  It is required to meet NFR2 at scale.
→ SQS maxConcurrency capped at 10 to avoid Bedrock throttling.
  Bedrock Sonnet quota is typically 5–50 concurrent invocations.

Storage:
  Average image size (PNG):       ~2 MB
  Monthly storage:                3,000 × 2 MB = ~6 GB
  Annual storage:                 ~72 GB
  S3 cost (us-east-1):           ~$1.65 / month

DynamoDB:
  Writes per campaign:            ~10 (status updates)
  Monthly writes:                 ~5,000
  → Well within on-demand pricing. No capacity planning needed.

Bedrock API cost per campaign:
  Claude 3.5 Sonnet:              ~2,000 input + 500 output tokens
                                  At $3/M input, $15/M output → ~$0.013
  Nova Canvas:                    ~$0.08 per image × 6 images → ~$0.48
  Total per campaign:             ~$0.50
  Monthly (500 campaigns):        ~$250
```

---

## 4. High-Level Design

```
                    ┌─────────────────────────────────┐
                    │         REACT FRONTEND          │
                    │   (Vite + React Spectrum S2)    │
                    │                                 │
                    │  Home | Brief Form | Canvas     │
                    │  Loading | Insights             │
                    └──────────────┬──────────────────┘
                                   │ HTTPS
                                   ▼
                    ┌─────────────────────────────────┐
                    │     API GATEWAY (REST v1)       │
                    │   (API key authentication)      │
                    │                                 │
                    │  POST  /brief                   │
                    │  POST  /briefs/batch            │
                    │  GET   /campaigns               │
                    │  GET   /campaigns/{id}          │
                    │  PATCH /campaigns/{id}/approval │
                    │  GET   /insights                │
                    └───┬──────────┬──────────┬───────┘
                        │          │          │
              ┌─────────▼──┐  ┌────▼──────┐  ┌▼────────────┐  ┌─────────────┐
              │  Lambda 1  │  │ Lambda 4  │  │  Lambda 5   │  │  Lambda 7   │
              │SubmitBrief │  │GetCampaign│  │ GetInsights │  │UpdateApproval│
              └─────┬──────┘  └────┬──────┘  └──────┬──────┘  └──────┬──────┘
                    │              │                 │                │
                    ▼              ▼                 ▼                ▼
                SQS Queue      DynamoDB           Athena            SNS
                    │          (campaigns)     (analytics S3)   (email notify)
                    │
                    ▼
    ┌───────────────────────────────────────────────────────┐
    │            Lambda 2 — GenerateCampaign                │
    │      (maxConcurrency: 10 via SQS event source)       │
    │                                                       │
    │  0. Idempotency: check DynamoDB status + S3 outputs  │
    │  1. Read brief from DynamoDB                          │
    │  2. Check S3 assets-input for existing brand images   │
    │  3. Invoke Bedrock Agent (Claude 3.5 Sonnet)          │
    │     ├── Agent queries Knowledge Base (RAG)            │
    │     ├── Agent calls CreativeStrategy → Lambda 3       │
    │     └── Agent calls ComplianceCheck  → Lambda 3       │
    │  4. Call Nova Canvas → base64 image                   │
    │  5. Pillow: resize to 1:1, 9:16, 16:9                │
    │  6. Pillow: overlay localized text on each image      │
    │  7. Save 6 images to S3 outputs bucket                │
    │  8. Update DynamoDB:                                  │
    │     → status: "complete"                              │
    │     → approval_status: "pending_review"               │
    │  9. Emit event to Kinesis Firehose                    │
    └───────────────────────────────────────────────────────┘
                    │
        ┌───────────┼────────────┐
        ▼           ▼            ▼
    DynamoDB    Bedrock KB    Kinesis
    (status)     (RAG)       Firehose → S3 Analytics (Parquet)
                                              │
                                        Glue + Athena
                                              │
                                         Lambda 5      Lambda 6
                                        (insights)   (daily KB
                                                       refresh)
```

> **Lambda 3** (CheckCompliance) is internal only — called exclusively by the Bedrock Agent action group, never by API Gateway directly.
>
> **Lambda 6** (RefreshKnowledge) is triggered by EventBridge on a daily cron, not by any API route.
>
> **REST API v1** is used (not HTTP v2) because it supports native API key authentication without requiring a separate Lambda authorizer.

---

## 5. Deep Dive — Data Flow

### Flow 1: Generation (user-initiated)

```
User submits brief
  → POST /brief
  → Lambda 1: validates schema, writes DynamoDB (status: pending), pushes to SQS
  → Returns 202 + { campaign_id }

Frontend navigates to loading screen, polls GET /campaigns/{id} every 3s

SQS triggers Lambda 2 (maxConcurrency: 10 via event source mapping)
  → Idempotency check:
      Read DynamoDB status.
      IF status != "pending" → skip (already processing or done)
      Conditional write: set status = "generating"
        ConditionExpression: status = "pending"
        IF condition fails → exit (another instance picked it up)

  → Check S3 assets-input:
      IF image exists → reuse it (skip Nova Canvas, saves ~$0.48)
      IF missing      → continue

  → Invoke Bedrock Agent (with exponential backoff for ThrottlingException)
      Agent queries Knowledge Base (semantic search over OpenSearch)
        Retrieves: brand guidelines chunks + regional trend chunks
      Agent calls CreativeStrategy action group → Lambda 3
        Returns: image_prompt + localized ad_copy
      Agent calls ComplianceCheck action group → Lambda 3
        Applies Bedrock Guardrails to ad_copy
        Returns: { pass: [], warn: [], fail: [] }
        IF fail → agent revises and re-checks (up to 3 attempts)

  → Call Nova Canvas with image_prompt → base64 PNG
  → Pillow: resize to 3 aspect ratios
  → Pillow: composite localized text overlay on each
  → Upload 6 images to S3 (check if image already exists before uploading):
        s3://campaignx-outputs/outputs/{id}/{product}/1x1.png
        s3://campaignx-outputs/outputs/{id}/{product}/9x16.png
        s3://campaignx-outputs/outputs/{id}/{product}/16x9.png

  → Update DynamoDB:
        status: "complete"
        approval_status: "pending_review"
        output_paths: { "1x1": "s3://...", ... }
        compliance: { pass: [...], warn: [...] }
        cost_usd: 0.51
        token_counts: { input: 1842, output: 487 }

  → Emit event to Kinesis Firehose

Frontend poll returns status: "complete" + approval_status: "pending_review" → Canvas renders
Frontend poll returns status: "failed" → error screen with failure_reason
Frontend poll exceeds 10 minutes → timeout error with retry option
```

### Flow 2: Approval (reviewer-initiated)

```
Reviewer opens Canvas → sees Approval block (approval_status: pending_review)
  → Clicks Approve or Reject (with optional notes)
  → PATCH /campaigns/{id}/approval
  → Lambda 7: writes approval_status, reviewed_by, reviewed_at to DynamoDB
  → Lambda 7: publishes to SNS → email notification to creative team
  → Lambda 7: emits approval event to Kinesis Firehose
Frontend reflects updated status
```

### Flow 3: Learning (system-initiated, daily)

```
EventBridge fires cron → daily at midnight
  → Lambda 6 (RefreshKnowledge)

  → Query Athena (last 30 days):
        SELECT region, AVG(compliance_fail), AVG(cost_usd), COUNT(*)
        FROM campaign_events
        GROUP BY region

  → Identify patterns:
        "Brazil campaigns: 0 compliance fails when
         image_prompt includes warm color palette"

  → Write learnings to S3 RAG bucket:
        s3://campaignx-rag-docs/regional-trends/brazil_learnings.md

  → Call Bedrock StartIngestionJob → re-index both data sources

Next Brazil campaign retrieves brazil_learnings.md via RAG
→ Better creative from day one, no human curation required
```

This feedback loop means campaign quality improves continuously without model retraining or manual intervention.

---

## 6. Deep Dive — Component Design

### Lambda Functions (7 total)

| # | Name | Trigger | Timeout | Memory | Architecture | Purpose |
|---|------|---------|---------|--------|-------------|---------|
| 1 | SubmitBrief | POST /brief, POST /briefs/batch | 10s | 256 MB | x86_64 | Validate brief, write DynamoDB, push to SQS |
| 2 | GenerateCampaign | SQS (maxConcurrency: 10) | 300s | 1024 MB | arm64 | Full generation pipeline — the workhorse |
| 3 | CheckCompliance | Bedrock Agent action group (internal) | 30s | 256 MB | x86_64 | Apply Guardrails, return compliance report |
| 4 | GetCampaigns | GET /campaigns, GET /campaigns/{id} | 10s | 256 MB | x86_64 | Query DynamoDB, generate S3 presigned URLs |
| 5 | GetInsights | GET /insights | 30s | 256 MB | x86_64 | Execute Athena queries, return analytics |
| 6 | RefreshKnowledge | EventBridge cron (daily) | 300s | 512 MB | x86_64 | Query Athena patterns, write RAG learnings, trigger KB sync |
| 7 | UpdateApproval | PATCH /campaigns/{id}/approval | 10s | 256 MB | x86_64 | Write approval to DynamoDB, publish SNS, emit Firehose event |

> Lambda 2 uses **arm64 (Graviton2)** for 20% cost savings and better performance on image processing workloads. All other Lambdas use x86_64 (default).
>
> Lambda 3 is never called by API Gateway. It is wired exclusively as a Bedrock Agent action group executor. Lambda 6 has no API route — it is a scheduled background job.
>
> Lambda 2's **SQS event source mapping** uses `maxConcurrency: 10` to prevent overwhelming Bedrock's per-model throttling limits. This means at most 10 campaigns generate simultaneously. At ~5 minutes per campaign, this processes ~120 campaigns/hour — sufficient for 500/month.

### SQS Queue

```
Queue:            campaignx-{env}-campaign-gen
Type:             Standard (ordering not required)
Visibility:       360s (60s buffer above Lambda timeout of 300s)
Retention:        1 day
DLQ:              campaignx-{env}-campaign-gen-dlq
Max receive count: 3 retries before moving to DLQ
```

**DLQ Alarm:**
```
CloudWatch Alarm:  campaignx-{env}-dlq-alarm
Metric:            ApproximateNumberOfMessagesVisible > 0
Period:            60s
SNS Target:        campaignx-{env}-campaign-approvals (reuse existing topic)
```

When a message hits the DLQ, the team gets an email alert. This prevents silent failures where campaigns are stuck without anyone knowing.

**Why SQS:** Without a queue, Lambda 1 would invoke Lambda 2 synchronously and block for 5 minutes per campaign. SQS decouples submission from generation. Lambda scales to match queue depth automatically — but capped at `maxConcurrency: 10` to respect Bedrock throttling limits.

### S3 Buckets (4 total)

| Bucket | Contents | Read by | Write by |
|--------|----------|---------|----------|
| `campaignx-{env}-rag-docs` | `/brand-guidelines/`, `/regional-trends/` | Bedrock KB | Lambda 6 (auto-updates learnings) |
| `campaignx-{env}-assets-input` | `/products/{name}/hero.png` | Lambda 2 | Creative team (manual upload) |
| `campaignx-{env}-outputs` | `/outputs/{id}/{product}/{ratio}.png` | Lambda 4, Frontend | Lambda 2 |
| `campaignx-{env}-analytics` | `/events/year/month/day/` (Parquet) | Athena, Lambda 5, Lambda 6 | Kinesis Firehose |

All buckets: versioning ON, SSE-AES256, public access blocked. Outputs bucket has GET CORS enabled for in-browser image display.

> Frontend hosting is **not** managed by this Terraform. Deploy to Vercel/Netlify or manage a separate S3+CloudFront stack.

### SNS Topic

```
Topic:     campaignx-{env}-campaign-approvals
Protocol:  email
Endpoint:  creative-team@company.com (set in locals.tf)
Triggers:  Lambda 7 on every approval or rejection
           CloudWatch DLQ alarm on failed campaigns
Note:      Subscriber must click confirmation email after first terraform apply
```

---

## 7. Deep Dive — Database Design

### DynamoDB — CampaignTable

**Primary Key:** `campaign_id` (PK, String) + `product_name` (SK, String)

> Rationale for composite key: a single campaign covers multiple products. `campaign_id` as PK allows querying all products in one campaign. `product_name` as SK allows targeting a specific product. Both patterns are needed and neither requires a scan.

**Attributes:**

| Attribute | Type | Values / Notes |
|-----------|------|----------------|
| `campaign_id` | String | UUID — partition key |
| `product_name` | String | e.g. "Dove Shampoo" — sort key |
| `status` | String | `pending` \| `generating` \| `complete` \| `failed` |
| `approval_status` | String | `pending_review` \| `approved` \| `rejected` — **not set on initial write** |
| `failure_reason` | String | Set only when status = "failed" (e.g. "compliance hard fail after 3 attempts") |
| `brief` | Map | `{ region, audience, message, language }` |
| `output_paths` | Map | `{ "1x1": "s3://...", "9x16": "...", "16x9": "..." }` |
| `compliance` | Map | `{ pass: [...], warn: [...], fail: [...] }` |
| `cost_usd` | Number | e.g. `0.51` |
| `token_counts` | Map | `{ input: 1842, output: 487 }` |
| `nova_canvas_calls` | Number | e.g. `3` |
| `reviewed_by` | String | reviewer email |
| `reviewer_notes` | String | optional free text |
| `reviewed_at` | String | ISO 8601 timestamp |
| `created_at` | String | ISO 8601 timestamp |
| `ttl` | Number | Unix timestamp — auto-expire records after 90 days |

> **`approval_status` lifecycle:** Not set on initial write (Lambda 1). Set to `pending_review` only when Lambda 2 completes successfully (status = "complete"). The GSI naturally excludes items without `approval_status` (sparse index behavior), so the reviewer dashboard only shows campaigns that have finished generating.

**Global Secondary Index:**

```
Name:       status-created-index
Hash key:   approval_status
Sort key:   created_at
Purpose:    Query all campaigns WHERE approval_status = "pending_review"
            ORDER BY created_at DESC LIMIT 20
            Powers a reviewer dashboard without a full table scan.
            Sort key enables pagination and chronological ordering.
```

> GSI is sparse — items without `approval_status` are excluded automatically. This means only completed campaigns appear in the index, which is the desired behavior.

**Billing:** `PAY_PER_REQUEST` — zero cost when idle, no capacity planning at POC scale.

### Analytics Store — S3 + Glue + Athena

Not a traditional database. Raw events land in S3 as **Parquet** (converted by Firehose), partitioned by date. Glue Catalog provides the schema. Athena runs SQL directly over S3 — no database server.

> **Why Parquet over GZIP JSON:** Parquet is columnar — Athena reads only the columns needed per query. This is 5–10x faster and 30–90% cheaper for analytical queries. Firehose converts JSON → Parquet automatically using the Glue table schema.

**Glue table schema (`campaign_events`):**

```
campaign_id          string
product_name         string
region               string
audience             string
event_type           string    ← "generation" | "approval"
generation_time_ms   bigint
cost_usd             double
input_tokens         int
output_tokens        int
nova_canvas_calls    int
compliance_pass      int
compliance_warn      int
compliance_fail      int
approval_status      string
created_at           string
year / month / day   string   ← partition keys (with partition projection)
```

> **Partition projection** is enabled on the Glue table. This eliminates the need for `MSCK REPAIR TABLE` after new partitions are created and speeds up partition discovery.

---

## 8. Deep Dive — API Design

All endpoints use **REST API v1** (API Gateway). CORS enabled via OPTIONS methods on all resources. API key authentication enabled — no Cognito at POC stage.

> **Why REST v1 over HTTP v2:** REST API v1 supports native API key usage plans without a Lambda authorizer. HTTP v2 (`.../apigatewayv2/...`) does not support API keys natively. The trade-off is higher cost ($3.50/M vs $1.00/M requests) and more verbose CORS setup, but at POC scale (~100K requests/month) the cost difference is ~$0.25/month.

> **REST v1 Lambda integration note:** REST v1 sends a different event format than HTTP v2. Lambda handlers must use `event["body"]` (string, must be JSON-parsed), `event["pathParameters"]`, and `event["queryStringParameters"]`. Response format must include `statusCode`, `headers`, and `body` (string).

### POST /brief

```json
// Request
{
  "product_name": "Dove Shampoo",
  "region": "brazil",
  "audience": "women 25-40",
  "message": "Feel confident every day",
  "language": "pt-BR"
}

// Response 202
{
  "campaign_id": "a3f2b1c9-...",
  "product_name": "Dove Shampoo",
  "status": "pending"
}
```

### POST /briefs/batch

```json
// Request (max 50 briefs per request)
{
  "briefs": [
    { "product_name": "...", "region": "...", "audience": "...", "message": "...", "language": "..." },
    { "product_name": "...", "region": "...", "audience": "...", "message": "...", "language": "..." }
  ]
}

// Response 202
{
  "batch_id": "b9c3...",
  "campaign_ids": ["a3f2...", "c9d4..."],
  "count": 2
}

// Response 400 (if > 50 briefs)
{
  "error": "Batch size exceeds maximum of 50 briefs per request"
}
```

> **Batch limits:** Max 50 briefs per request. Lambda 1 writes to DynamoDB in batches of 25 (`BatchWriteItem` limit) and to SQS in batches of 10 (`SendMessageBatch` limit). At 50 briefs: 2 DynamoDB batches + 5 SQS batches, well within the 10s Lambda timeout.

### GET /campaigns/{id}

```json
// Response 200 (in progress)
{ "campaign_id": "...", "status": "generating" }

// Response 200 (complete, awaiting review)
{
  "campaign_id": "...",
  "status": "complete",
  "approval_status": "pending_review",
  "output_paths": {
    "1x1":  "https://presigned-s3-url...",
    "9x16": "https://presigned-s3-url...",
    "16x9": "https://presigned-s3-url..."
  },
  "compliance": {
    "pass": ["no prohibited words", "brand colors present"],
    "warn": ["headline slightly long"],
    "fail": []
  },
  "cost_usd": 0.51,
  "ad_copy": {
    "headline": "Sinta-se confiante todo dia",
    "body": "Dove Shampoo cuida dos seus cabelos...",
    "cta": "Compre agora"
  }
}

// Response 200 (failed)
{
  "campaign_id": "...",
  "status": "failed",
  "failure_reason": "Compliance hard fail after 3 revision attempts"
}
```

### PATCH /campaigns/{id}/approval

```json
// Request
{
  "approval_status": "approved",
  "reviewer_notes": "Great work for the Brazil market",
  "reviewed_by": "jane@company.com"
}

// Response 200
{ "campaign_id": "...", "approval_status": "approved" }
```

### GET /insights

```json
// Response 200
{
  "total_campaigns": 847,
  "top_regions": [
    { "region": "brazil", "count": 82 },
    { "region": "usa",    "count": 61 }
  ],
  "avg_cost_usd": 0.49,
  "total_cost_usd": 415.03,
  "compliance_pass_rate": 0.94,
  "avg_generation_time_ms": 42300,
  "most_flagged_terms": ["guaranteed", "proven"],
  "kb_last_refreshed": "2025-04-01T00:00:00Z"
}
```

> **Insights caching:** Lambda 5 caches Athena results in DynamoDB with a 1-hour TTL. Subsequent requests within the hour return the cached result, avoiding repeated Athena queries (~$5/TB scanned).

---

## 9. Deep Dive — Frontend Architecture

### Tech Stack

| Layer | Technology |
|-------|-----------:|
| Framework | React 18 + Vite + TypeScript |
| Package manager | Bun |
| UI library | Adobe React Spectrum S2 (`@react-spectrum/s2`) |
| Macro plugin | `unplugin-parcel-macros` — **must come first** in `vite.config.ts` |
| Styling | React Spectrum S2 style macro + scoped CSS files |

### Screen Flow

```
Home → BriefForm → LoadingPipeline → Canvas → [Insights]
                                   ↘ ErrorScreen (on failure/timeout)
```

| Screen | Purpose |
|--------|---------|
| Home | Recent campaigns list, prompt bar to start a new one |
| BriefForm | Manual form OR JSON/YAML file upload; batch mode uploads CSV or JSON array (max 50) |
| LoadingPipeline | Animated pipeline steps while polling `GET /campaigns/{id}` every 3s |
| Canvas | Sophia-style blueprint with 9 blocks (see below) |
| Insights | Analytics dashboard powered by `GET /insights` |
| ErrorScreen | Displayed when status = "failed" or polling exceeds 10 minutes |

### Canvas Blocks (Sophia-style Blueprint)

| Block | Name | Content |
|-------|------|---------|
| A | Creative Strategy | Agent's reasoning — why this creative for this market |
| B | Image 1:1 | Generated Instagram image + download button |
| C | Image 9:16 | Generated TikTok/Reels image + download button |
| D | Image 16:9 | Generated YouTube image + download button |
| E | Ad Copy | Localized headline, body text, CTA |
| F | Compliance Report | Pass / Warn / Fail items, colour-coded green / amber / red |
| G | Suggested Next Steps | Agent recommendations for this market |
| H | Output Files | Folder tree of saved asset paths, cost and token report |
| I | Approval Status | Status badge, Approve/Reject buttons, reviewer notes field |

### AI Cursor

Every block has a floating popover (AI Cursor pattern). The user types a refinement ("make it more vibrant", "translate to Spanish"). Only that block regenerates via a targeted API call — the rest of the canvas stays intact. This is the key UX differentiator of the Sophia-style canvas.

### Polling Pattern

Frontend polls `GET /campaigns/{id}` every 3 seconds.

```
pending → generating → complete (approval_status: pending_review) → approved | rejected
                     → failed (show ErrorScreen with failure_reason)

Timeout: if polling exceeds 10 minutes without status change from "generating",
         show timeout error with retry option.
```

On `status: "complete"` the canvas renders with real images. On `status: "failed"` the ErrorScreen renders with the `failure_reason` from DynamoDB. No WebSockets required — polling every 3s costs ~100 API calls per campaign (negligible), and the UX difference vs push notification is imperceptible for a 1–5 minute generation job.

### File Structure

```
src/
├── App.tsx                   router + Provider wrapper
├── main.tsx                  entry point — <Provider colorScheme="dark">
├── types/index.ts            all TypeScript types
├── data/mockData.ts          mock campaign for local development
├── hooks/useCampaign.ts      all state + API call logic
├── api.ts                    fetch wrappers for all 6 endpoints
├── pages/
│   ├── Home.tsx + .css
│   ├── BriefForm.tsx + .css
│   ├── LoadingPipeline.tsx + .css
│   ├── Canvas.tsx + .css
│   ├── ErrorScreen.tsx + .css
│   └── Insights.tsx + .css
└── components/
    ├── layout/TopNav.tsx + .css
    └── shared/
        ├── AICursor.tsx + .css
        └── ImageDetail.tsx + .css
```

### Important Setup Notes

1. **Macro plugin order** in `vite.config.ts`:
   ```ts
   plugins: [macros.vite(), react()]  // macros MUST come first
   ```

2. **React Spectrum S2 breaking change:** no `Flex` or `Grid` components — use `<div>` with style macro instead.

3. **Wrap entire app in Provider:**
   ```tsx
   <Provider colorScheme="dark">
     <App />
   </Provider>
   ```

4. **To connect to real API:** edit `src/hooks/useCampaign.ts` only. Replace `mockGenerateCampaign()` with real API calls via `src/api.ts`. All UI components remain unchanged.

5. **REST v1 API key:** include `x-api-key` header in all fetch calls in `src/api.ts`.

---

## 10. Deep Dive — AI Pipeline

### Models Used

| Role | Model | Model ID |
|------|-------|----------|
| Campaign Orchestrator (LLM) | Claude 3.5 Sonnet | `anthropic.claude-3-5-sonnet-20241022-v2:0` |
| Image Generation | Amazon Nova Canvas | `amazon.nova-canvas-v1:0` |
| Embeddings / RAG | Amazon Titan Embed Text v2 | `amazon.titan-embed-text-v2:0` — 1024 dimensions |

> **Why Titan Embed v2 over Nova Embed v1:** Titan Embed v2 is more mature, has configurable dimensions (256/512/1024 — useful for cost optimization later), and is widely documented. The OpenSearch index MUST be configured with the same dimension count (1024).

### Bedrock Agent

**Name:** `campaignx-{env}-campaign-orchestrator`
**Instruction file:** `modules/bedrock/src/agent.txt`

The agent has two action groups and one knowledge base association. Execution flow per brief:

```
Agent receives: { product_name, region, message, audience }
  ↓
Automatic RAG query to Knowledge Base
  → OpenSearch vector search over brand-guidelines/ + regional-trends/
  → Top-k chunks prepended to agent context window
  ↓
Calls CreativeStrategy action group → Lambda 3
  → Returns: image_prompt + localized ad_copy
  ↓
Calls ComplianceCheck action group → Lambda 3
  → Applies Bedrock Guardrails to ad_copy
  → IF FAIL: agent revises copy and retries (up to 3 attempts)
  ↓
Returns structured creative package to Lambda 2
```

The agent instruction (`agent.txt`) is the system prompt. It defines the exact workflow sequence, output format, tone rules, compliance hard stops, and image prompt guidelines. It is version-controlled in the repository.

### Knowledge Base (RAG)

```
Vector store:  OpenSearch Serverless (VECTORSEARCH collection)
Index:         knn_vector, dimension 1024, engine faiss, space_type l2
Embedding:     amazon.titan-embed-text-v2:0 (must match index dimension)
```

**Two data sources on the same Knowledge Base:**

| Data Source | S3 Prefix | Contents |
|-------------|-----------|---------|
| Brand Guidelines | `brand-guidelines/` | `brand_guidelines.md`, `marketing_voice.md` |
| Regional Trends | `regional-trends/` | `brazil.md`, `japan.md`, `usa.md`, `germany.md`, `mexico.md`, `legal_constraints.md`, `*_learnings.md` (auto-written by Lambda 6) |

One KB means one vector search retrieves relevant chunks from both sources simultaneously. Bedrock ranks all chunks by relevance — no manual result merging needed.

### Guardrails

One guardrail applied globally to the agent and Lambda 3.

```
Content Filter:    HATE, VIOLENCE, SEXUAL — all HIGH strength (input + output)

Word Filter:       guaranteed, clinically proven, miracle,
(blocked terms)    instant results, 100% effective, best in world

Topic Denial:      competitor brand mentions
                   medical claims
                   financial guarantees
```

If a guardrail blocks output: Lambda 3 returns a `FAIL` compliance item. The agent revises the copy and retries. After 3 failures the campaign status is set to `failed` with `failure_reason: "compliance hard fail after 3 revision attempts"` stored in DynamoDB.

### Image Processing (Pillow)

After Nova Canvas returns a base64 PNG:

```
1. Decode base64 → PIL Image object
2. Generate at 1:1 (square) — best median aspect ratio for cropping
3. Resize/crop to 9:16  — crop center to portrait
4. Resize/crop to 16:9  — crop center to landscape
5. For each ratio:
     Load ad_copy (headline + CTA)
     Select bundled font from Lambda layer
     Calculate text position (bottom third of image)
     Add semi-transparent background strip
     Render text with anti-aliasing
6. Save as PNG with metadata
7. Upload to S3 (check if file already exists for idempotency)
```

Pillow is packaged as a Lambda layer (`layers/pillow.zip`). Build the layer with architecture-pinned pip:

```bash
# For arm64 Lambda (Lambda 2 uses Graviton2):
pip install Pillow --platform manylinux2014_aarch64 --target python/ --only-binary=:all:
zip -r modules/lambda/layers/pillow.zip python/

# For x86_64 Lambda (if not using arm64):
pip install Pillow --platform manylinux2014_x86_64 --target python/ --only-binary=:all:
zip -r modules/lambda/layers/pillow.zip python/
```

> **Do NOT run bare `pip install Pillow --target python/`** on macOS. This produces a macOS ARM binary that will fail on Lambda's Linux runtime.

---

## 11. Deep Dive — Analytics & Feedback Loop

### Analytics Pipeline

Lambda 2 emits a JSON event to Kinesis Firehose after each successful generation. Lambda 7 emits an event after each approval/rejection. These are the **only** two ingestion points — no DynamoDB Streams duplication.

**Generation event payload (Lambda 2):**
```json
{
  "event_type": "generation",
  "campaign_id": "...",
  "product_name": "Dove Shampoo",
  "region": "brazil",
  "generation_time_ms": 42300,
  "cost_usd": 0.51,
  "input_tokens": 1842,
  "output_tokens": 487,
  "nova_canvas_calls": 3,
  "compliance_pass": 2,
  "compliance_warn": 1,
  "compliance_fail": 0,
  "approval_status": "pending_review",
  "created_at": "2025-04-03T10:22:00Z"
}
```

**Approval event payload (Lambda 7):**
```json
{
  "event_type": "approval",
  "campaign_id": "...",
  "product_name": "Dove Shampoo",
  "region": "brazil",
  "approval_status": "approved",
  "reviewed_by": "jane@company.com",
  "reviewed_at": "2025-04-03T14:10:00Z"
}
```

Kinesis Firehose buffers events (60s or 5 MB), converts JSON → **Parquet** using the Glue table schema, then writes to:
```
s3://campaignx-analytics/events/year=2025/month=04/day=03/
```

Glue Catalog provides the schema with **partition projection** enabled. Athena reads directly over S3 partitions — no ETL, no database server, no `MSCK REPAIR TABLE`.

> **No DynamoDB Streams:** The v1 design mentioned DynamoDB Streams feeding into Firehose. This has been removed to avoid duplicate events. Lambda 2 and Lambda 7 write directly to Firehose with all necessary context. This is simpler and avoids the need for a Streams-processing Lambda.

### Feedback Loop (Lambda 6)

Runs every day at midnight via EventBridge cron.

```
1. Query Athena — last 30 days of events, grouped by region
   Compute: avg compliance_fail, most common fail reasons,
            avg pass rate, volume

2. For each region with > 10 campaigns:
   Generate a learnings markdown doc
   e.g. "Brazil campaigns fail compliance when using 'garantido' —
         use 'confiável' instead"

3. Write {region}_learnings.md to S3 RAG bucket:
   s3://campaignx-rag-docs/regional-trends/

4. Call Bedrock StartIngestionJob — re-index both data sources

5. Future campaigns for that region retrieve the learnings via RAG
```

Every future campaign for that region now benefits from the learned patterns. Quality improves daily without human curation or model retraining.

### Cost Tracking

Lambda 2 calculates `estimated_cost_usd` per campaign:

```python
nova_canvas_cost = nova_canvas_calls * 0.08
llm_cost = (input_tokens / 1_000_000 * 3.00) + (output_tokens / 1_000_000 * 15.00)
total_cost = nova_canvas_cost + llm_cost
```

This is stored in DynamoDB, emitted to Firehose, aggregated by Athena, and surfaced in `GET /insights` — directly addressing the business goal of measuring ROI per region and market.

---

## 12. Deep Dive — Approval Workflow

### State Machine

```
status (campaign generation lifecycle):
  pending        → record created, awaiting SQS
  generating     → Lambda 2 in progress (set via conditional write)
  complete       → images saved, text overlaid
  failed         → generation error or compliance hard fail
                   (failure_reason stored in DynamoDB)

approval_status (review lifecycle, set only after status = complete):
  (not set)      → campaign still generating or failed
  pending_review → default after generation completes successfully
  approved       → reviewer approved via Canvas UI
  rejected       → reviewer rejected, notes recorded
```

These are two **separate** fields. A campaign can be `status=complete` and `approval_status=rejected` — generated successfully but rejected by the reviewer for creative reasons. A campaign with `status=failed` will never have `approval_status` set.

### Notification

Lambda 7 publishes to SNS after every approval state change:
```
Subject: [CampaignX] Campaign Ready for Review
Body:    Campaign {id} for {product} / {region}
         Status: pending_review
         Review at: {canvas_url}
```

### GSI Usage

The `status-created-index` GSI on DynamoDB enables:
```
Query all campaigns WHERE approval_status = "pending_review"
      ORDER BY created_at DESC
      LIMIT 20
```
This powers a reviewer dashboard without requiring a full table scan. The sort key (`created_at`) enables chronological ordering and pagination. Without the GSI, finding all pending reviews would be O(n) over the entire table.

The GSI is **sparse** — items without `approval_status` (i.e., campaigns still generating or failed) are automatically excluded from the index. This is the desired behavior.

---

## 13. Infrastructure as Code

### Terraform Structure

```
campaignx-infra/
├── env/
│   ├── dev/
│   │   ├── dev.tf          → calls module "campaignx" {}
│   │   ├── locals.tf       → ALL config lives here as maps
│   │   ├── outputs.tf
│   │   ├── providers.tf
│   │   └── variables.tf
│   ├── staging/
│   └── prod/
├── infrastructure/
│   ├── main.tf             ← module calls + wiring (the glue)
│   ├── outputs.tf
│   └── variables.tf
└── modules/
    ├── iam/                → roles + policies for all services
    ├── storage/            → 4 S3 buckets (CORS, versioning, SSE)
    ├── dynamodb/           → CampaignTable + GSI + TTL
    ├── bedrock/            → OpenSearch + KB + Agent + 2 data sources
    ├── guardrails/         → content filter + word filter + topic deny
    ├── lambda/             → for_each map of all 7 functions + Pillow layer
    ├── api_gateway/        → REST API v1 + 6 routes + CORS + API key
    ├── sqs/                → campaign-gen queue + DLQ + DLQ alarm
    ├── sns/                → campaign-approvals topic + email subscription
    ├── analytics/          → Kinesis Firehose (Parquet) + Glue (partition projection) + Athena workgroup
    └── scheduler/          → EventBridge cron (daily) → Lambda 6
```

### Key Patterns

**1. `enable_ai_engine` flag:**
```hcl
for_each = var.enable_ai_engine ? { "enabled" = true } : {}
```
Allows provisioning infrastructure without Bedrock — useful for testing API Gateway and Lambda in isolation before requesting model access.

**2. Lambda `for_each` map:**
All 7 Lambda functions defined as a single map in `locals.tf`. One module call creates all of them. Adding a new Lambda means adding one block to `locals.tf` only — `infrastructure/main.tf` never changes.

**3. Lambda 2 SQS event source `maxConcurrency`:**
```hcl
resource "aws_lambda_event_source_mapping" "sqs_trigger" {
  function_name    = aws_lambda_function.generate_campaign.arn
  event_source_arn = var.sqs_queue_arn
  scaling_config {
    maximum_concurrency = 10
  }
}
```
This caps parallel Lambda 2 invocations at 10, preventing Bedrock throttling.

**4. `time_sleep` after IAM (60s):**
IAM role creation to global policy consistency takes up to 60 seconds in AWS. Bedrock KB and OpenSearch both fail silently if policies aren't propagated. `time_sleep` is the industry-standard fix.

**5. All config in `locals.tf`:**
S3 buckets, IAM roles, Lambda configs, guardrail words — all defined as maps in `env/dev/locals.tf`. The same `infrastructure/main.tf` is used unchanged across dev, staging, and prod.

**6. DLQ CloudWatch Alarm:**
```hcl
resource "aws_cloudwatch_metric_alarm" "dlq_alarm" {
  alarm_name          = "${var.project_name}-${var.environment}-dlq-messages"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Sum"
  threshold           = 0
  alarm_actions       = [var.sns_topic_arn]
  dimensions = {
    QueueName = var.dlq_name
  }
}
```

### Provider Requirements

```hcl
hashicorp/aws                  >= 5.56.0  # required for aws_bedrockagent_*
opensearch-project/opensearch  >= 2.2.0
hashicorp/time                 >= 0.9.0
```

### Build Order (Dependency Sequence)

| Step | Module | Depends on |
|------|--------|-----------|
| 1 | S3 buckets | nothing |
| 2 | DynamoDB | nothing |
| 3 | SQS + DLQ | nothing |
| 4 | SNS | nothing |
| 5 | IAM roles | S3 ARNs, DynamoDB ARN, SQS ARN |
| 6 | `time_sleep` 60s | IAM |
| 7 | Analytics (Firehose/Glue) | IAM (firehose role), S3, Glue table schema |
| 8 | Guardrails | nothing |
| 9 | Bedrock (OSS + KB + Agent) | IAM, S3, `time_sleep` |
| 10 | Lambda functions (all 7) | IAM, all env var sources |
| 11 | SQS → Lambda trigger (maxConcurrency: 10) | SQS + Lambda 2 |
| 12 | DLQ CloudWatch Alarm | DLQ + SNS |
| 13 | API Gateway (REST v1 + API key) | Lambda ARNs |
| 14 | Scheduler (EventBridge, daily) | Lambda 6 ARN |

Terraform resolves this dependency graph from a single `terraform apply` via `depends_on` and implicit references.

---

## 14. How to Recreate From Scratch

### Prerequisites

- AWS account with Bedrock model access granted for:
  - `anthropic.claude-3-5-sonnet-20241022-v2:0`
  - `amazon.nova-canvas-v1:0`
  - `amazon.titan-embed-text-v2:0`
  - *(Request via AWS Console → Bedrock → Model access)*
- Bedrock service quota: request increase for Claude Sonnet concurrent invocations (minimum 10)
- AWS CLI configured: `aws configure`
- Terraform >= 1.6.0
- Bun: `curl -fsSL https://bun.sh/install | bash`

### Step 1: Create Terraform State Bucket

```bash
aws s3 mb s3://campaignx-terraform-state-dev --region us-east-1
```

### Step 2: Apply Infrastructure

```bash
cd campaignx-infra/env/dev
terraform init
terraform plan
terraform apply
```

On first apply, SNS sends a subscription confirmation email. Click the confirm link before reviewers can receive notifications.

Note the outputs:
- `api_gateway_url` → copy to frontend `.env`
- `api_key_value` → copy to frontend `.env`
- `campaign_table_name` → for reference
- `agent_id` → for reference

### Step 3: Upload RAG Documents

```bash
aws s3 cp docs/brand_guidelines.md s3://campaignx-dev-rag-docs/brand-guidelines/
aws s3 cp docs/marketing_voice.md  s3://campaignx-dev-rag-docs/brand-guidelines/
aws s3 cp docs/brazil.md           s3://campaignx-dev-rag-docs/regional-trends/
aws s3 cp docs/japan.md            s3://campaignx-dev-rag-docs/regional-trends/
# repeat for each market

# Trigger initial Knowledge Base sync
aws bedrock-agent start-ingestion-job \
  --knowledge-base-id <kb_id_from_terraform_output> \
  --data-source-id <brand_guidelines_ds_id>
```

### Step 4: Build Pillow Layer

```bash
mkdir python

# For arm64 Lambda 2 (Graviton2):
pip install Pillow --platform manylinux2014_aarch64 --target python/ --only-binary=:all:

zip -r modules/lambda/layers/pillow.zip python/
```

> **Important:** Do NOT run `pip install Pillow --target python/` on macOS. This produces a macOS ARM binary incompatible with Lambda's Linux runtime. Always use `--platform` and `--only-binary` flags.

Terraform references this zip in `modules/lambda/main.tf`.

### Step 5: Frontend Setup

```bash
cd campaignx
bun install
```

Create `.env.local`:
```
VITE_API_BASE_URL=https://{api_id}.execute-api.us-east-1.amazonaws.com/{stage}
VITE_API_KEY={api_key_value_from_terraform_output}
```

```bash
bun dev    # local development
bun build  # production build
```

### Step 6: Connect Frontend to API

In `src/hooks/useCampaign.ts`, replace `mockGenerateCampaign()` with:
```ts
await api.submitBrief(brief)        // POST /brief
await api.pollCampaign(campaignId)  // GET /campaigns/{id}
```

In `src/api.ts`, include the API key header:
```ts
const headers = {
  'Content-Type': 'application/json',
  'x-api-key': import.meta.env.VITE_API_KEY,
};
```

No UI components need to change.

### Step 7: Deploy Frontend

**Option A — Vercel or Netlify (recommended for POC):**
Push to GitHub, connect repo, set `VITE_API_BASE_URL` and `VITE_API_KEY` environment variables.

**Option B — S3 + CloudFront (recommended for prod):**
```bash
bun build
aws s3 sync dist/ s3://campaignx-dev-frontend/
# Configure CloudFront distribution separately
```

### Step 8: Verify End-to-End

```
1.  Submit a brief from the frontend
2.  DynamoDB: status → "generating" (via conditional write)
3.  SQS: message appears and is consumed
4.  CloudWatch Logs: /aws/lambda/campaignx-dev-generate-campaign
5.  S3 outputs bucket: 6 images present
6.  DynamoDB: status → "complete", approval_status → "pending_review"
7.  Canvas: renders with generated images
8.  Approve the campaign, verify SNS email notification
9.  S3 analytics bucket: Firehose Parquet files present
10. GET /insights: analytics data returned
11. Submit same brief again: verify idempotency (no duplicate generation)
12. Check DLQ: should be empty (no failed messages)
```

---

## 15. Key Design Decisions & Trade-offs

### Decision 1: SQS vs Direct Lambda Invocation

| | Choice |
|---|---|
| **Chose** | SQS queue between Lambda 1 and Lambda 2 |
| **Alternative** | Lambda 1 invokes Lambda 2 asynchronously |
| **Reason** | SQS provides built-in retry (3× before DLQ), visibility timeout prevents duplicate processing, and `maxConcurrency` on the event source mapping caps parallel invocations at 10 to prevent Bedrock throttling. Direct async invocation requires managing failure states manually and offers no built-in backpressure. |

### Decision 2: One Bedrock Agent vs Multiple Agents

| | Choice |
|---|---|
| **Chose** | One agent with 2 action groups |
| **Alternative** | Separate Creative agent + Compliance agent |
| **Reason** | Multi-agent coordination adds latency and Terraform complexity with no benefit at POC scale. One agent handles creative strategy and compliance sequentially. The `agent.txt` instruction file defines the exact workflow. Upgrade to multi-agent only if the context window becomes a bottleneck. |

### Decision 3: DynamoDB vs RDS

| | Choice |
|---|---|
| **Chose** | DynamoDB (pay-per-request) |
| **Alternative** | Aurora Serverless PostgreSQL |
| **Reason** | Campaign data is accessed by primary key 99% of the time. DynamoDB delivers microsecond reads for this pattern with no joins required. Pay-per-request means zero cost at idle. Aurora's minimum cost is ~$50/month even at zero load. |

### Decision 4: Polling vs WebSockets

| | Choice |
|---|---|
| **Chose** | Frontend polling every 3s |
| **Alternative** | API Gateway WebSocket + Lambda push |
| **Reason** | Generation takes 1–5 minutes. Polling at 3s costs ~100 API calls per campaign — negligible. WebSockets require connection management, reconnection logic, a connection table in DynamoDB, and significantly more infrastructure. The UX difference is imperceptible to users. |

### Decision 5: Kinesis Firehose vs Direct S3 Writes

| | Choice |
|---|---|
| **Chose** | Kinesis Data Firehose with Parquet conversion |
| **Alternative** | Lambda 2 writes JSON directly to S3 |
| **Reason** | Direct S3 writes create thousands of tiny files, which destroys Athena query performance. Firehose handles batching, Parquet conversion, and date partitioning automatically. Parquet is 5–10x faster for Athena queries than GZIP JSON. Firehose also provides a retry buffer — events are not lost if S3 is temporarily unavailable. |

### Decision 6: Two Data Sources vs Two Knowledge Bases

| | Choice |
|---|---|
| **Chose** | One KB with two S3 data sources (different prefixes) |
| **Alternative** | Separate KB for brand guidelines vs regional trends |
| **Reason** | One KB means a single vector search retrieves relevant chunks from both sources simultaneously. Bedrock ranks all chunks by relevance regardless of source. Two KBs would require two separate retrieval calls and manual result merging — more complex with no quality benefit. |

### Decision 7: Self-Updating RAG vs Fine-tuning

| | Choice |
|---|---|
| **Chose** | Lambda 6 writes learnings back to RAG S3 daily |
| **Alternative** | Fine-tune Claude or Nova on successful campaigns |
| **Reason** | Fine-tuning costs thousands of dollars, takes days, and requires labeled datasets. RAG updates are free (S3 writes), near-instant (next KB sync), and reversible (delete the file). The quality improvement from RAG-based learning is sufficient for this use case. Daily sync (vs weekly in v1) provides faster learning loops. Fine-tuning is a Phase 2 consideration. |

### Decision 8: REST API v1 vs HTTP API v2

| | Choice |
|---|---|
| **Chose** | REST API v1 |
| **Alternative** | HTTP API v2 |
| **Reason** | REST API v1 supports native API key authentication via usage plans without requiring a Lambda authorizer. HTTP v2 does not support API keys natively. Trade-off: REST v1 is ~3.5x more expensive per million requests ($3.50 vs $1.00) and requires manual OPTIONS methods for CORS. At POC scale (~100K requests/month), the cost difference is ~$0.25/month — negligible. |

### Decision 9: Direct Firehose vs DynamoDB Streams

| | Choice |
|---|---|
| **Chose** | Lambda 2 and Lambda 7 write directly to Firehose |
| **Alternative** | Enable DynamoDB Streams → Lambda → Firehose |
| **Reason** | Direct writes are simpler and avoid duplicate events. The Lambdas already have all the context needed for the analytics payload. DynamoDB Streams would add a processing Lambda, increase cost, and risk duplicating events (every DynamoDB write triggers a stream event). If we later need to capture ALL DynamoDB mutations for audit purposes, Streams can be added as a separate concern. |

### Decision 10: Titan Embed v2 vs Nova Embed v1

| | Choice |
|---|---|
| **Chose** | Amazon Titan Embed Text v2 (`amazon.titan-embed-text-v2:0`) |
| **Alternative** | Amazon Nova Embed (`amazon.nova-embed-text-v1`) |
| **Reason** | Titan Embed v2 is more mature, has configurable dimension sizes (256/512/1024), and is widely documented. Configurable dimensions allow cost optimization in the future — reduce to 512 or 256 dims if retrieval quality is sufficient, halving OpenSearch storage and query cost. |

---

## 16. Known Limitations

These are accepted constraints for the POC. They do not block implementation but should be understood by anyone building or operating the system.

### 16.1 Bedrock Agent Iteration Control

The design specifies "up to 3 compliance retry attempts" when the Guardrail rejects ad copy. However, Bedrock Agents do not enforce a strict iteration count by default — the LLM decides when to stop retrying.

**Risk:** The agent could loop more than 3 times, burning tokens and extending generation time. In extreme cases it could hit the Lambda 2 timeout (300s).

**Mitigation (must implement):**
- Set `maximumIterations` in the Bedrock Agent Terraform config (e.g., `max_iterations = 5` — allows 3 compliance retries + 2 for normal flow)
- Inside Lambda 3 (CheckCompliance): maintain an invocation counter in the event payload. If `invocation_count >= 3`, return a hard `FAIL` with `"max retries exceeded"` regardless of Guardrail output. This forces the agent to stop.
- Lambda 2 should check if the agent's response contains a hard fail and set `status: "failed"` + `failure_reason` in DynamoDB accordingly.

### 16.2 Athena Query Latency on Cache Miss

Lambda 5 (GetInsights) caches Athena results in DynamoDB with a 1-hour TTL. On a cache miss, Athena queries take **5–10 seconds** to execute — this is inherent to Athena's serverless architecture (query planning + S3 scan).

**Impact:** The first Insights page load per hour will feel slow. Subsequent loads within that hour will be near-instant (DynamoDB read).

**This is acceptable for POC.** Users load the Insights dashboard infrequently, and 5–10s on first load is tolerable. A loading spinner in the frontend is sufficient.

### 16.3 Lambda 2 Memory for High-Resolution Images

Lambda 2 is configured at 1024 MB. Pillow loads images as uncompressed bitmaps in memory. A 2048×2048 PNG consumes ~16 MB in RAM per image. Processing 6 images simultaneously uses ~96 MB — well within the 1024 MB limit.

**Risk:** If Nova Canvas output resolution increases beyond 2048×2048 in future model versions, or if campaigns grow beyond 2 products (e.g., 5 products × 3 ratios = 15 images), memory usage could approach the limit.

**Mitigation:** Monitor Lambda 2 memory usage via CloudWatch `MaxMemoryUsed` metric. If it exceeds 800 MB consistently, bump to 2048 MB in `locals.tf` (one-line change).

### 16.4 Presigned URL Expiry

Lambda 4 generates S3 presigned URLs for image display in the frontend. These URLs expire after a configurable duration (default: 1 hour). If a reviewer leaves the Canvas tab open for longer than the expiry period, images will fail to load.

**Mitigation:** Set presigned URL expiry to 24 hours (sufficient for review workflows). The frontend can detect `403` responses on image loads and re-fetch the campaign to get fresh URLs.

---

## 17. Future Improvements

These are out of scope for the POC but should be considered for production readiness.

| Priority | Improvement | Rationale |
|----------|-------------|-----------|
| **P1** | **Cognito authentication** | Replace API key auth with JWT-based user auth. Enables per-user permissions, reviewer identity verification, and audit trails. |
| **P1** | **CloudFront for image delivery** | Replace presigned URLs with CloudFront + OAI. Provides edge caching, eliminates URL expiry issues, and reduces S3 costs at scale. |
| **P1** | **Structured logging + X-Ray tracing** | Add AWS X-Ray to all Lambdas for end-to-end request tracing. Critical for debugging generation failures across the multi-service pipeline. |
| **P2** | **Step Functions for orchestration** | Replace Lambda 2's monolithic pipeline with Step Functions. Each step (Bedrock call, Nova Canvas, Pillow, S3 upload) becomes a separate state. Enables partial retries, visual debugging, and cleaner error handling. |
| **P2** | **Multi-product parallelism** | Currently Lambda 2 processes products sequentially within a campaign. For campaigns with 5+ products, process each product in parallel (e.g., SQS message per product, not per campaign). |
| **P2** | **WAF on API Gateway** | Add AWS WAF rules to rate-limit requests, block suspicious IPs, and prevent abuse of the batch endpoint. |
| **P3** | **Ad platform integration** | Publish approved assets directly to Meta Ads, TikTok Ads, and Google Ads via their APIs. Requires OAuth integration per platform. |
| **P3** | **A/B testing of creatives** | Generate 2–3 creative variants per brief, publish all, and ingest platform performance data (CTR, conversions) to determine winners. Feed results back into the RAG pipeline. |
| **P3** | **Aurora Serverless for complex queries** | If analytics needs grow beyond what Athena + DynamoDB can serve (e.g., JOINs, real-time dashboards), migrate to Aurora Serverless v2 with a read replica for analytics. |
| **P3** | **Fine-tuning** | Once sufficient approved campaigns exist (~1,000+), fine-tune the LLM on successful creative patterns. This would complement RAG with learned style preferences. |

---

*End of document — v2, revised 2026-03-07*
