import os
import sys
import json
from datetime import datetime
from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm.translate import generate_embedding
from db.database import SessionLocal
from db.models import RawIdea, Brief

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
            source = record.source
            source_url = record.source_url
            raw_text = record.raw_text
            is_valid_idea = record.is_valid_idea
            extracted_title = record.extracted_title
            problem_summary = record.problem_summary
            target_user = record.target_user
            features = record.suggested_features
            difficulty = record.difficulty_estimate
            tech_stack = record.suggested_tech_stack
            learning = record.learning_outcomes
            rescoped_version = record.rescoped_version
            source_date = record.source_date
            
            # Determine which fields to use (rescoped or direct)
            if is_valid_idea == 'needs_rescope' and rescoped_version:
                title = rescoped_version.get('title')
                problem = rescoped_version.get('problem_summary')
                target = rescoped_version.get('target_user')
                features_list = rescoped_version.get('suggested_features', [])
                diff = rescoped_version.get('difficulty_estimate')
                tech_list = rescoped_version.get('suggested_tech_stack', [])
                learning_list = rescoped_version.get('learning_outcomes', [])
            else:
                title = extracted_title
                problem = problem_summary
                target = target_user
                features_list = features if features else []
                diff = difficulty
                tech_list = tech_stack if tech_stack else []
                learning_list = learning if learning else []
            
            # Insert into briefs table
            brief = Brief(
                title=title,
                difficulty=diff,
                core_task=problem,
                recommended_stack=tech_list,  # Now JSON type, not string
                target_user=target,
                suggested_features=features_list,
                learning_outcomes=learning_list,
                raw_idea_id=raw_idea.id,  # Link back to RawIdea source
                created_at=datetime.utcnow(),
                source_date=source_date
            )
            db.add(brief)
            db.flush()  # Get the ID without committing
            
            brief_id = brief.id
            
            # Generate embedding for dedup (Step 5)
            combined_text = f"{title} {problem}"
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
        print(f"\n=== Daily Publish Complete ===")
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
