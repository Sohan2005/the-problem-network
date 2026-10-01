import requests
from bs4 import BeautifulSoup
from requests.exceptions import HTTPError

def fetch_blog_post(url: str):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    
    soup = BeautifulSoup(response.text, "html.parser")
    
    title_tag = soup.find("h1")
    if title_tag:
        title = title_tag.get_text().strip()
    else:
        title_tag = soup.find("title")
        title = title_tag.get_text().strip() if title_tag else ""
    
    paragraphs = soup.find_all("p")
    body = " ".join([p.get_text().strip() for p in paragraphs])
    body = body[:8000]
    
    return {
        "title": title,
        "body": body,
        "html_url": url
    }

def fetch_multiple_blog_posts(urls: list[str]):
    results = []
    for url in urls:
        try:
            result = fetch_blog_post(url)
            results.append(result)
        except HTTPError:
            continue
    return results
