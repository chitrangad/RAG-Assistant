# specs.md — Living Requirements Specification

Created: 2026-07-28  
Last Updated: 2026-07-31 — Admin API implemented; live ingestion progress; path-edit fix

## 1. Product Name

Project Knowledge & Requirement Traceability Assistant

## 2. Goal

Build a team-facing Project Knowledge Assistant that enables technical teams, engineering managers, and leadership to retrieve project knowledge from project artifacts in the fewest possible steps using grounded answers and verifiable citations.

## 3. Core Decision Supported

Help users confidently answer project-related questions using evidence from project artifacts without manually searching repositories, documents, emails, meeting notes, or source code.

## 4. Revised Architecture

### 4.1 High-Level Flow

```
User asks question in AI Chat (Copilot / Gemini / ChatGPT / ...)
  → Browser Extension detects provider based on URL
  → Extension calls local Python RAG Backend (localhost:8000)
  → Backend retrieves evidence from SQLite Catalog + ChromaDB
  → Backend returns ranked evidence package with confidence scores
  → Extension formats grounding prompt per provider's conventions
  → Extension injects prompt into chat input and submits
  → AI (cloud) synthesizes final answer from provided evidence
  → User sees cited, grounded answer
```

### 4.2 Architecture Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                    USER'S LAPTOP                              │
│                                                               │
│  ┌──────────────────────┐    ┌────────────────────────────┐  │
│  │ AI Chat (any of:)    │◄───│ Browser Extension          │  │
│  │                      │    │  (Chrome/Edge, Manifest V3)│  │
│  │  • Copilot (work)    │    │                            │  │
│  │  • Gemini (personal) │    │  - Detects provider by URL │  │
│  │  • ChatGPT (future)  │    │  - Intercepts query        │  │
│  │  • Claude (future)   │    │  - Calls RAG backend       │  │
│  │                      │    │  - Formats prompt per AI   │  │
│  │  Reasoning Layer     │    │  - Injects + submits       │  │
│  └──────────────────────┘    └─────────────┬──────────────┘  │
│                                            │                 │
│                                     localhost:8000            │
│                                            │                 │
│  ┌─────────────────────────────────────────▼──────────────┐  │
│  │              Python RAG Backend (FastAPI)               │  │
│  │                                                        │  │
│  │  ┌──────────┐ ┌───────────┐ ┌──────────────────────┐  │  │
│  │  │Ingestion │ │Retrieval  │ │ Answer Construction   │  │  │
│  │  │ Pipeline │ │ Engine    │ │ + Citation Builder    │  │  │
│  │  └────┬─────┘ └─────┬─────┘ └──────────┬───────────┘  │  │
│  │       │             │                  │               │  │
│  │  ┌────▼─────────────▼──────────────────▼───────────┐   │  │
│  │  │     SQLite Catalog    │    ChromaDB Vector DB    │   │  │
│  │  └──────────────────────┴──────────────────────────┘   │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

### 4.3 Responsibility Split

| Layer | Owns | Does NOT Own |
|---|---|---|
| **Browser Extension** | Query interception, provider detection, prompt formatting per AI, prompt injection, user-facing UX, provider selection settings | Retrieval, ranking, evidence decisions, final answer synthesis |
| **Python RAG Backend** | Ingestion, metadata extraction, project resolution, retrieval, ranking, confidence scoring, citation construction, insufficient-evidence enforcement | Final answer synthesis, AI provider logic |
| **AI Provider** (Copilot / Gemini / etc.) | Natural language reasoning, final answer formatting, multi-turn conversation | Facts, project names, requirement IDs, dates (must come from evidence) |

### 4.4 Key Design Decisions

| Decision ID | Decision | Rationale |
|---|---|---|
| D-001 | Python (FastAPI) over Node.js | Better ML/AI ecosystem, async-native, Pydantic validation |
| D-002 | Browser Extension over standalone app | Seamless UX within AI chat interfaces, no manual copy-paste |
| D-007 | Multi-provider support (Copilot, Gemini, etc.) | Dev on personal laptop (Gemini), deploy to work laptop (Copilot). Extension is provider-agnostic; user picks AI in settings. |
| D-003 | Local-first deployment | MVP runs entirely on laptop; SQLite + ChromaDB are local |
| D-004 | Local embedding model (all-MiniLM-L6-v2) | Free, no internet dependency, runs easily on Dell 5450 |
| D-005 | Copilot as reasoning layer only | Corporate mandate; all facts come from our RAG pipeline |
| D-006 | SQLite catalog + ChromaDB vector store | SQLite = authoritative traceability; Chroma = semantic accelerator |

## 5. Tech Stack

