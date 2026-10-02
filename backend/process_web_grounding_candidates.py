import os
import sys
import time
from dotenv import load_dotenv
from datetime import datetime, date, timedelta

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm.translate import translate_forum_idea, generate_embedding
from db.database import SessionLocal
from db.models import RawIdea
from dedup_check import check_duplicate, log_duplicate_candidate
from sqlalchemy import text

load_dotenv()

# 3-year cutoff date
CUTOFF_DATE = date.today() - timedelta(days=3*365)

def process_web_grounding_candidates(limit=50):
    """Process unprocessed web grounding candidates through Step 3 extraction pipeline"""
    
    db = SessionLocal()
    
    try:
        # Get unprocessed web grounding ideas
        # Note: web_grounding may not have reliable dates, so we don't filter by date at query time
        # Instead, we flag unverifiable dates during processing
        ideas = db.query(RawIdea).filter(
            RawIdea.source == "web_grounding",
            RawIdea.processed_at == None
        ).limit(limit).all()
        
        print(f"Processing {len(ideas)} web grounding candidates through Step 3 extraction...")
        
        valid_count = 0
        rescoped_count = 0
        rejected_count = 0
        
        for idea in ideas:
            print(f"Processing ID {idea.id}: {idea.raw_title[:50]}...")
            
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
                
                # Step 5: Dedup check for valid ideas
                if result["is_valid_idea"] == True or result["is_valid_idea"] == "true" or result["is_valid_idea"] == "needs_rescope":
                    # Determine title and problem_summary for dedup check
                    if result["is_valid_idea"] == "needs_rescope" and result["rescoped_version"]:
                        check_title = result["rescoped_version"]["title"]
                        check_problem = result["rescoped_version"]["problem_summary"]
                    else:
                        check_title = result["title"]
                        check_problem = result["problem_summary"]
                    
                    # Run dedup check
                    matched_brief_id, similarity = check_duplicate(check_title, check_problem, db)
                    
                    if matched_brief_id and similarity > 0.88:
                        # High similarity - reject as duplicate, log to duplicate_candidates
                        matched_brief_title = db.execute(text("SELECT title FROM briefs WHERE id = :id"), {"id": matched_brief_id}).scalar()
                        log_duplicate_candidate(idea.id, matched_brief_id, similarity, idea.raw_title, matched_brief_title)
                        idea.is_valid_idea = "false"
                        idea.rejection_reason = f"Duplicate of existing brief (ID {matched_brief_id}, similarity: {similarity:.2f})"
                        print(f"  [DUPLICATE] Similarity {similarity:.2f} to brief ID {matched_brief_id}")
                        rejected_count += 1
                        db.commit()
                        continue
                    elif matched_brief_id and similarity >= 0.75:
                        # Gray zone - flag for review
                        idea.duplicate_of_brief_id = matched_brief_id
                        idea.similarity_score = similarity
                        print(f"  [FLAGGED] Possible duplicate (similarity: {similarity:.2f}) to brief ID {matched_brief_id}")
                
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
        
        print(f"\n=== Web Grounding Extraction Breakdown ===")
        print(f"Valid: {valid_count}")
        print(f"Rescoped: {rescoped_count}")
        print(f"Rejected: {rejected_count}")
        print(f"Total viable ideas: {valid_count + rescoped_count}")
        print(f"Yield rate: {(valid_count + rescoped_count) / len(ideas) * 100:.1f}%")
        
        return valid_count, rescoped_count, rejected_count
        
    finally:
        db.close()

if __name__ == "__main__":
    process_web_grounding_candidates(limit=50)
