from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Table
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func
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
    embedding = Column(Vector(768), nullable=True)
    ingested_at = Column(DateTime, default=func.utcnow())
    
    brief = relationship("Brief", back_populates="problem", uselist=False)

class Brief(Base):
    __tablename__ = "briefs"
    
    id = Column(Integer, primary_key=True)
    problem_id = Column(Integer, ForeignKey("problems.id"), nullable=False, unique=True)
    title = Column(String(200), nullable=False)
    difficulty = Column(String(20), nullable=False)
    core_task = Column(Text, nullable=False)
    recommended_stack = Column(String(300), nullable=True)
    created_at = Column(DateTime, default=func.utcnow())
    
    problem = relationship("Problem", back_populates="brief")
    tags = relationship("Tag", secondary=brief_tags, back_populates="briefs")

class Tag(Base):
    __tablename__ = "tags"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False, unique=True)
    
    briefs = relationship("Brief", secondary=brief_tags, back_populates="tags")

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True)
    email = Column(String(255), nullable=False, unique=True)
    hashed_password = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=func.utcnow())
