import os
import json
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)

def translate_issue_to_brief(title, body, source_url):
    model = genai.GenerativeModel("gemini-2.5-flash-lite")
    
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
