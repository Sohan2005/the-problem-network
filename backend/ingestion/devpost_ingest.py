import requests

def fetch_hackathon_challenges(search_term: str = "", per_page: int = 10):
    url = "https://devpost.com/api/hackathons"
    params = {
        "status[]": "open",
        "per_page": per_page
    }
    if search_term:
        params["search"] = search_term
    
    response = requests.get(url, params=params)
    response.raise_for_status()
    
    challenges = []
    for hackathon in response.json().get("hackathons", []):
        body_parts = []
        if hackathon.get("tagline"):
            body_parts.append(hackathon["tagline"])
        if hackathon.get("themes"):
            body_parts.append("Themes: " + ", ".join(hackathon["themes"]))
        if hackathon.get("prize_amount"):
            body_parts.append(f"Prize: {hackathon['prize_amount']}")
        
        challenges.append({
            "title": hackathon.get("title", ""),
            "body": " | ".join(body_parts),
            "html_url": hackathon.get("url", ""),
            "labels": hackathon.get("themes", [])
        })
    
    return challenges
