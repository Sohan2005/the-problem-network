import os
import sys
from datetime import datetime
from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm.translate import generate_embedding
from db.database import SessionLocal
from db.models import RawIdea, Brief
from pipeline.publish import brief_fields, embedding_text

# Load .env from project root (relative to this script)
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
env_path = os.path.join(project_root, '.env')
load_dotenv(env_path)

def daily_publish_to_briefs(limit=10):
    """
    Daily automated publish function:
    - Takes UP TO 10 records marked ready_to_publish
    - Promotes them to live briefs table
    - Uses oldest-approved-first ordering
    - Requires NO manual action once records are marked ready
    """
    
    db = SessionLocal()
    try:
        # Get ready_to_publish records, oldest first
        records = db.query(RawIdea).filter(
            RawIdea.ready_to_publish == True,
            RawIdea.processed_at != None
        ).order_by(RawIdea.ready_to_publish_at.asc()).limit(limit).all()
        
        if not records:
            print("No ready_to_publish records found. Nothing to publish.")
            return 0
        
        print(f"Found {len(records)} ready_to_publish records to promote\n")
        
        promoted_count = 0
        
        for record in records:
            raw_id = record.id
            
            # Insert into briefs table (rescoped fields for needs_rescope, extracted fields otherwise)
            fields = brief_fields(record)
            title = fields["title"]
            brief = Brief(**fields, created_at=datetime.utcnow())
            db.add(brief)
            db.flush()  # Get the ID without committing
            
            brief_id = brief.id
            
            # Generate embedding for dedup (Step 5)
            combined_text = embedding_text(fields)
            embedding = generate_embedding(combined_text)
            embedding_str = f"[{','.join(map(str, embedding))}]"
            
            # Update brief with embedding using raw SQL for pgvector
            from sqlalchemy import text
            db.execute(text("""
                UPDATE briefs
                SET embedding = CAST(:embedding AS vector)
                WHERE id = :brief_id;
            """), {"embedding": embedding_str, "brief_id": brief_id})
            
            print(f"  [OK] Promoted raw_idea ID {raw_id} to brief ID {brief_id}: {title[:50]}...")
            
            # Mark as published by clearing ready_to_publish
            record.ready_to_publish = False
            record.ready_to_publish_at = None
            
            promoted_count += 1
        
        db.commit()
        print("\n=== Daily Publish Complete ===")
        print(f"Promoted {promoted_count} briefs to live table")
        
        # Check remaining ready_to_publish count
        remaining = db.query(RawIdea).filter(RawIdea.ready_to_publish == True).count()
        print(f"Remaining ready_to_publish: {remaining}")
        
        return promoted_count
        
    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
        return 0
    finally:
        db.close()

if __name__ == "__main__":
    daily_publish_to_briefs(limit=10)
