import json
import re

from llm.gemini import GeminiClient

def generate_embedding(text):
    """Generate embedding for text with gemini-embedding-001 (3072 dimensions)"""
    return GeminiClient().embed(text)

def translate_issue_to_brief(title, body, source_url):
    model = GeminiClient("gemini-3.5-flash-lite")
    
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
    
    response_text = model.generate(system_prompt + "\n\n" + prompt).strip()
    
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

FORUM_MODEL = "gemini-3.5-flash-lite"

GETTING_STARTED_FIELDS = ("what_youll_need", "how_to_begin")

GETTING_STARTED_RULES = """GETTING STARTED (required for every valid or rescoped idea, tailored to that idea's suggested_tech_stack and features):
- what_youll_need: one string of exactly 3 lines separated by "\\n", each line starting with "- ". Name the concrete tools a student needs before writing code: a browser and/or code editor (e.g. VS Code), the language runtime and package manager of the stack (e.g. Node.js and npm, Python and pip), Git, and any free account or API key the idea truly requires.
- how_to_begin: one string of exactly 3 lines separated by "\\n", numbered "1. ", "2. ", "3. ". Step 1 initializes the project with the stack's tooling, step 2 builds the data/storage layer, step 3 builds the core UI or logic. Refer to the idea's own data and features, not generic placeholders.
These lines may name common general-purpose tools (code editor, browser, Git, the stack's runtime) even when the source text is short.
Example what_youll_need: "- A code editor such as VS Code and a modern web browser\\n- Node.js and npm installed locally\\n- Git for version control"
Example how_to_begin: "1. Initialize a Vite + React project with npm and set up the folder structure.\\n2. Define a localStorage-backed store for routes and sends with add, update and delete helpers.\\n3. Build the route list and the form to log a sent route, wired to the store."
"""

FORUM_SYSTEM_PROMPT = """You are analyzing forum posts (Hacker News, Reddit, etc.) to extract buildable app/website ideas for student portfolio projects. Your task is to determine if the post contains a valid, buildable idea and extract structured information.

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

If is_valid_idea is false, set all other fields to null (title, problem_summary, target_user, what_youll_need, how_to_begin) or empty arrays (suggested_features, suggested_tech_stack, learning_outcomes) — do not invent placeholder content for a rejected idea.

SECOND, check if the idea is valid but too large/complex for a student portfolio project. Set is_valid_idea="needs_rescope" if the idea requires:
- Payment processing, financial transactions, or marketplace logic
- Enterprise infrastructure integration (university IT systems, corporate authentication)
- Browser/engine development, operating system components, or low-level systems programming
- Multi-sided platform dynamics (matching buyers/sellers, complex network effects)
- Large-scale data processing or ML infrastructure

If is_valid_idea="needs_rescope", provide:
- original_ask: Brief description of the original scope from the source text
- rescoped_version: A trimmed-down, realistically student-buildable alternative with the same structure as a normal brief (title, problem_summary, target_user, suggested_features, difficulty_estimate, suggested_tech_stack, learning_outcomes, what_youll_need, how_to_begin); its what_youll_need and how_to_begin follow the GETTING STARTED rules below for the rescoped project
- rescope_reason: One sentence explaining what was cut (e.g., "removed payment processing", "removed university IT integration")

If the post passes all rejection criteria AND is appropriately scoped for a student project, set is_valid_idea=true and extract these fields:

- title: Concise, descriptive title for the project idea
- problem_summary: What problem does this solve? What pain point does it address?
- target_user: Who would use this? What demographic or use case?
- suggested_features: List key features this app/website should have (can be 1-5 items based on source detail)
- difficulty_estimate: "beginner", "intermediate", or "advanced" for a student developer
- suggested_tech_stack: List appropriate technologies (can be 1-5 items based on source detail)
- learning_outcomes: List skills a student would learn building this (can be 1-5 items based on source detail)
- what_youll_need: 3 "- " lines of prerequisites, see GETTING STARTED below
- how_to_begin: 3 numbered first steps, see GETTING STARTED below
- source_url: The original forum post URL (provided in input)
- source_platform: "hackernews", "reddit", or "indiehackers" (provided in input)

""" + GETTING_STARTED_RULES + """
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
    "what_youll_need": "- line\\n- line\\n- line",
    "how_to_begin": "1. step\\n2. step\\n3. step"
  } or null,
  "rescope_reason": string or null,
  "title": string or null,
  "problem_summary": string or null,
  "target_user": string or null,
  "suggested_features": [string] or [],
  "difficulty_estimate": "beginner|intermediate|advanced" or null,
  "suggested_tech_stack": [string] or [],
  "learning_outcomes": [string] or [],
  "what_youll_need": "- line\\n- line\\n- line" or null (null only when is_valid_idea is false or "needs_rescope"),
  "how_to_begin": "1. step\\n2. step\\n3. step" or null (null only when is_valid_idea is false or "needs_rescope"),
  "source_url": string or null,
  "source_platform": string or null
}
Do not include any markdown, explanations, or text outside the JSON."""