| Component | Choice | Rationale |
|---|---|---|
| Language | Python 3.11+ | Rich ML/NLP ecosystem |
| Web Framework | FastAPI | Async-native, auto OpenAPI docs, Pydantic integration |
| ORM | SQLAlchemy 2.0 + Alembic | Mature, async support, migrations |
| Validation | Pydantic v2 | FastAPI-native, fast, strict typing |
| Catalog DB | SQLite (via aiosqlite) | Zero-config, local, perfect for traceability |
| Vector DB | ChromaDB | Local, Python-native, persistent mode |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) | 80MB, CPU-friendly, 384-dim vectors |
| Doc Extraction | python-docx, PyMuPDF, built-in | Standard, well-tested Python libraries |
| Logging | structlog | Structured, async-friendly |
| Testing | pytest + pytest-asyncio | Standard Python testing with async support |
| Browser Extension | TypeScript, Manifest V3 | Chrome/Edge compatible |

## 6. Functional Requirements

### FR-001 — Natural Language Query
Users can ask project-related questions in natural language via Copilot.

### FR-002 — Requirement Discovery
Users can ask which project implemented a requirement or business capability.

### FR-003 — Ranked Project Matches
If multiple projects match, the assistant returns all relevant matches ranked by relevance.

### FR-004 — Project Summary
Users can request a concise project summary.

### FR-005 — Requirement Traceability
Users can identify which document supports a requirement.

### FR-006 — Change Request Discovery
Users can ask what change request introduced a project feature or requirement.

### FR-007 — Artifact Discovery
Users can ask where the latest artifacts are saved when that information exists in source evidence.

### FR-008 — Evidence-Visible Responses
Responses must include answer, confidence, evidence summary, citations, and alternative matches when applicable.

### FR-009 — Insufficient Evidence Response
If evidence is insufficient, the assistant must not invent an answer.
Required response: "I do not have enough evidence to answer this question."

### FR-010 — Existing Document Support
The system must support mostly structured existing project documents that do not use a standard registration template.

### FR-011 — Metadata Extraction
The ingestion pipeline must extract metadata such as project names, requirements, change requests, artifacts, repositories, implementation dates, and contributors when present.

### FR-012 — Admin Metadata Enrichment
Administrators can correct or enrich extracted metadata.

### FR-013 — Multi-Provider AI Integration
Users interact through their choice of AI chat interface (Microsoft 365 Copilot, Google Gemini, etc.) via the browser extension. The extension detects the provider and adapts prompt formatting accordingly.

### FR-014 — Provider Selection
Users can select their preferred AI provider in the extension settings. The RAG backend is provider-agnostic and returns the same evidence package regardless of which AI is used.

### FR-015 — User Identity
Each user uses their own Microsoft 365 identity and Copilot entitlement.

### FR-015 — Source Registration
Administrators can register multiple sources.

### FR-016 — Source Removal
Administrators can disable or remove sources while retaining audit and ingestion history.

### FR-017 — Source Reindexing
Administrators can trigger reindexing for a source.

### FR-018 — Source Health
Administrators can view source status and indexing health.

### FR-019 — Source Traceability
Every ingested document must retain its originating source.

## 7. Supported MVP Sources

- Local folder
- Document upload
- Network folder
- SharePoint (best-effort without admin; may require manual download)

## 8. Data Model (SQLite Catalog)

### Core Tables

```
projects              — Project registry (name, description, dates, team)
project_aliases       — Alternative names for projects
documents             — Ingested document registry
project_documents     — Project-to-document links
requirements          — Extracted requirement IDs and descriptions
project_requirements  — Project-to-requirement links
change_requests       — Extracted CR IDs and details
project_change_requests — Project-to-CR links
artifacts             — Discovered artifacts (repos, files, URLs)
project_artifacts     — Project-to-artifact links
evidence_links        — Links between claims and source document chunks
metadata_reviews      — Admin corrections to extracted metadata
document_chunks       — Chunked document segments for embedding
data_sources          — Registered data sources and their config
source_documents      — Source-to-document mappings
ingestion_runs        — Ingestion job tracking and status
query_audit           — Query logging for analysis
```

### Ranking Weights

| Match Type | Weight |
|---|---|
| Requirement Match | 50 |
| Project Name Match | 40 |
| Change Request Match | 20 |
| Architecture / Design Match | 15 |
| Runbook Match | 10 |
| Test Evidence Match | 10 |
| Artifact Match | 10 |
| Meeting Notes Match | 5 |
| Status Report Match | 5 |
| Email Export Match | 3 |
| Weak Reference | 1 |

## 9. Non-Functional Requirements

- Every factual claim must be supported by citation evidence.
- The assistant must not invent projects, requirements, dates, owners, CR numbers, or artifact locations.
- The API must capture user identity and query metadata for future auditing.
- The browser extension must not interfere with normal Copilot usage.
- The system should gracefully handle offline/cold-start scenarios.
- The system should support future integrations (Azure DevOps, Jira, Git, email exports).

