-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Create problems table
CREATE TABLE IF NOT EXISTS problems (
    id SERIAL PRIMARY KEY,
    source VARCHAR(50) NOT NULL,
    source_url VARCHAR(500) NOT NULL UNIQUE,
    raw_text TEXT NOT NULL,
    embedding vector(768),
    ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create briefs table
CREATE TABLE IF NOT EXISTS briefs (
    id SERIAL PRIMARY KEY,
    problem_id INTEGER NOT NULL UNIQUE REFERENCES problems(id),
    title VARCHAR(200) NOT NULL,
    difficulty VARCHAR(20) NOT NULL,
    core_task TEXT NOT NULL,
    recommended_stack VARCHAR(300),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

-- Create raw_ideas staging table for forum-sourced ideas
CREATE TABLE IF NOT EXISTS raw_ideas (
    id SERIAL PRIMARY KEY,
    source VARCHAR(50) NOT NULL,
    source_url VARCHAR(500) NOT NULL UNIQUE,
    raw_title VARCHAR(500) NOT NULL,
    raw_text TEXT NOT NULL,
    author VARCHAR(100),
    matched_keyword VARCHAR(100),
    passed_prefilter BOOLEAN,
    prefilter_reject_reason TEXT,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP,
    is_valid_idea BOOLEAN,
    rejection_reason TEXT,
    extracted_title VARCHAR(500),
    problem_summary TEXT,
    target_user VARCHAR(300),
    suggested_features JSONB,
    difficulty_estimate VARCHAR(20),
    suggested_tech_stack JSONB,
    learning_outcomes JSONB,
    embedding vector(768)
);
