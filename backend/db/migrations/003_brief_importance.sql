-- 003_brief_importance.sql
-- Real-world importance of each brief: how much the underlying problem matters to the people who face it.
-- importance is 'high', 'medium' or 'everyday' (NULL until rated); importance_detail holds the model's factor scores,
-- reason and rating metadata, or the failed attempts while unrated. Written by pipeline/importance.py.
-- Idempotent: every statement is safe to re-run. Runs as a single transaction.

BEGIN;

ALTER TABLE briefs ADD COLUMN IF NOT EXISTS importance text;
ALTER TABLE briefs ADD COLUMN IF NOT EXISTS importance_detail jsonb;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'briefs_importance_check' AND conrelid = 'briefs'::regclass
    ) THEN
        ALTER TABLE briefs ADD CONSTRAINT briefs_importance_check
            CHECK (importance IN ('high', 'medium', 'everyday'));
    END IF;
END $$;

COMMIT;
