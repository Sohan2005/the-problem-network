# The Problem Network

**Discover real-world software problems. Build projects that solve them.**

The Problem Network is a full-stack web application that transforms real software requests from Hacker News and Stack Exchange into structured, beginner-friendly development projects.

Instead of relying on generic project ideas, developers can explore problems that real people have encountered, discover relevant technologies, and follow actionable starting points to build practical portfolio projects.

[Explore the Live Application](https://the-problem-network.vercel.app/)

## Overview

Finding a meaningful software project can be surprisingly difficult.

Developers often struggle to identify projects that go beyond common tutorials, while online communities are filled with people describing problems they wish software could solve.

The Problem Network bridges that gap.

The application collects software-related requests from public discussion platforms, processes them using an AI-assisted extraction pipeline, and organizes them into actionable project briefs.

Each brief provides:

- **Problem Statement:** The real-world challenge that inspired the project.
- **Project Scope:** What a developer could build to address the problem.
- **Difficulty Level:** A classification to help developers find suitable challenges.
- **Recommended Tech Stack:** Suggested technologies for implementation.
- **Getting Started:** Practical steps for beginning development.
- **Learning Outcomes:** Skills and concepts developers can gain.
- **Original Source:** A link to the discussion that inspired the project, when available.

The result is a growing collection of practical project opportunities designed to connect learning with real-world software needs.

## Key Features

### Project Discovery

Browse a collection of development opportunities with tools designed to make finding relevant projects easier.

- **Full-Text Search:** Search across titles, descriptions, and technologies using case-insensitive, partial-word matching.
- **Technology Filtering:** Find projects by technology, including common aliases such as js/javascript and postgres/postgresql.
- **Difficulty Filtering and Sorting:** Browse projects according to their complexity.
- **Incremental Pagination:** Load projects in batches of 24 without losing access to older entries.
- **Saved Projects:** Bookmark interesting projects using browser-based storage.
- **Detailed Project Briefs:** Explore implementation suggestions, recommended stacks, learning outcomes, original discussions, and comments.
- **Light and Dark Themes:** Switch between visual themes.

### AI-Assisted Project Generation

The ingestion and processing workflow converts unstructured community discussions into standardized development briefs.

It combines:

- Public API ingestion from Hacker News and Stack Exchange.
- Early filtering to remove short or low-quality candidates.
- Structured information extraction using Google Gemini.
- Semantic duplicate detection using vector embeddings and cosine similarity.
- Automated quality gates that validate project structure, source relevance, content quality, and uniqueness.
- Quality scoring and scheduled publication of the best-scoring project briefs.

This separates content discovery and processing from public distribution, allowing only projects that pass the automated quality gates to become visible.

## Technology Stack

| Layer | Technologies |
|---|---|
| Frontend | Next.js 14, React 18, TypeScript, Tailwind CSS |
| Client State and Data Fetching | Zustand, TanStack React Query |
| UI Utilities | clsx, tailwind-merge |
| Backend | Python 3.11, FastAPI, Pydantic, SQLAlchemy 2, Uvicorn |
| Data Processing | NumPy, requests, psycopg2 |
| Database | PostgreSQL (Neon), pgvector |
| AI Processing | Google Gemini, Google GenAI SDK |
| Scheduling | Azure Functions |
| Backend Hosting | Azure App Service |
| Frontend Hosting | Vercel |
| Secret Management | Azure Key Vault |
| Community Discussion | giscus, GitHub Discussions |

**AI models**

- `gemini-3.5-flash-lite` — Structured project extraction.
- `gemini-embedding-001` — 3,072-dimensional vector embeddings for semantic comparison.

## System Architecture

The application uses a decoupled architecture that separates data ingestion, AI processing, publication, API delivery, and frontend presentation.

```mermaid
flowchart TD
    HN["Hacker News / Algolia API"]
    SE["Stack Exchange API"]
    TICK["Azure Functions: pipeline_tick (every 2 hours)"]
    ING["Ingestion and Prefiltering"]
    RAW[("PostgreSQL: raw_ideas")]
    PROC["AI Extraction"]
    GATES["Automated Quality Gates"]
    SCORE["Quality Scoring (0–100)"]
    FALLBACK["AI-Suggested Fallback"]
    PUB["Azure Functions: daily_publish (10:00 UTC)"]
    BRIEFS[("PostgreSQL: briefs + pgvector")]
    API["FastAPI: Cached Project Snapshot"]
    WEB["Next.js Frontend on Vercel"]
    COMMENTS["GitHub Discussions / giscus"]

    HN --> TICK
    SE --> TICK
    TICK --> ING
    ING --> RAW
    RAW --> PROC
    PROC --> GATES
    GATES --> SCORE
    SCORE --> PUB
    TICK -.-> FALLBACK
    FALLBACK -.-> RAW
    PUB --> BRIEFS
    BRIEFS --> API
    API --> WEB
    WEB --> COMMENTS
```

Ingestion, AI processing, quality validation, and publishing all run automatically in Azure Functions. The `pipeline_tick` workflow is enabled in production through `AUTOMATION_ENABLED=true`, and publication requires no manual approval. The legacy `daily_extraction` timer remains scheduled but does nothing while automation is enabled.

## Data Processing Pipeline

### 1. Source Ingestion

The `pipeline_tick` Azure Function runs every two hours:

`0 0 */2 * * *`

It retrieves candidate software requests from:

- **Hacker News:** Ask HN discussions accessed through the Algolia API.
- **Stack Exchange:** Questions retrieved from seven Stack Exchange sites through the Stack Exchange API.

The pipeline searches across a three-year window and stores retrieved candidates in the PostgreSQL `raw_ideas` table. It works through a bank of several hundred search phrases per source, newest posts first.

The legacy `daily_extraction` function remains scheduled at 09:00 UTC but does nothing while `AUTOMATION_ENABLED=true`.

### 2. AI Extraction and Validation

The automated pipeline prepares source material for conversion into structured project briefs.

The workflow:

- Removes short and noisy submissions before invoking an AI model.
- Uses Gemini to extract structured project information.
- Generates embeddings for semantic comparison.
- Passes extracted projects through automated quality gates.
- Scores qualifying projects for publication priority.

Filtering candidates before model inference helps avoid unnecessary API usage.

### 3. Automated Quality Gates

Every extracted project must pass a sequence of validation checks before becoming eligible for publication.

The gates run in the following order:

1. **Idea Validity:** Confirms that the idea represents a valid software project.
2. **Structure and Completeness:** Validates field lengths and counts and rejects placeholder content.
3. **Getting Started:** Requires actionable Getting Started text.
4. **Red Flags:** Rejects unsuitable submissions, including Show HN and Launch HN product pitches.
5. **Source Relevance:** Verifies sufficient overlap between the generated project and its original source.
6. **Duplicate Detection:** Rejects projects that duplicate a published posting or a better candidate using a 0.85 cosine-similarity threshold.

Projects that pass all gates receive a 0–100 quality score used to determine publication priority.

The thresholds were calibrated against the first 49 published postings. Automated tests cover every gate and its boundaries, duplicate detection, retries, and an end-to-end publishing workflow.

No manual approval is required.

### 4. Scheduled Publication

The `daily_publish` Azure Function runs at 10:00 UTC.

It:

- Publishes five qualifying projects per day, prioritizing the highest quality scores.
- Ranks real-source projects ahead of AI-suggested projects.
- Publishes at least three projects on Wednesday, Saturday, and Sunday when sufficient approved candidates are available.
- Publishes whatever is available and records the shortfall when fewer projects are ready.
- Prevents the same project from being published more than once.

The publishing process runs automatically using the results of the quality validation and scoring pipeline.

### 5. AI-Suggested Fallback

AI-suggested projects provide a fallback when public sources do not generate enough qualifying project briefs.

The fallback activates only when the stock of passed, unpublished projects falls below 15 after both Hacker News and Stack Exchange have been processed and still have not supplied enough candidates.

The fallback:

- Allows no more than three generation calls per day.
- Limits publication to a maximum of five AI-suggested projects per day.
- Marks AI-suggested projects with a small spark logo.
- Does not provide an original source link for AI-suggested projects.

Real-source projects always receive publication priority over AI-suggested projects.

## Backend Performance and Engineering

Beyond building the core application, a major focus of the project has been improving backend efficiency, scalability, and reliability.

### 1. Eliminating Unnecessary Embedding Transfers

**Problem**

The original project-list endpoint retrieved full database records, including 3,072-dimensional vector embeddings that the frontend never used.

On a test database containing 54 projects, this resulted in approximately 2.2 MB of database data transferred per listing request.

**Solution**

Reworked the listing endpoint to select only the fields necessary for project cards and serve results from an in-memory cached snapshot.

**Measured result**

| Metric | Before | After |
|---|---|---|
| Data retrieved for initial listing | ~2.2 MB | ~15.6 KB |
| Embeddings included | Yes | No |
| Database read on a cached listing request | Yes | No |

This reduced initial listing data transfer by approximately 99.3% in the measured test scenario.

### 2. Implementing an In-Memory Query Cache

**Problem**

Every listing request originally triggered a PostgreSQL query, creating unnecessary database activity.

This was especially undesirable when using a free-tier database that can become idle.

**Solution**

Implemented an in-memory snapshot containing only project-card fields.

The API now performs filtering, sorting, searching, and pagination against the cached snapshot.

The cache provides:

- A 60-minute refresh interval.
- Continued service from the previous snapshot while a refresh runs.
- A single background refresh instead of overlapping refresh operations.
- Preservation of the last successful snapshot if a refresh fails.
- A five-minute retry interval after refresh failures.

**Result**

Repeated listing requests can be handled without additional database reads, while newly published projects usually become available within about an hour. The first visit after a quiet period may still show the previous list until the next background refresh.

### 3. Building More Flexible Search and Filtering

**Problem**

The original implementation relied on exact matching and limited searchable fields.

This meant that searches involving technology aliases, partial words, or multiple terms could fail to return relevant projects.

**Solution**

Implemented a normalized search system that:

- Ignores capitalization.
- Handles punctuation differences, including dots and hyphens.
- Supports partial-word matching.
- Recognizes common technology aliases.
- Searches project titles, descriptions, and recommended technologies.
- Requires all search terms to match, potentially across different searchable fields.

**Result**

Developers can discover relevant projects without needing to know the exact terminology used in their descriptions.

### 4. Removing the 200-Project Listing Limit

**Problem**

The previous API returned no more than 200 projects, leaving older records inaccessible from the interface.

**Solution**

Introduced backend pagination using the cached snapshot and a frontend Load More interaction.

- Default page size: 24 projects.
- Maximum page size: 100 projects.
- Total result count returned by the API.
- Incremental loading from the frontend.

**Result**

Users can navigate the entire project collection, including the oldest entries, without retrieving all projects at once.

### 5. Migrating Scheduled Workloads to Azure

**Problem**

The initial ingestion and publishing schedule depended on a local Windows machine and its Task Scheduler.

**Solution**

Moved ingestion, automated processing, and publication scheduling to Azure Functions.

- `pipeline_tick` — Every two hours, handling ingestion, extraction, and quality validation.
- `daily_publish` — 10:00 UTC.
- `daily_extraction` — 09:00 UTC (inactive while automation is enabled).
- Secrets managed through Azure Key Vault.
- PostgreSQL hosted on Neon.

**Result**

The automated pipeline no longer depends on a personal computer remaining powered on.

### 6. Improving the Supply of Viable Project Ideas

**Problem**

Hacker News and Stack Exchange initially supplied fewer than one viable project per day, which made a continuous publishing schedule difficult and led to the introduction of an AI-suggested fallback.

**Solution**

Replaced the original narrow searches with a large bank of search phrases: 869 for Hacker News and 836 for each of the seven Stack Exchange sites. These are searched across a three-year window in a resumable order: the newest 14 days every 6 hours, then every phrase, then a full sweep. The searches stay within each source's API limits:

- Stack Exchange searching stops when fewer than 1,500 requests remain in its daily quota.
- Backoff requests from the API are respected.
- Busy Hacker News time windows are split to stay under the search API's result cap.
- Throttling or errors pause that source until the next run.

**Result**

In a test-database check using 30 Hacker News phrases, 45% of the top 20 rows by intent score were valid, compared with 8% before the change. Most of the gain came from Hacker News, since Stack Exchange yielded far less from this style of phrase.

### 7. Automating Project Approval

**Problem**

Publishing originally depended on manual approval, creating a bottleneck in the content pipeline.

**Solution**

Implemented automated quality gates and thorough testing. Gate thresholds were calibrated using the first 49 published projects, with tests covering gate boundaries, duplicate detection, retries, and end-to-end publishing.

**Result**

Projects that pass all validation gates can now be scored and published automatically without manual approval.

## API Security and Reliability

Several safeguards are included in the backend implementation:

- **Restricted CORS:** Only configured origins are allowed, with GET and OPTIONS methods.
- **Protected Administrative Routes:** Admin endpoints are disabled unless `ENABLE_ADMIN_ROUTES=1`.
- **Constant-Time Key Comparison:** Administrative key validation uses constant-time comparison.
- **Rate Limiting:** Requests are limited to 60 GET requests per minute per IP.
- **Restricted API Documentation:** Interactive documentation is disabled unless `ENABLE_DOCS=1`.
- **Resilient Caching:** Previously loaded data remains available during failed refresh attempts.
- **Targeted Saved-Project Retrieval:** The Saved page requests only bookmarked project IDs.
- **User-Friendly Error Handling:** Empty and failed states provide appropriate explanations and recovery actions.

## Project Structure

```
backend/
    FastAPI application
    Database models and queries
    Ingestion and AI processing
    Pipeline stages
    Backend tests

frontend/
    Next.js application
    Reusable UI components
    API client
    Project discovery and saved pages

functions/
    Azure Functions application
    Scheduled ingestion and publication
    Deployment scripts

docs/
    Architectural decisions
    Development progress
    Build order
    Design and implementation notes
```

## Data Sources and Attribution

Projects are derived primarily from publicly available discussions on Hacker News and Stack Exchange.

Source-based project briefs retain links to their original discussions so developers can explore the context and motivation behind each idea.

AI-suggested projects are generated only as a fallback when both Hacker News and Stack Exchange fail to supply enough qualifying projects. These postings are identified by a small spark logo and do not include an original source link.

The application transforms source discussions into structured development challenges rather than presenting them as complete implementations.

## Current Status

The application is deployed and accessible at:

[https://the-problem-network.vercel.app](https://the-problem-network.vercel.app/)

The full automated pipeline is live in production with `AUTOMATION_ENABLED=true`. Azure Functions handles ingestion, AI extraction, quality validation, scoring, and scheduled publication without manual approval.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

Copyright © 2026 Sohan Mirpuri.
