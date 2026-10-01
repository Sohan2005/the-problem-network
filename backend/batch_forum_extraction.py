import os
import sys
import time
import argparse
from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm.translate import translate_forum_idea
from db.database import SessionLocal
from db.models import RawIdea

load_dotenv()

def batch_forum_extraction(skip_ids=None):
    """Run Step 3 extraction on all passed records except specified skip IDs"""
    
    if skip_ids is None:
        skip_ids = []
    
    db = SessionLocal()
    
    try:
        # Get all passed records excluding skip IDs
        raw_ideas = db.query(RawIdea).filter(
            RawIdea.passed_prefilter == True,
            RawIdea.id.notin_(skip_ids)
        ).all()
        
        print(f"Processing {len(raw_ideas)} passed records (excluding skip IDs: {skip_ids})\n")
        
        processed_count = 0
        valid_count = 0
        rejected_count = 0
        error_count = 0
        
        for idea in raw_ideas:
            # Skip already processed records
            if idea.processed_at is not None:
                print(f"Skipping ID {idea.id}: already processed")
                continue
            
            print(f"Processing ID {idea.id}: {idea.raw_title[:50]}...")
            
            try:
                result = translate_forum_idea(
                    idea.raw_text,
                    idea.source_url,
                    idea.source
                )
                
                # Update raw_idea with extraction results
                idea.is_valid_idea = result["is_valid_idea"]
                idea.rejection_reason = result["rejection_reason"]
                idea.extracted_title = result["title"]
                idea.problem_summary = result["problem_summary"]
                idea.target_user = result["target_user"]
                idea.suggested_features = result["suggested_features"]
                idea.difficulty_estimate = result["difficulty_estimate"]
                idea.suggested_tech_stack = result["suggested_tech_stack"]
                idea.learning_outcomes = result["learning_outcomes"]
                idea.what_youll_need = result["what_youll_need"]
                idea.how_to_begin = result["how_to_begin"]
                idea.processed_at = datetime.utcnow()
                
                if result["is_valid_idea"]:
                    valid_count += 1
                    print(f"  [VALID] {result['title']}")
                else:
                    rejected_count += 1
                    print(f"  [REJECTED] {result['rejection_reason']}")
                
                processed_count += 1
                
                # Rate limit: wait 5 seconds between requests to stay under free tier quota
                time.sleep(5)
                
            except Exception as e:
                print(f"  [ERROR] {e}")
                error_count += 1
                # Wait longer on error to avoid rate limit issues
                time.sleep(10)
            
            # Commit every 5 records to avoid losing progress
            if processed_count % 5 == 0:
                db.commit()
                print(f"  Committed {processed_count} records\n")
        
        db.commit()
        
        print(f"\n=== Batch Processing Summary ===")
        print(f"Total processed: {processed_count}")
        print(f"Valid ideas: {valid_count}")
        print(f"Rejected: {rejected_count}")
        print(f"Errors: {error_count}")
        
    finally:
        db.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Step 3 extraction on passed raw ideas")
    parser.add_argument("--skip-ids", nargs="+", type=int, help="IDs to skip during extraction")
    args = parser.parse_args()
    batch_forum_extraction(skip_ids=args.skip_ids)
