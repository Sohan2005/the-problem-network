from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Table, Boolean, JSON, Float
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime
from pgvector.sqlalchemy import Vector

Base = declarative_base()

brief_tags = Table(
    "brief_tags",
    Base.metadata,
    Column("brief_id", Integer, ForeignKey("briefs.id"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id"), primary_key=True)
)

class Problem(Base):
    __tablename__ = "problems"
    
    id = Column(Integer, primary_key=True)
    source = Column(String(50), nullable=False)
    source_url = Column(String(500), nullable=False, unique=True)
    raw_text = Column(Text, nullable=False)
    embedding = Column(Vector(3072), nullable=True)  # Updated to 3072 for gemini-embedding-001
    ingested_at = Column(DateTime, default=datetime.utcnow)
    
    brief = relationship("Brief", back_populates="problem", uselist=False)

class Brief(Base):
    __tablename__ = "briefs"
    
    id = Column(Integer, primary_key=True)
    problem_id = Column(Integer, ForeignKey("problems.id"), nullable=True, unique=True)  # Made nullable for new pipeline
    raw_idea_id = Column(Integer, ForeignKey("raw_ideas.id"), nullable=True)  # Added to link back to RawIdea source
    title = Column(String(200), nullable=False)
    difficulty = Column(String(20), nullable=False)
    core_task = Column(Text, nullable=False)
    recommended_stack = Column(JSON, nullable=True)  # Changed from String to JSON array
    target_user = Column(Text, nullable=True)  # Added for Project Detail page
    suggested_features = Column(JSON, nullable=True)  # Added for Project Detail page
    learning_outcomes = Column(JSON, nullable=True)  # Added for Project Detail page
    what_youll_need = Column(Text, nullable=True)  # Prerequisites: accounts, tools, local setup, API keys
    how_to_begin = Column(Text, nullable=True)  # First 2-4 actionable steps to start the project
    source_date = Column(DateTime, nullable=True)  # Original post date for age tracking
    created_at = Column(DateTime, default=datetime.utcnow)
    embedding = Column(Vector(3072), nullable=True)  # Updated to 3072 for gemini-embedding-001
    
    problem = relationship("Problem", back_populates="brief")
    tags = relationship("Tag", secondary=brief_tags, back_populates="briefs")

class Tag(Base):
    __tablename__ = "tags"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False, unique=True)
    
    briefs = relationship("Brief", secondary=brief_tags, back_populates="tags")

class DuplicateCandidate(Base):
    """Log for candidates rejected as duplicates (similarity > 0.88)"""
    __tablename__ = "duplicate_candidates"
    
    id = Column(Integer, primary_key=True)
    raw_idea_id = Column(Integer, nullable=False)  # ID of the rejected candidate
    matched_brief_id = Column(Integer, nullable=False)  # ID of the similar live brief
    similarity_score = Column(Float, nullable=False)  # Cosine similarity score
    raw_title = Column(String(500), nullable=False)  # Title of rejected candidate
    matched_brief_title = Column(String(200), nullable=False)  # Title of matched brief
    rejected_at = Column(DateTime, default=datetime.utcnow)  # When rejected as duplicate

class RawIdea(Base):
    __tablename__ = "raw_ideas"
    
    id = Column(Integer, primary_key=True)
    source = Column(String(50), nullable=False)  # "hackernews", "reddit", "indiehackers"
    source_url = Column(String(500), nullable=False, unique=True)
    raw_title = Column(String(500), nullable=False)
    raw_text = Column(Text, nullable=False)  # post body + top-level comments
    author = Column(String(100), nullable=True)
    matched_keyword = Column(String(100), nullable=True)  # which keyword triggered the match
    confidence_flag = Column(String(20), nullable=True)  # "high" or "low confidence for unmet need detection
    passed_prefilter = Column(Boolean, nullable=True)  # Step 2 heuristic filter result
    prefilter_reject_reason = Column(Text, nullable=True)  # Step 2 reject reason
    fetched_at = Column(DateTime, default=datetime.utcnow)  # when we scraped it
    source_date = Column(DateTime, nullable=True)  # actual post creation time from source platform
    processed_at = Column(DateTime, nullable=True)  # when LLM processed it
    is_valid_idea = Column(String(20), nullable=True)  # Step 3 rejection gate (can be true, false, or "needs_rescope")
    rejection_reason = Column(Text, nullable=True)  # Step 3 rejection reason
    original_ask = Column(Text, nullable=True)  # Original scope for rescoped ideas
    rescoped_version = Column(JSON, nullable=True)  # Rescoped brief for needs_rescope ideas
    rescope_reason = Column(Text, nullable=True)  # Reason for rescope
    ready_to_publish = Column(Boolean, nullable=True, default=False)  # Manual approval flag for publishing to briefs
    ready_to_publish_at = Column(DateTime, nullable=True)  # When manually marked ready to publish
    duplicate_of_brief_id = Column(Integer, nullable=True)  # ID of similar brief (Step 5 dedup)
    similarity_score = Column(Float, nullable=True)  # Cosine similarity score (Step 5 dedup)
    # Step 3 extraction output (null until processed)
    extracted_title = Column(String(500), nullable=True)
    problem_summary = Column(Text, nullable=True)
    target_user = Column(String(300), nullable=True)
    suggested_features = Column(JSON, nullable=True)  # list of strings
    difficulty_estimate = Column(String(20), nullable=True)
    suggested_tech_stack = Column(JSON, nullable=True)  # list of strings
    learning_outcomes = Column(JSON, nullable=True)  # list of strings
    what_youll_need = Column(Text, nullable=True)  # Prerequisites for Getting Started
    how_to_begin = Column(Text, nullable=True)  # First steps for Getting Started
    embedding = Column(Vector(3072), nullable=True)  # Updated to 3072 for gemini-embedding-001
