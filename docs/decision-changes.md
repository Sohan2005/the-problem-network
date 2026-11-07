# Decision changes: from GitHub issues to forum-sourced ideas

The project first turned GitHub "good first issue" bug-fix tasks into briefs. This note records the change of direction and the pipeline that came with it. Later changes are in the [decision log](decision-log.md).

## What changed

- Before: briefs came from GitHub issues, which already have a title, a description and labels.
- Now: briefs come from forum posts where someone asks for a tool or app to exist. They are turned into project postings for students (portfolios, internships, learning, hobby projects).
- Forum posts are unstructured and the real signal is often in the comments. They need their own filtering and a judgment step, not a copy of the GitHub pipeline.
- Only the data source and the filtering changed. FastAPI, Neon with pgvector, the Next.js frontend and Gemini stay.

## Sources

- Reddit was the first target, but its API needs manual approval. It was dropped, and Hacker News (Ask HN) became the main source. Stack Exchange was added later.
- Indie Hackers was considered and not built.
- Product Hunt and Devpost show finished products, so they do not fit.

## The pipeline

1. **Ingest.** Store the full text of each post (title, body, top-level comments) in a raw staging table with its source, URL and date. No quality judgment at this step.
2. **Prefilter.** Reject cheap cases before any model call: very short posts, meta discussion or rants, and self-promotion. The first rule was a 40-word minimum. It is now 20 words (see the decision log).
3. **Extract and judge.** One model call decides whether the post is a valid idea and extracts the structured fields. The judgment field comes first, so unusable posts are not turned into polished but meaningless briefs. The fields are title, problem summary, target user, suggested features, difficulty, tech stack and learning outcomes.
4. **Rejection rules.** Reject a post if it is:
   - an existing product pitch rather than a request;
   - missing a clear target user or use case;
   - a coding-help question rather than an app idea;
   - illegal, adult or unsuitable for a student project.
5. **Duplicate check.** Forums repeat the same ideas often. Compare embeddings with pgvector and flag near-duplicates before they ship as separate briefs.
6. **Staging before publishing.** Valid ideas go to a staging table first, never straight into the live briefs table.

## Later changes

- Step 6 originally required a human review. On 2026-10-05 it was replaced by automated quality gates. That pipeline is now switched on in production, so postings are published without manual review.
- A third outcome, "needs rescope", was added on 2026-07-28 for ideas that are valid but too big.
