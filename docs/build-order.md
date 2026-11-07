# Build order

The fixed order in which The Problem Network is built, so design polish never interrupts unfinished features.

## Rules

- Do the phases in order. A phase is done when its exit condition is met.
- Design work happens in Phase 4 only.
- An idea that belongs to a later phase goes into the [decision log](decision-log.md), not into the current work.

## Phases

### Phase 0: Lock the spec
- Write the spec, the architecture, the design document and an empty decision log.
- Exit: all of them exist and are reviewed before any application code.

### Phase 1: Data layer
- Define the Postgres tables on Neon: problems, tags, briefs and the rest. Enable pgvector.
- Exit: a row can be inserted into and read from every core table.

### Phase 2: Backend core
- FastAPI skeleton with a health check.
- Then one source at a time, end to end: fetch, extract with the language model, store, expose through a GET endpoint.
- Exit: every planned endpoint returns correct data. No frontend work yet.

### Phase 3: Plain frontend
- Unstyled Next.js pages that call the real API, using React Query for server state and Zustand for client state.
- Exit: every core user flow works with real data.

### Phase 4: Styling pass
- Apply Tailwind and the design tokens, screen by screen, in the page-template order.
- No new design decisions here: use only tokens that already exist in the [design notes](design.md).
- Exit: every screen is styled and matches the design notes.

### Phase 5: Automation
- Azure Functions timers that run the pipeline without anyone starting it. Originally weekly, now daily.
- Exit: a full collection and publishing cycle runs on its own.

### Phase 6: Hardening
- Regression, dependency, security and bloat checks, a security scan and a clean-up pass.
- Exit: all checks pass.

### Phase 7: Polish and ship
- Cross-browser and device check, accessibility check, documentation.
- Deploy the API to Azure App Service and the frontend to Vercel.
- Exit: the live site works for a first-time visitor with no setup.

## Avoid

- Styling before the backend endpoints are finished.
- New design tokens or component variants during Phase 4.
- Automation before the manual flow works.
- Skipping the hardening pass to ship faster.
