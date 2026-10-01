import os
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

def fetch_good_first_issues(repo: str, per_page: int = 10):
    url = f"https://api.github.com/repos/{repo}/issues"
    headers = {}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    
    # Calculate date 180 days ago
    cutoff_date = datetime.now() - timedelta(days=180)
    
    params = {
        "labels": "good first issue",
        "state": "open",
        "since": cutoff_date.isoformat(),
        "per_page": per_page
    }
    
    # Print the query string for verification
    query_string = "&".join([f"{k}={v}" for k, v in params.items()])
    print(f"GitHub API Query: {url}?{query_string}")
    
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    
    issues = []
    for issue in response.json():
        if "pull_request" in issue:
            continue
        
        # Skip issues with body under 100 characters
        body = issue["body"] or ""
        if len(body) < 100:
            print(f"Skipping issue (body too short): {issue['title']} ({len(body)} chars)")
            continue
        
        issues.append({
            "title": issue["title"],
            "body": body,
            "html_url": issue["html_url"],
            "labels": [label["name"] for label in issue["labels"]]
        })
    
    return issues
