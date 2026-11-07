# Decision log

What was decided on The Problem Network, why, and when. One line per decision, oldest first.

## Data sources

- **2026-07-23: Drop Reddit.** Its API now needs manual approval, which would stall the project. It stays dropped.
- **2026-07-24: Use Hacker News as the main forum source.** Reddit's unauthenticated access was closed, and Ask HN needs no approval. Indie Hackers stays a possible future source.
- **2026-07-24: Do not build an "Inspiration" section from Product Hunt or Devpost.** Those sites show finished products, not unmet needs. It would be a separate feature.
- **2026-08-02: Only use posts from the last 3 years (rolling window).** Search returned 10-year-old posts, which gave outdated ideas. The window is computed from today's date.
- **2026-08-02: Retire GitHub issues as a source, and reset the briefs table.** The project moved to forum-sourced ideas, so all existing briefs were deleted.
- **2026-08-16: Add a "web grounding" source (Gemini with Google Search).** On a test batch, all 19 ideas it found were usable.
- **2026-10-05: Keep the GitHub, blog and Devpost adapters retired.** They fit poorly (coding tasks, thin text, no unmet needs). A shared ingestion layer with one adapter contract replaces them.
- **2026-10-07: Search with a phrase bank over the 3-year window.**
  - Hacker News: each exact phrase, then every Ask HN story month by month.
  - Stack Exchange: seven sites, phrase searches then a tag sweep.
  - Only posts with an intent score of at least 2 and at least 20 words are kept.
  - Exact phrases are used because "is there a tool that" matches 6 Ask HN stories as a phrase but 1,239 as loose words.
- **2026-10-07: Add an AI-suggested top-up source,** used only when fewer than 15 passed postings are waiting, capped at 5 published per day, with real-sourced postings always ranked first.
- **2026-10-07: Show a source link only for Hacker News and Stack Exchange postings** (commit dc5d35b).

## Extraction and quality

- **2026-07-28: Three outcomes for extraction.** An idea is valid, invalid, or "needs rescope" (too big, so it is cut down to a student-sized version). Some ideas, such as a full learning platform, were too large as written.
- **2026-08-16: Check duplicates with embeddings.** At first: above 0.88 similarity is rejected and 0.75 to 0.88 is flagged for review. The automated gates later use 0.85.
- **2026-08-23: Fix embeddings at 3072 dimensions** (`gemini-embedding-001`) in every table and call, so a changed default can never mismatch vectors. The embedding model is never changed.
- **2026-08-23: Use SQLAlchemy in every pipeline script,** after a raw database connection failed in one environment.
- **2026-08-30: Link each brief to its raw idea with a foreign key,** so later fixes do not need title matching.
- **2026-10-05: Replace the human review step with automated quality gates:** structure checks, red-flag rules (for example Show HN pitches), overlap with the source text, and embedding-based duplicate checks. Reason: the project must run without anyone in the loop. The automated pipeline is now switched on in production.
- **2026-10-07: Loosen the prefilter.** Minimum words went from 40 to 20 and the "no intent signal" rule was switched off. On 668 extracted rows the strict rules would have rejected 26 of the 96 ideas later judged valid. Posts with an intent score of -7 or lower are rejected as noise.
- **2026-10-07: Move Gemini calls to the `google-genai` package** (the older package was deprecated).
- **2026-10-10: Stay on free quotas.** Extraction is capped at 300 calls a day and Stack Exchange sweeping stops below 1,500 remaining requests. The run stops cleanly when a quota is used up.

## Publishing

- **2026-08-06: Cap daily publishing and keep extraction separate from review.** Ideas were reviewed by hand, marked ready, and published up to 10 a day, oldest approved first.
- **2026-08-06: Move collection and publishing to Azure Functions timers,** with secrets in Azure Key Vault, so nothing depends on a local machine. The local Windows scheduled task was removed.
- **2026-10-07: Publish 5 postings a day** (was 10), with a minimum of 3 on flexible days: Wednesday, Saturday and Sunday (UTC). A posting is never published twice (commit d5028c5).

## Product and design

- **2026-07-24: Replace the old design files with one design document.** Duplicate documents drift out of date.
- **2026-07-24: Hold back the Collections and Sources navigation items** until their scope is approved. The navigation is Browse and Saved.
- **2026-07-24: Style the posting page with the data that exists,** without placeholder content.
- **2026-08-30: Wire up search and sort, trim the navigation to real pages, and rebuild the posting page.** The briefs table gained target user, suggested features and learning outcomes, and the stack is stored as a JSON list.
- **2026-09-04: Use a warm olive palette with IBM Plex Sans.** One accent color, text contrast above WCAG AA.
- **2026-09-06 to 2026-09-26: Saved postings are kept in the browser (localStorage), with no accounts.** A GitHub sign-in plan was dropped and the unused saved-postings backend code was removed.
- **2026-09-19: Document only what is built.** Acceptance criteria, stretch goals and the landing, dashboard and settings templates were removed from the design document.
- **2026-10-11: Harden the API.** Origins come from `ALLOWED_ORIGINS` and only GET and OPTIONS are allowed. Ingest routes sit behind `ENABLE_ADMIN_ROUTES` and an admin key. `/docs` is hidden unless `ENABLE_DOCS=1`. GET requests are rate limited and brief responses cached.
- **2026-11-03: Stop reading embeddings in the API,** to cut the data read from the free database.
- **2026-11-04: Match search and stack filter in memory over every posting,** with partial words and aliases.
- **2026-11-04: Call items "postings" everywhere visitors see them,** and replace the weekly count with "New postings added every day".
- **2026-11-05: Cache the list as a snapshot refreshed every 60 minutes,** serve the old copy during a refresh, and page it with a Load more button.
