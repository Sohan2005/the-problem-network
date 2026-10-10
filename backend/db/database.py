from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# Neon suspends idle compute and drops idle connections: test each pooled connection before use and replace old ones.
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=300, connect_args={"connect_timeout": 30})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