def build_forum_prompt(raw_text, source_url, source_platform):
    """Full prompt text (system instructions + item) for forum idea extraction"""
    prompt = f"""Raw Text: {raw_text}
Source URL: {source_url}
Source Platform: {source_platform}

Extract and validate this forum idea following the system instructions."""
    return FORUM_SYSTEM_PROMPT + "\n\n" + prompt

_LINE_PREFIX = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)](?!\d))\s*")

def _lines(value) -> list:
    items = value if isinstance(value, list) else value.splitlines() if isinstance(value, str) else []
    lines = (_LINE_PREFIX.sub("", str(item)).strip() for item in items)
    return [line for line in lines if line]

def format_what_youll_need(value):
    """Lines (string or list, any bullet or numbering) as "- " lines; None when empty."""
    return "\n".join(f"- {line}" for line in _lines(value)) or None

def format_how_to_begin(value):
    """Lines (string or list, any bullet or numbering) as "1. ", "2. ", ... lines; None when empty."""
    return "\n".join(f"{i}. {line}" for i, line in enumerate(_lines(value), 1)) or None

def normalize_getting_started(fields: dict) -> dict:
    """Formats fields' what_youll_need and how_to_begin in place and returns fields."""
    fields["what_youll_need"] = format_what_youll_need(fields.get("what_youll_need"))
    fields["how_to_begin"] = format_how_to_begin(fields.get("how_to_begin"))
    return fields

def missing_getting_started(fields: dict) -> list:
    return [name for name in GETTING_STARTED_FIELDS if not fields.get(name)]

def _load_json(response_text):
    response_text = response_text.strip()
    
    if response_text.startswith("```json"):
        response_text = response_text[7:]
    if response_text.startswith("```"):
        response_text = response_text[3:]
    if response_text.endswith("```"):
        response_text = response_text[:-3]
    response_text = response_text.strip()
    
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        raise ValueError("Invalid JSON response from Gemini")

def parse_forum_response(response_text):
    """
    Parse and validate the model's JSON reply; raises ValueError on malformed output.
    Valid ideas must carry what_youll_need and how_to_begin, needs_rescope ideas inside rescoped_version;
    both are normalized to "- " and "1. " lines.
    """
    idea = _load_json(response_text)
    if not isinstance(idea, dict):
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
    
    if idea["is_valid_idea"] is True:
        target, prefix = idea, ""
    elif idea["is_valid_idea"] == "needs_rescope":
        if not isinstance(idea["rescoped_version"], dict):
            raise ValueError("Missing rescoped_version for needs_rescope idea")
        target, prefix = idea["rescoped_version"], "rescoped_version."
    else:
        return idea
    missing = missing_getting_started(normalize_getting_started(target))
    if missing:
        raise ValueError("Missing getting started field(s): " + ", ".join(prefix + name for name in missing))
    return idea

GETTING_STARTED_SYSTEM_PROMPT = """You write the Getting Started section of a student portfolio project brief.

""" + GETTING_STARTED_RULES + """
Return ONLY valid JSON in this exact shape:
{"what_youll_need": "- line\\n- line\\n- line", "how_to_begin": "1. step\\n2. step\\n3. step"}
Do not include any markdown, explanations, or text outside the JSON."""

def build_getting_started_prompt(title, problem_summary, tech_stack, features=None):
    """Prompt for the Getting Started fields of an existing brief (same GETTING_STARTED_RULES as extraction)."""
    def joined(value):
        return ", ".join(str(v) for v in value) if isinstance(value, list) else (value or "")
    prompt = f"""Title: {title}
Problem Summary: {problem_summary}
Suggested Tech Stack: {joined(tech_stack)}
Suggested Features: {joined(features)}

Write the Getting Started fields for this project following the system instructions."""
    return GETTING_STARTED_SYSTEM_PROMPT + "\n\n" + prompt

def parse_getting_started_response(response_text) -> dict:
    """{"what_youll_need", "how_to_begin"} normalized; raises ValueError when malformed or either is missing."""
    reply = _load_json(response_text)
    if not isinstance(reply, dict):
        raise ValueError("Invalid JSON response from Gemini")
    fields = normalize_getting_started({name: reply.get(name) for name in GETTING_STARTED_FIELDS})
    missing = missing_getting_started(fields)
    if missing:
        raise ValueError("Missing getting started field(s): " + ", ".join(missing))
    return fields

def translate_forum_idea(raw_text, source_url, source_platform):
    """Extract structured idea from forum post with rejection gate and rescope option"""
    model = GeminiClient(FORUM_MODEL)
    return parse_forum_response(model.generate(build_forum_prompt(raw_text, source_url, source_platform)))
