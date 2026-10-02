import os
import sys
import time
from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm.translate import translate_forum_idea
from db.database import SessionLocal
from db.models import RawIdea
from datetime import datetime

load_dotenv()

def process_stackexchange_candidates(limit=None):
    """Process Stack Exchange candidates through Step 3 extraction pipeline"""
    
    db = SessionLocal()
    
    try:
        # Get unprocessed Stack Exchange ideas
        query = db.query(RawIdea).filter(
            RawIdea.source == "stackexchange_softwarerecs",
            RawIdea.processed_at == None
        )
        
        if limit:
            query = query.limit(limit)
        
        ideas = query.all()
        
        print(f"Processing {len(ideas)} Stack Exchange candidates through Step 3 extraction...")
        
        valid_count = 0
        rescoped_count = 0
        rejected_count = 0
        
        for idea in ideas:
            print(f"Processing ID {idea.id}...")
            
            try:
                result = translate_forum_idea(
                    idea.raw_text,
                    idea.source_url,
                    idea.source
                )
                
                # Update raw_idea with extraction results
                idea.is_valid_idea = str(result["is_valid_idea"]) if isinstance(result["is_valid_idea"], bool) else result["is_valid_idea"]
                idea.rejection_reason = result["rejection_reason"]
                idea.original_ask = result["original_ask"]
                idea.rescoped_version = result["rescoped_version"]
                idea.rescope_reason = result["rescope_reason"]
                idea.extracted_title = result["title"]
                idea.problem_summary = result["problem_summary"]
                idea.target_user = result["target_user"]
                idea.suggested_features = result["suggested_features"]
                idea.difficulty_estimate = result["difficulty_estimate"]
                idea.suggested_tech_stack = result["suggested_tech_stack"]
                idea.learning_outcomes = result["learning_outcomes"]
                idea.processed_at = datetime.utcnow()
                
                if result["is_valid_idea"] == True or result["is_valid_idea"] == "true":
                    print(f"  [VALID] {result['title']}")
                    valid_count += 1
                elif result["is_valid_idea"] == "needs_rescope":
                    print(f"  [RESCOPED] {result['rescoped_version']['title']}")
                    rescoped_count += 1
                else:
                    print(f"  [REJECTED] {result['rejection_reason'][:80]}...")
                    rejected_count += 1
                
                db.commit()
                
                # Rate limit to avoid quota issues
                time.sleep(5)
                
            except Exception as e:
                print(f"  [ERROR] {e}")
                time.sleep(10)
        
        print(f"\n=== Stack Exchange Extraction Breakdown ===")
        print(f"Valid: {valid_count}")
        print(f"Rescoped: {rescoped_count}")
        print(f"Rejected: {rejected_count}")
        print(f"Total viable ideas: {valid_count + rescoped_count}")
        print(f"Yield rate: {(valid_count + rescoped_count) / len(ideas) * 100:.1f}%")
        
    finally:
        db.close()

if __name__ == "__main__":
    process_stackexchange_candidates(limit=200)
