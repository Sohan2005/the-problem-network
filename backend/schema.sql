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

-- Create users table
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    hashed_password VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
