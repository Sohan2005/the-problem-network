# Progress

Where The Problem Network stands, by build phase and by feature. See [build-order.md](build-order.md) for the phases.

Status: site live. The automatic pipeline is enabled in Azure: new postings are published every day through quality gates, with no manual review.

## Phases

- [x] Phase 0: Lock the spec and design rules.
- [x] Phase 1: Data layer. Schema in Neon, pgvector confirmed, rows inserted and read back.
- [x] Phase 2: Backend core. FastAPI app and health check; each source checked end to end (fetch, extract, store, read).
- [x] Phase 3: Plain frontend wired to the real API. Browse with filters, and a posting page.
- [x] Phase 4: Styling pass with the design tokens, plus the Getting Started, Tags and Comments sections.
- [ ] Phase 5: Automation. Azure Functions timers run in production. The full pipeline (ingest, prefilter, extract, quality gates, publish with no human review) is enabled through `AUTOMATION_ENABLED`.
- [ ] Phase 6: Hardening pass.
- [ ] Phase 7: Polish and ship.

## Features

1. Ingestion from Hacker News and Stack Exchange: done. GitHub is retired.
2. Language-model extraction into structured postings: done.
3. Storage in Neon with pgvector: done.
4. Browse the list of postings: done (paged, with Load more).
5. Filter by difficulty and tech stack, and search: done.
6. Posting page with Getting Started, tags and comments: done.
7. Automated daily updates: running in Azure Functions with the automatic pipeline enabled.
8. Saved postings: done, kept in the browser. There are no accounts.
9. Web grounding ingestion: done, added later. AI-suggested postings are now only a fallback when Hacker News and Stack Exchange do not supply enough.

## Deferred or retired

- Reddit ingestion: dropped for good.
- GitHub ingestion: retired for good.
- Collections and Sources navigation: waiting for scope approval.
