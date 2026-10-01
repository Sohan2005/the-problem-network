import os
import sys
import requests
from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import SessionLocal
from db.queries import create_raw_idea, get_raw_idea_by_url

# Load .env from project root (relative to this script)
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
env_path = os.path.join(project_root, '.env')
load_dotenv(env_path)

def fetch_hn_ideas_via_context_stitching():
    """
    Context-Stitching Architecture for HN Idea Discovery:
    STEP A: Algolia Search API for keyword matching
    STEP B: Use Algolia's built-in story_title/story_url (no Firebase needed for basic context)
    STEP C: Store structured context in raw_ideas table
    """
    
    # Keyword buckets - expanded with broader phrasings
    bucket_a = ["would gladly pay", "i would pay monthly", "surprised no one sells", "shut up and take my money", "is there a paid version"]
    bucket_b = ["scratch my own itch", "frustratingly bad", "i ended up writing a script", "why is there no open source alternative", "hate the current options"]
    bucket_c = ["wish there was a tool", "someone should build", "is there a lightweight alternative", "gap in the market"]
    bucket_d = ["someone should build", "is there a tool that", "why doesn't this exist", "looking for an app/tool that", "wish there was a way to"]
    
    all_keywords = bucket_a + bucket_b + bucket_c + bucket_d
    results_limit = 50  # per phrase (increased from 5 for larger candidate pool)
    
    # Search modes: ask_hn only (direct idea requests) - higher signal than comment mining
    search_modes = ["ask_hn"]
    
    # Date filtering: only pull posts from last N years (configurable)
    max_post_age_years = 3  # Configurable: change to 1, 2, 3, etc.
    
    # Calculate Unix timestamp for N years ago
    import time
    current_timestamp = int(time.time())
    seconds_per_year = 365 * 24 * 60 * 60
    min_timestamp = current_timestamp - (max_post_age_years * seconds_per_year)
    
    db = SessionLocal()
    processed_count = 0
    skipped_count = 0
    
    try:
        for search_mode in search_modes:
            for keyword in all_keywords:
                print(f"Searching for: '{keyword}' (mode: {search_mode})")
                
                # STEP A: Algolia Search API with date filtering and show_hn exclusion
                algolia_url = "https://hn.algolia.com/api/v1/search"
                params = {
                    "tags": search_mode,
                    "query": keyword,
                    "hitsPerPage": results_limit,
                    "numericFilters": f"created_at_i>{min_timestamp}",
                    "tagFilters": "-show_hn"  # Exclude Show HN posts (completed projects)
                }
                
                response = requests.get(algolia_url, params=params)
                response.raise_for_status()
                search_results = response.json().get("hits", [])
                
                print(f"  Found {len(search_results)} results")
                
                for hit in search_results:
                    comment_id = hit.get("objectID")
                    comment_text = hit.get("comment_text", "")
                    story_title = hit.get("story_title", "")
                    story_url = hit.get("story_url", "")
                    author = hit.get("author", "")
                    created_at_i = hit.get("created_at_i")  # Unix timestamp of post creation
                    story_text = hit.get("story_text", "")  # For ask_hn posts, use story_text
                    
                    # Skip if no comment text (for comment mode)
                    if search_mode == "comment" and not comment_text:
                        continue
                    
                    # Skip if no story text (for ask_hn mode)
                    if search_mode == "ask_hn" and not story_text:
                        continue
                    
                    # Skip if no story title (invalid entry)
                    if not story_title:
                        continue
                    
                    # STEP B: Build structured raw_text (Algolia already provides story context)
                    if search_mode == "comment":
                        raw_text = f"STORY: {story_title}\n\n"
                        raw_text += f"STORY URL: {story_url}\n\n"
                        raw_text += f"MATCHING COMMENT: {comment_text}"
                    else:  # ask_hn mode - use story_text for post content
                        raw_text = f"STORY: {story_title}\n\n"
                        raw_text += f"STORY URL: {story_url}\n\n"
                        raw_text += f"POST TEXT: {story_text}"
                    
                    # Build source URL (comment permalink)
                    source_url = f"https://news.ycombinator.com/item?id={comment_id}"
                    
                    # Check for duplicates
                    existing = get_raw_idea_by_url(db, source_url)
                    if existing:
                        print(f"    Skipping (already exists)")
                        skipped_count += 1
                        continue
                    
                    # Store in raw_ideas
                    idea = create_raw_idea(
                        db,
                        source="hackernews",
                        source_url=source_url,
                        raw_title=story_title or "Unknown Story",
                        raw_text=raw_text,
                        author=author
                    )
                    
                    # Convert Unix timestamp to datetime and store as source_date
                    from datetime import datetime
                    source_date = None
                    if created_at_i:
                        source_date = datetime.fromtimestamp(created_at_i)
                    
                    # Update matched_keyword and source_date separately
                    from db.models import RawIdea
                    db.query(RawIdea).filter(RawIdea.id == idea.id).update({
                        "matched_keyword": keyword,
                        "source_date": source_date
                    })
                    db.commit()
                    
                    print(f"    [OK] Stored: {story_title[:50]}... (matched: {keyword})")
                    processed_count += 1
                
    finally:
        db.close()
    
    print(f"\n=== Summary ===")
    print(f"Processed successfully: {processed_count}")
    print(f"Skipped (already exists): {skipped_count}")
    
    return processed_count

if __name__ == "__main__":
    fetch_hn_ideas_via_context_stitching()
