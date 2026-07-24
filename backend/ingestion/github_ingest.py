import os
import requests
from dotenv import load_dotenv

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

def fetch_good_first_issues(repo: str, per_page: int = 10):
    url = f"https://api.github.com/repos/{repo}/issues"
    headers = {}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    
    params = {
        "labels": "good first issue",
        "state": "open",
        "per_page": per_page
    }
    
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    
    issues = []
    for issue in response.json():
        if "pull_request" in issue:
            continue
        issues.append({
            "title": issue["title"],
            "body": issue["body"],
            "html_url": issue["html_url"],
            "labels": [label["name"] for label in issue["labels"]]
        })
    
    return issues
