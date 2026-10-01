import os
import sys
import time
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import SessionLocal
from db.queries import create_raw_idea, get_raw_idea_by_url

# Load .env from project root (relative to this script)
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
env_path = os.path.join(project_root, '.env')
load_dotenv(env_path)

def fetch_softwarerecs_ideas():
    """
    Ingest questions from Software Recommendations Stack Exchange
    Filter heuristic: unanswered + aged + viewed = potential gap
    """
    
    # Stack Exchange API configuration
    api_key = os.getenv("STACKEXCHANGE_API_KEY")  # User needs to set this
    site = "softwarerecs"
    base_url = "https://api.stackexchange.com/2.3"
    
    # Date filtering: rolling 3-year window
    max_post_age_years = 3
    current_timestamp = int(time.time())
    seconds_per_year = 365 * 24 * 60 * 60
    min_timestamp = current_timestamp - (max_post_age_years * seconds_per_year)
    min_date = datetime.fromtimestamp(min_timestamp)
    
    # Filter thresholds
    min_question_age_days = 30
    high_confidence_view_count = 100
    max_pages = 10  # Limit to 10 pages (1000 questions) to stay within quota
    
    db = SessionLocal()
    processed_count = 0
    skipped_count = 0
    high_confidence_count = 0
    low_confidence_count = 0
    
    try:
        if not api_key:
            print("WARNING: No STACKEXCHANGE_API_KEY set. Using anonymous quota (300/day).")
            print("Register at https://stackapps.com/apps/oauth/register for 10,000/day quota.")
        
        print(f"Fetching questions from {site} (up to {max_pages} pages)...")
        
        for page in range(1, max_pages + 1):
            # Fetch questions from Software Recommendations with pagination
            params = {
                "site": site,
                "order": "desc",
                "sort": "creation",
                "pagesize": 100,
                "page": page,
                "filter": "withbody",  # Include question body
                "key": api_key
            }
            
            response = requests.get(f"{base_url}/questions", params=params)
            response.raise_for_status()
            data = response.json()
            
            questions = data.get("items", [])
            if not questions:
                print(f"  Page {page}: No more questions")
                break
            
            print(f"  Page {page}: Found {len(questions)} questions")
            
            for question in questions:
                question_id = question.get("question_id")
                title = question.get("title", "")
                body = question.get("body", "")
                creation_date = datetime.fromtimestamp(question.get("creation_date"))
                view_count = question.get("view_count", 0)
                score = question.get("score", 0)
                accepted_answer_id = question.get("accepted_answer_id")
                answer_count = question.get("answer_count", 0)
                
                # Apply rolling 3-year filter
                if creation_date < min_date:
                    skipped_count += 1
                    continue
                
                # Skip questions less than 1 month old
                if datetime.utcnow() - creation_date < timedelta(days=min_question_age_days):
                    skipped_count += 1
                    continue
                
                # Filter heuristic: reject if need is likely already met
                if accepted_answer_id:
                    # Has accepted answer - need is likely met
                    skipped_count += 1
                    continue
                
                # Check if any answer has meaningfully higher score than question
                # This would indicate a good solution exists
                if answer_count > 0:
                    # Fetch answers to check scores
                    answers_params = {
                        "site": site,
                        "order": "desc",
                        "sort": "votes",
                        "pagesize": 10,
                        "key": api_key
                    }
                    answers_response = requests.get(f"{base_url}/questions/{question_id}/answers", params=answers_params)
                    if answers_response.status_code == 200:
                        answers_data = answers_response.json()
                        answers = answers_data.get("items", [])
                        for answer in answers:
                            answer_score = answer.get("score", 0)
                            if answer_score > score + 2:
                                # Good answer exists - skip
                                skipped_count += 1
                                break
                        else:
                            # No good answer found - continue processing
                            pass
                    else:
                        # Failed to fetch answers - skip to be safe
                        skipped_count += 1
                        continue
                else:
                    # No answers - potential gap
                    pass
                
                # Determine confidence level based on view count
                if view_count >= high_confidence_view_count:
                    confidence_flag = "high"
                    high_confidence_count += 1
                else:
                    confidence_flag = "low"
                    low_confidence_count += 1
                
                # Build source URL
                source_url = f"https://softwarerecs.stackexchange.com/questions/{question_id}"
                
                # Check for duplicates
                existing = get_raw_idea_by_url(db, source_url)
                if existing:
                    print(f"    Skipping (already exists)")
                    skipped_count += 1
                    continue
                
                # Build raw_text
                raw_text = f"QUESTION: {title}\n\n"
                raw_text += f"QUESTION URL: {source_url}\n\n"
                raw_text += f"QUESTION BODY: {body}\n\n"
                raw_text += f"METADATA: Score={score}, Views={view_count}, Answers={answer_count}"
                
                # Store in raw_ideas
                idea = create_raw_idea(
                    db,
                    source="stackexchange_softwarerecs",
                    source_url=source_url,
                    raw_title=title,
                    raw_text=raw_text,
                    author=question.get("owner", {}).get("display_name", "Unknown")
                )
                
                # Update with metadata
                from db.models import RawIdea
                db.query(RawIdea).filter(RawIdea.id == idea.id).update({
                    "source_date": creation_date,
                    "matched_keyword": f"softwarerecs_question",
                    "confidence_flag": confidence_flag
                })
                db.commit()
                
                print(f"    [OK] Stored: ID {question_id} (confidence: {confidence_flag})")
                processed_count += 1
        
        print(f"\n=== Summary ===")
        print(f"Processed successfully: {processed_count}")
        print(f"Skipped (already exists/filtered): {skipped_count}")
        print(f"High confidence candidates: {high_confidence_count}")
        print(f"Low confidence candidates: {low_confidence_count}")
        
    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
    finally:
        db.close()
    
    return processed_count

if __name__ == "__main__":
    fetch_softwarerecs_ideas()
