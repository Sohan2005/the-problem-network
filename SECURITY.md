# Security Policy

## Reporting a vulnerability

Please do not open a public issue for a security problem. Report it privately through GitHub: open the repository's **Security** tab and choose **Report a vulnerability**. Include what you found, how to reproduce it and what it could affect. I will acknowledge your report and keep you updated until it is fixed.

## Supported version

Only the latest code on the `main` branch and the live site at https://the-problem-network.vercel.app are supported.

## What the project does to stay safe

- The public API is read-only: CORS allows only the configured origins and only GET and OPTIONS requests.
- Admin routes are off unless `ENABLE_ADMIN_ROUTES=1`, and they require an `X-Admin-Key` header that is checked in constant time.
- Each IP is limited to 60 GET requests a minute.
- The API docs are hidden unless `ENABLE_DOCS=1`.
- Secrets live in environment variables (and Azure Key Vault for the timers). Environment files are not committed.
- There are no user accounts. Saved postings stay in your browser, and comments go through giscus and GitHub.

## Out of scope

- Findings that need a leaked key or a compromised account.
- Rate-limit or denial-of-service tests against the live site.
- Issues in third-party services (Vercel, Azure, Neon, GitHub, giscus, Google).
