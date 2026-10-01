import os
import json
from dotenv import load_dotenv
import google.generativeai as genai
from google import genai as new_genai
from google.genai import types

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)

def generate_embedding(text):
    """Generate embedding for text using new google-genai SDK with gemini-embedding-001"""
    client = new_genai.Client(api_key=GEMINI_API_KEY)
    result = client.models.embed_content(
        model="gemini-embedding-001",
        contents=text,
        config=types.EmbedContentConfig(output_dimensionality=3072)
    )
    # New SDK returns list of ContentEmbedding objects, each with values attribute
    return result.embeddings[0].values

def translate_issue_to_brief(title, body, source_url):
    model = genai.GenerativeModel("gemini-3.5-flash-lite")
    
    system_prompt = """You are a technical problem translator. Convert GitHub issues into structured briefs for junior developers.
Return ONLY valid JSON in this exact shape:
{
    "title": string,
    "difficulty": "Beginner" or "Intermediate" or "Advanced",
    "core_task": string,
    "recommended_stack": string,
    "tags": [string]
}
Do not include any markdown, explanations, or text outside the JSON."""
    
    prompt = f"""Title: {title}
Body: {body}
Source URL: {source_url}

Convert this issue into a brief following the system instructions."""
    
    response = model.generate_content(system_prompt + "\n\n" + prompt)
    response_text = response.text.strip()
    
    if response_text.startswith("```json"):
        response_text = response_text[7:]
    if response_text.startswith("```"):
        response_text = response_text[3:]
    if response_text.endswith("```"):
        response_text = response_text[:-3]
    response_text = response_text.strip()
    
    try:
        brief = json.loads(response_text)
    except json.JSONDecodeError:
        raise ValueError("Invalid JSON response from Gemini")
    
    required_keys = ["title", "difficulty", "core_task", "recommended_stack", "tags"]
    for key in required_keys:
        if key not in brief:
            raise ValueError(f"Missing required key: {key}")
    
    if brief["difficulty"] not in ["Beginner", "Intermediate", "Advanced"]:
        raise ValueError(f"Invalid difficulty value: {brief['difficulty']}")
    
    return brief

