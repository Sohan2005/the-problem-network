import os
import sys
from datetime import datetime
from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import SessionLocal
from db.models import RawIdea

# Load .env from project root (relative to this script)
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
env_path = os.path.join(project_root, '.env')
load_dotenv(env_path)

def mark_ready_to_publish(approved_ids):
    """
    Batch mark raw_idea records as ready_to_publish.
    This is the manual approval step - user reviews export and provides IDs.
    """
    
    db = SessionLocal()
    try:
        marked_count = 0
        
        for raw_id in approved_ids:
            # Mark as ready_to_publish
            idea = db.query(RawIdea).filter(RawIdea.id == raw_id).first()
            if idea and (idea.ready_to_publish is None or idea.ready_to_publish == False):
                idea.ready_to_publish = True
                idea.ready_to_publish_at = datetime.utcnow()
                marked_count += 1
                print(f"  [OK] Marked ID {raw_id} as ready_to_publish")
            else:
                print(f"  [SKIP] ID {raw_id} already ready or not found")
        
        db.commit()
        print(f"\n=== Batch Approval Complete ===")
        print(f"Marked {marked_count} records as ready_to_publish")
        
        # Check total ready_to_publish count
        total_ready = db.query(RawIdea).filter(RawIdea.ready_to_publish == True).count()
        print(f"Total ready_to_publish: {total_ready}")
        
        return marked_count
        
    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
        return 0
    finally:
        db.close()

if __name__ == "__main__":
    # Accept IDs as command-line arguments
    import sys
    approved_ids = [int(id_str) for id_str in sys.argv[1:]] if len(sys.argv) > 1 else []
    
    if not approved_ids:
        print("No IDs provided.")
        print("Usage: python mark_ready_to_publish.py 123 456 789")
    else:
        mark_ready_to_publish(approved_ids)
