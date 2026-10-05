-- Describes the live database schema (pgvector 0.8.1, PostgreSQL 18).
-- Column order follows the live tables. Embeddings use gemini-embedding-001 at 3072 dimensions.

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Create problems table (legacy GitHub/Devpost/blog pipeline)
CREATE TABLE IF NOT EXISTS problems (
    id SERIAL PRIMARY KEY,
    source VARCHAR(50) NOT NULL,
    source_url VARCHAR(500) NOT NULL UNIQUE,
    raw_text TEXT NOT NULL,
    embedding vector(3072),
    ingested_at TIMESTAMP DEFAULT now()
);

-- Create raw_ideas staging table for forum-sourced ideas
CREATE TABLE IF NOT EXISTS raw_ideas (
    id SERIAL PRIMARY KEY,
    source VARCHAR(50) NOT NULL,
    source_url VARCHAR(500) NOT NULL UNIQUE,
    raw_title VARCHAR(500) NOT NULL,
    raw_text TEXT NOT NULL,
    author VARCHAR(100),
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP,
    rejection_reason TEXT,
    extracted_title VARCHAR(500),
    problem_summary TEXT,
    target_user VARCHAR(300),
    suggested_features JSONB,
    difficulty_estimate VARCHAR(20),
    suggested_tech_stack JSONB,
    learning_outcomes JSONB,
    embedding vector(3072),
    matched_keyword VARCHAR(100),
    passed_prefilter BOOLEAN,
    prefilter_reject_reason TEXT,
    original_ask TEXT,
    rescoped_version JSONB,
    rescope_reason TEXT,
    is_valid_idea VARCHAR(20),
    source_date TIMESTAMP,
    confidence_flag VARCHAR(20),
    ready_to_publish BOOLEAN DEFAULT false,
    ready_to_publish_at TIMESTAMP,
    duplicate_of_brief_id INTEGER,
    similarity_score DOUBLE PRECISION,
    what_youll_need TEXT,
    how_to_begin TEXT
);

-- Create briefs table
CREATE TABLE IF NOT EXISTS briefs (
    id SERIAL PRIMARY KEY,
    problem_id INTEGER UNIQUE REFERENCES problems(id),
    title VARCHAR(200) NOT NULL,
    difficulty VARCHAR(20) NOT NULL,
    core_task TEXT NOT NULL,
    recommended_stack JSON,
    created_at TIMESTAMP DEFAULT now(),
    source_date TIMESTAMP,
    embedding vector(3072),
    target_user TEXT,
    suggested_features JSON,
    learning_outcomes JSON,
    raw_idea_id INTEGER REFERENCES raw_ideas(id),
    what_youll_need TEXT,
    how_to_begin TEXT
);

-- Create tags table
CREATE TABLE IF NOT EXISTS tags (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE
);

-- Create brief_tags association table
CREATE TABLE IF NOT EXISTS brief_tags (
    brief_id INTEGER NOT NULL REFERENCES briefs(id),
    tag_id INTEGER NOT NULL REFERENCES tags(id),
    PRIMARY KEY (brief_id, tag_id)
);

-- Create duplicate_candidates log for candidates rejected as duplicates of live briefs
CREATE TABLE IF NOT EXISTS duplicate_candidates (
    id SERIAL PRIMARY KEY,
    raw_idea_id INTEGER NOT NULL,
    matched_brief_id INTEGER NOT NULL,
    similarity_score DOUBLE PRECISION NOT NULL,
    raw_title VARCHAR(500) NOT NULL,
    matched_brief_title VARCHAR(200) NOT NULL,
    rejected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- UNUSED: users and saved_briefs remain in the live database but no application code reads or writes them
-- (favorites moved to browser localStorage; see decision-log.md 2026-09-26).
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    hashed_password VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS saved_briefs (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    brief_id INTEGER NOT NULL REFERENCES briefs(id) ON DELETE CASCADE,
    saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, brief_id)
);

CREATE INDEX IF NOT EXISTS idx_saved_briefs_user_id ON saved_briefs (user_id);
