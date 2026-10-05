import os
import sys
import json
from datetime import datetime
from dotenv import load_dotenv
import google.generativeai as genai

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env from project root (relative to this script)
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
env_path = os.path.join(project_root, '.env')
load_dotenv(env_path)

from db.database import SessionLocal
from db.queries import insert_raw_ideas

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)

# Rotating general prompts for web grounding
GROUNDING_PROMPTS = [
    "What problems do people commonly complain don't have a good software/app solution?",
    "What tools do people wish existed for productivity?",
    "What tools do people wish existed for home management?",
    "What tools do people wish existed for fitness?",
    "What tools do people wish existed for developer tools?",
    "What tools do people wish existed for education?",
    "What repeated complaints do people have about missing features in existing apps?",
    "What software solutions do people say are missing for small businesses?",
    "What app ideas do people frequently suggest but don't exist yet?",
    "What problems do students face that don't have good software solutions?"
]

RECENCY_INSTRUCTION = """
Only include problems, complaints, or requests that are current and were raised within the last 3 years. 
Do not include anything older than 3 years — if a result's age is unclear or cannot be reasonably confirmed as recent, exclude it rather than including it anyway.
"""

def fetch_grounding_ideas(prompt_index=0, max_ideas_per_prompt=10):
    """
    Fetch ideas from web grounding using Gemini's Google Search.
    Returns list of ideas with source URLs and citations.
    """
    prompt = GROUNDING_PROMPTS[prompt_index % len(GROUNDING_PROMPTS)]
    
    # Configure model with search grounding
    model = genai.GenerativeModel("gemini-3.5-flash-lite")
    
    system_prompt = """You are searching the web for app/software idea requests. Use Google Search to find what problems people complain about not having good solutions for.

Break your findings into a JSON list of DISTINCT, INDIVIDUAL ideas. Each idea should be:
- A specific, buildable app/website concept
- Based on real complaints or requests you find in search results
- Not a duplicate of another idea in your list

For each idea, provide:
- title: Concise title for the app/website idea
- description: What problem does it solve? What pain point does it address?
- source_url: The specific URL where you found this idea/request (Reddit, Quora, blog, forum, etc.)
- source_domain: The domain name of the source (e.g., reddit.com, quora.com, medium.com)
- confidence: "high" if the source is a clear idea request, "low" if it's vague or indirect
- publish_date: The publish/post date if available from the source (YYYY-MM-DD format), or null if not found

Return ONLY valid JSON in this exact shape:
{
  "ideas": [
    {
      "title": string,
      "description": string,
      "source_url": string,
      "source_domain": string,
      "confidence": "high" or "low",
      "publish_date": string or null
    }
  ]
}

""" + RECENCY_INSTRUCTION + """

Do not include any markdown, explanations, or text outside the JSON."""
    
    try:
        # Use generate_content with search grounding enabled
        response = model.generate_content(
            system_prompt + "\n\n" + prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.7,
                top_p=0.8,
                top_k=40
            )
        )
        
        response_text = response.text.strip()
        
        # Clean up JSON response
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
        response_text = response_text.strip()
        
        data = json.loads(response_text)
        ideas = data.get("ideas", [])
        
        # Limit to max_ideas_per_prompt
        return ideas[:max_ideas_per_prompt]
        
    except Exception as e:
        print(f"Error fetching grounding ideas: {e}")
        return []

def store_grounding_ideas(ideas, prompt_index):
    """
    Store grounding ideas in raw_ideas table through the shared writer.
    Returns (stored, skipped); skipped covers duplicates and rejected items.
    """
    items = []
    for idea in ideas:
        if not isinstance(idea, dict):
            items.append(idea)  # rejected by insert_raw_ideas
            continue
        publish_date_str = idea.get("publish_date", None)
        
        # Parse publish_date if available
        source_date = None
        if publish_date_str:
            try:
                source_date = datetime.strptime(publish_date_str, "%Y-%m-%d")
            except (ValueError, TypeError):
                # Invalid date format, keep as null
                pass
        
        items.append({
            "source": "web_grounding",
            "source_url": idea.get("source_url", ""),
            "raw_title": idea.get("title", ""),
            "raw_text": idea.get("description", ""),
            "confidence_flag": idea.get("confidence", "low"),
            "source_date": source_date,
        })
    
    db = SessionLocal()
    try:
        result = insert_raw_ideas(db, items)
    except Exception as e:
        print(f"Error storing grounding ideas: {type(e).__name__}")
        return 0, 0
    finally:
        db.close()
    
    stored_count = result["inserted"]
    skipped_count = result["skipped_duplicate"] + len(result["rejected"])
    print(f"Stored {stored_count} ideas from prompt {prompt_index}")
    print(f"Skipped {skipped_count} ideas (duplicates, missing fields or out-of-range dates)")
    
    return stored_count, skipped_count

def run_grounding_ingestion(num_prompts=5, max_ideas_per_prompt=10):
    """
    Run web grounding ingestion with rotating prompts.
    Budget: ~150 grounded queries/day (num_prompts * max_ideas_per_prompt)
    """
    print(f"Starting web grounding ingestion with {num_prompts} prompts...")
    
    total_stored = 0
    total_skipped = 0
    
    for i in range(num_prompts):
        print(f"\n--- Prompt {i + 1}/{num_prompts} ---")
        print(f"Query: {GROUNDING_PROMPTS[i % len(GROUNDING_PROMPTS)]}")
        
        ideas = fetch_grounding_ideas(i, max_ideas_per_prompt)
        print(f"Fetched {len(ideas)} ideas from grounding")
        
        stored, skipped = store_grounding_ideas(ideas, i)
        total_stored += stored
        total_skipped += skipped
        
        # Rate limit between prompts
        if i < num_prompts - 1:
            import time
            time.sleep(2)
    
    print(f"\n=== Web Grounding Ingestion Complete ===")
    print(f"Total stored: {total_stored}")
    print(f"Total skipped: {total_skipped}")
    print(f"Total queries used: {num_prompts}")
    print(f"Budget remaining: ~{5000 - num_prompts} queries this month")

if __name__ == "__main__":
    # Run with 5 prompts (50 ideas max) for test batch
    run_grounding_ingestion(num_prompts=5, max_ideas_per_prompt=10)
