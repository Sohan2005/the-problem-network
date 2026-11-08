-- 002_site_visits.sql
-- Anonymous visit counter: one row per UTC day holding only a number. No IP address, cookie, user agent or visitor
-- identifier is stored. The total is the sum of the daily rows.
-- Idempotent: every statement is safe to re-run. Runs as a single transaction.

BEGIN;

CREATE TABLE IF NOT EXISTS site_visits (
    day date PRIMARY KEY,
    visits bigint NOT NULL DEFAULT 0 CHECK (visits >= 0)
);

COMMIT;
