-- 001_pipeline_state.sql
-- Pipeline state for the automated ingest -> gate -> publish flow.
-- Idempotent: every statement is safe to re-run. Runs as a single transaction; any failed check aborts everything.

BEGIN;

-- 1. New raw_ideas columns
ALTER TABLE raw_ideas ADD COLUMN IF NOT EXISTS canonical_url text;
ALTER TABLE raw_ideas ADD COLUMN IF NOT EXISTS extraction_attempts integer NOT NULL DEFAULT 0;
ALTER TABLE raw_ideas ADD COLUMN IF NOT EXISTS last_error text;
ALTER TABLE raw_ideas ADD COLUMN IF NOT EXISTS gate_status text NOT NULL DEFAULT 'pending';
ALTER TABLE raw_ideas ADD COLUMN IF NOT EXISTS gate_failures jsonb;
ALTER TABLE raw_ideas ADD COLUMN IF NOT EXISTS gate_score numeric;
ALTER TABLE raw_ideas ADD COLUMN IF NOT EXISTS gated_at timestamptz;
ALTER TABLE raw_ideas ADD COLUMN IF NOT EXISTS published_brief_id integer REFERENCES briefs(id);
ALTER TABLE raw_ideas ADD COLUMN IF NOT EXISTS published_at timestamptz;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'raw_ideas_gate_status_check' AND conrelid = 'raw_ideas'::regclass
    ) THEN
        ALTER TABLE raw_ideas ADD CONSTRAINT raw_ideas_gate_status_check
            CHECK (gate_status IN ('pending', 'passed', 'failed', 'duplicate'));
    END IF;
END $$;

-- 2. Backfill canonical_url: lowercase scheme and host, drop the fragment and utm_* parameters,
--    remove trailing slashes from the path, keep every other query parameter in its original order
--    (Hacker News item URLs differ only by ?id= and must stay distinct).
WITH parts AS (
    SELECT id,
           regexp_match(btrim(source_url), '^([A-Za-z][A-Za-z0-9+.-]*://[^/?#]*)?([^?#]*)(\?[^#]*)?(#.*)?$') AS m
    FROM raw_ideas
    WHERE canonical_url IS NULL
),
normalized AS (
    SELECT id,
           lower(coalesce(m[1], '')) AS origin,
           regexp_replace(coalesce(m[2], ''), '/+$', '') AS path,
           (SELECT string_agg(kv, '&' ORDER BY ord)
            FROM unnest(string_to_array(substring(m[3] FROM 2), '&')) WITH ORDINALITY AS q(kv, ord)
            WHERE kv <> '' AND lower(kv) NOT LIKE 'utm\_%') AS query
    FROM parts
)
UPDATE raw_ideas r
SET canonical_url = n.origin || n.path || coalesce('?' || n.query, '')
FROM normalized n
WHERE r.id = n.id;

DO $$
DECLARE
    collision_groups integer;
    collision_sample text;
BEGIN
    SELECT count(*) INTO collision_groups
    FROM (SELECT canonical_url FROM raw_ideas WHERE canonical_url IS NOT NULL
          GROUP BY canonical_url HAVING count(*) > 1) d;

    IF collision_groups > 0 THEN
        SELECT string_agg(canonical_url || ' (ids ' || ids || ')', '; ') INTO collision_sample
        FROM (SELECT canonical_url, string_agg(id::text, ',' ORDER BY id) AS ids
              FROM raw_ideas WHERE canonical_url IS NOT NULL
              GROUP BY canonical_url HAVING count(*) > 1
              ORDER BY canonical_url LIMIT 20) s;
        RAISE EXCEPTION 'Aborting: % canonical_url collision group(s). First 20: %', collision_groups, collision_sample;
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS raw_ideas_canonical_url_key ON raw_ideas (canonical_url);

-- 3. Normalize is_valid_idea to lowercase ('true', 'false', 'needs_rescope')
UPDATE raw_ideas
SET is_valid_idea = lower(is_valid_idea)
WHERE is_valid_idea IS DISTINCT FROM lower(is_valid_idea);

DO $$
DECLARE
    unexpected text;
BEGIN
    SELECT string_agg(DISTINCT is_valid_idea, ', ') INTO unexpected
    FROM raw_ideas
    WHERE is_valid_idea IS NOT NULL AND is_valid_idea NOT IN ('true', 'false', 'needs_rescope');

    IF unexpected IS NOT NULL THEN
        RAISE EXCEPTION 'Aborting: unexpected is_valid_idea value(s): %', unexpected;
    END IF;
END $$;

-- 5 (checked before 4 so the backfill can never see two briefs for one raw idea).
--    One brief per raw idea: abort on existing duplicates, then enforce with a unique index.
DO $$
DECLARE
    duplicate_ids text;
BEGIN
    SELECT string_agg(raw_idea_id::text || ' x' || n, ', ') INTO duplicate_ids
    FROM (SELECT raw_idea_id, count(*) AS n FROM briefs
          WHERE raw_idea_id IS NOT NULL
          GROUP BY raw_idea_id HAVING count(*) > 1) d;

    IF duplicate_ids IS NOT NULL THEN
        RAISE EXCEPTION 'Aborting: briefs.raw_idea_id duplicates (raw_idea_id x count): %', duplicate_ids;
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS briefs_raw_idea_id_key ON briefs (raw_idea_id);

-- 4. Backfill published markers from existing briefs (briefs.created_at is stored as naive UTC)
UPDATE raw_ideas r
SET published_brief_id = b.id,
    published_at = b.created_at AT TIME ZONE 'UTC'
FROM briefs b
WHERE b.raw_idea_id = r.id
  AND r.published_brief_id IS NULL;

-- 6. Publish bookkeeping and stage run log
CREATE TABLE IF NOT EXISTS publish_days (
    day date PRIMARY KEY,
    target integer,
    published integer,
    is_flexible_day boolean,
    buffer_before integer,
    buffer_after integer,
    note text
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id SERIAL PRIMARY KEY,
    stage text NOT NULL,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    rows_in integer,
    rows_out integer,
    status text,
    error text
);

COMMIT;