## 10. Implementation Buckets

### Bucket 1 — Foundation (Python FastAPI)
- Project scaffolding (poetry/pip, directory structure)
- FastAPI application bootstrap
- SQLAlchemy 2.0 async models (all 15+ tables)
- Alembic migrations
- SQLite initialization
- Health and readiness endpoints
- Configuration management (pydantic-settings)
- Structured logging (structlog)
- Request ID middleware
- Error handling middleware

### Bucket 2 — Ingestion Framework
- Source connector abstraction (protocol/ABC)
- Local folder connector
- Document upload connector
- Network folder connector (scaffold)
- SharePoint connector (best-effort)
- Text extraction (DOCX, PDF, MD, TXT)
- Metadata extraction (deterministic)
- Project resolution
- Document chunking (1000 char, 200 overlap)
- Embedding generation (sentence-transformers)
- ChromaDB indexing
- Ingestion run tracking

### Bucket 3 — Retrieval & Answer Engine
- Intent detection service
- Entity extraction service
- Dual retrieval (catalog + vector)
- Evidence aggregation service
- Project ranking service
- Confidence scoring service
- Citation builder service
- Answer builder service
- `/api/chat/query` endpoint
- Insufficient-evidence enforcement

### Bucket 4 — Admin API
- Source CRUD endpoints
- Source status and health
- Reindexing trigger
- Metadata review/enrichment
- Document management
- Ingestion run history

### Bucket 5 — Browser Extension
- Manifest V3 setup
- **Provider adapter system**: pluggable adapters per AI (Copilot, Gemini, ChatGPT, Claude)
  - Each adapter defines: URL pattern, input/button DOM selectors, prompt template
- **Settings popup**: provider selection, backend URL config
- Content script for each supported provider
- Query interception logic
- API client (localhost:8000)
- Grounding prompt builder (per-provider formatting)
- Prompt injection into chat input
- Submit automation
- Status indicator / error handling

### Bucket 6 — Hardening
- Comprehensive error handling
- pytest test suite (unit + integration)
- Input validation hardening
- Logging and observability
- Local packaging / install script
- **INSTALL.md**: detailed migration steps for work laptop deployment
- README and developer docs

## 11. Prompt Guardrails (Injected by Extension)

Shared across all providers:

```
You are answering a project knowledge question. Use ONLY the evidence
provided below. Do not add facts, invent projects, infer requirements,
invent dates, or fabricate change requests.

If the evidence is marked INSUFFICIENT, respond with:
"I do not have enough evidence to answer this question."

Always cite the source document for each claim.
```

Provider-specific formatting is handled by each adapter (e.g., Copilot may
need explicit system/user message separation, Gemini may use a different
convention).

## 12. Change Log

| Date | Change | Decision |
|---|---|---|
| 2026-07-28 | Initial specification (generic RAG) | Approved |
| 2026-07-28 | Shifted to Project Knowledge Assistant | Approved |
| 2026-07-28 | Added Microsoft 365 Copilot as conversation layer | Approved |
| 2026-07-28 | Added Entra ID user authentication model | Approved |
| 2026-07-28 | Added multi-source administration | Approved |
| 2026-07-28 | Added ingestion, retrieval, answer, and Copilot buckets | Approved |
| 2026-07-30 | **MAJOR REVISION**: No admin access confirmed | Approved |
| 2026-07-30 | Switched from Node.js to Python (FastAPI) | Approved |
| 2026-07-30 | Switched Copilot integration to Browser Extension model | Approved |
| 2026-07-30 | Local-first deployment (laptop), grow to hosted | Approved |
| 2026-07-30 | Local embedding model (all-MiniLM-L6-v2) | Approved |
| 2026-07-30 | Standard Python doc extraction libs | Approved |
| 2026-07-30 | **Multi-provider extension**: Copilot, Gemini, future AIs | Approved |
| 2026-07-30 | Added INSTALL.md to hardening bucket for work laptop migration | Approved |
| 2026-07-31 | Bucket 4 Admin API implemented (source CRUD, test-connection, background scan, run history, health, data wipe) | Approved |
| 2026-07-31 | Scan runs as background task returning `202` + `run_id`; live per-document progress via `GET /api/admin/runs/{id}` (serves FR-017 reindexing/health) | Approved |
| 2026-07-31 | Fixed source path editing persistence (SQLAlchemy JSON in-place mutation — dict copy fix); both features user-verified live | Approved |
| 2026-07-31 | INSTALL.md created — installation/deployment guide incl. browser-extension distribution, systemd service, backup, Docker roadmap (next version) | Approved |