def translate_forum_idea(raw_text, source_url, source_platform):
    """Extract structured idea from forum post with rejection gate and rescope option"""
    model = genai.GenerativeModel("gemini-3.5-flash-lite")
    
    system_prompt = """You are analyzing forum posts (Hacker News, Reddit, etc.) to extract buildable app/website ideas for student portfolio projects. Your task is to determine if the post contains a valid, buildable idea and extract structured information.

CRITICAL: When analyzing the source text, PRIORITIZE the main STORY/POST content over any matching comments. If the main story describes an existing product, reject it regardless of what comments say.

FIRST, determine validity by checking these rejection criteria. Set is_valid_idea=false and provide rejection_reason if ANY of these are true:

1. The main story/post describes an already-built, already-shipped, or already-launched product being demoed, pitched, or announced. This includes:
   - Named commercial products or startups being showcased
   - "Show HN", "Launch HN", "I built", "I made", "I created", "We launched", "We built" style posts
   - Product announcements, demos, or marketing pitches
   - Any post where the core message is "look at what I made" rather than "someone should build this"
   - IGNORE matching comments that might suggest ideas - focus on the main story/post
2. No clear target user or use case is stated or reasonably inferable
3. It's a question asking for coding help or technical advice, not an app idea
4. It's generic complaint/venting with no specific buildable concept (e.g., "companies should just take my money" without describing what should be built)
5. The idea is illegal, adult content, or otherwise unsuitable for a student portfolio project

If is_valid_idea is false, set all other fields to null (title, problem_summary, target_user) or empty arrays (suggested_features, suggested_tech_stack, learning_outcomes) — do not invent placeholder content for a rejected idea.

SECOND, check if the idea is valid but too large/complex for a student portfolio project. Set is_valid_idea="needs_rescope" if the idea requires:
- Payment processing, financial transactions, or marketplace logic
- Enterprise infrastructure integration (university IT systems, corporate authentication)
- Browser/engine development, operating system components, or low-level systems programming
- Multi-sided platform dynamics (matching buyers/sellers, complex network effects)
- Large-scale data processing or ML infrastructure

If is_valid_idea="needs_rescope", provide:
- original_ask: Brief description of the original scope from the source text
- rescoped_version: A trimmed-down, realistically student-buildable alternative with the same structure as a normal brief (title, problem_summary, target_user, suggested_features, difficulty_estimate, suggested_tech_stack, learning_outcomes)
- rescope_reason: One sentence explaining what was cut (e.g., "removed payment processing", "removed university IT integration")

If the post passes all rejection criteria AND is appropriately scoped for a student project, set is_valid_idea=true and extract these fields:

- title: Concise, descriptive title for the project idea
- problem_summary: What problem does this solve? What pain point does it address?
- target_user: Who would use this? What demographic or use case?
- suggested_features: List key features this app/website should have (can be 1-5 items based on source detail)
- difficulty_estimate: "beginner", "intermediate", or "advanced" for a student developer
- suggested_tech_stack: List appropriate technologies (can be 1-5 items based on source detail)
- learning_outcomes: List skills a student would learn building this (can be 1-5 items based on source detail)
- what_youll_need: A bulleted list of prerequisites (accounts, tools, local setup, API keys, etc.) needed to start this project
- how_to_begin: A numbered list of the first 2-4 actionable steps to actually start building this project
- source_url: The original forum post URL (provided in input)
- source_platform: "hackernews", "reddit", or "indiehackers" (provided in input)

CRITICAL RULE: If the source text (excluding story/parent context) is under 30 words, you MUST NOT invent specific named technologies, tools, or techniques not explicitly present in the source text. In this case, suggested_tech_stack must either be an empty array [], or contain only broad general categories directly implied by the request (e.g., 'a simple web app' implies ['web development'] — it does NOT imply specific libraries, frameworks, or techniques like 'NLP', 'web scraping libraries', or 'cron jobs' unless the source text explicitly mentions them). The same rule applies to suggested_features and learning_outcomes: for sources under 30 words, limit yourself to 1-2 items maximum, directly restating or minimally elaborating on what the source explicitly says, not inventing implementation approaches.

Base every extracted field ONLY on what is stated or reasonably and conservatively inferable from the source text. Do not invent specific details, feature counts, or technologies not implied by the original post. If the source text is brief, it is acceptable to return fewer than 3 items in suggested_features, suggested_tech_stack, or learning_outcomes (even just 1-2) rather than padding with invented detail to reach a target count. Thin source material should produce a thin (but honest) brief, not a fabricated detailed one.

Return ONLY valid JSON matching this exact schema:
{
  "is_valid_idea": boolean or "needs_rescope",
  "rejection_reason": string or null,
  "original_ask": string or null,
  "rescoped_version": {
    "title": string or null,
    "problem_summary": string or null,
    "target_user": string or null,
    "suggested_features": [string] or [],
    "difficulty_estimate": "beginner|intermediate|advanced" or null,
    "suggested_tech_stack": [string] or [],
    "learning_outcomes": [string] or [],
    "what_youll_need": string or null,
    "how_to_begin": string or null
  } or null,
  "rescope_reason": string or null,
  "title": string or null,
  "problem_summary": string or null,
  "target_user": string or null,
  "suggested_features": [string] or [],
  "difficulty_estimate": "beginner|intermediate|advanced" or null,
  "suggested_tech_stack": [string] or [],
  "learning_outcomes": [string] or [],
  "what_youll_need": string or null,
  "how_to_begin": string or null,
  "source_url": string or null,
  "source_platform": string or null
}
Do not include any markdown, explanations, or text outside the JSON."""
    
    prompt = f"""Raw Text: {raw_text}
Source URL: {source_url}
Source Platform: {source_platform}

Extract and validate this forum idea following the system instructions."""
    
    response = model.generate_content(system_prompt + "\n\n" + prompt)
    response_text = response.text.strip()
    
    if response_text.startswith("```json"):
        response_text = response_text[7:]
    if response_text.startswith("```"):
        response_text = response_text[3:]
    if response_text.endswith("```"):
        response_text = response_text[:-3]
    response_text = response_text.strip()
    
    try:
        idea = json.loads(response_text)
    except json.JSONDecodeError:
        raise ValueError("Invalid JSON response from Gemini")
    
    required_keys = ["is_valid_idea", "rejection_reason", "original_ask", "rescoped_version", "rescope_reason", 
                     "title", "problem_summary", "target_user", "suggested_features", "difficulty_estimate", 
                     "suggested_tech_stack", "learning_outcomes", "source_url", "source_platform"]
    for key in required_keys:
        if key not in idea:
            raise ValueError(f"Missing required key: {key}")
    
    if idea["difficulty_estimate"] not in ["beginner", "intermediate", "advanced", None]:
        raise ValueError(f"Invalid difficulty_estimate value: {idea['difficulty_estimate']}")
    
    if idea["is_valid_idea"] not in [True, False, "needs_rescope"]:
        raise ValueError(f"Invalid is_valid_idea value: {idea['is_valid_idea']}")
    
    return idea
