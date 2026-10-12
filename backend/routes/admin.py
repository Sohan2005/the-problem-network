import hmac
import os
from typing import Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from db.database import get_db
from db.queries import (
    attach_tag_to_brief,
    create_brief,
    create_problem,
    get_or_create_tag,
    get_problem_by_url,
)
from ingestion.blog_ingest import fetch_multiple_blog_posts
from ingestion.devpost_ingest import fetch_hackathon_challenges
from ingestion.github_ingest import fetch_good_first_issues
from llm.translate import translate_issue_to_brief


def require_admin(x_admin_key: Optional[str] = Header(default=None)) -> None:
    """Reject the request unless X-Admin-Key matches ADMIN_API_KEY."""
    expected = os.getenv("ADMIN_API_KEY")
    provided = x_admin_key or ""
    if not expected or not hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Unauthorized")


router = APIRouter(prefix="/briefs", dependencies=[Depends(require_admin)])


@router.post("/ingest/{repo:path}")
def ingest_repo(repo: str, db: Session = Depends(get_db)):
    issues = fetch_good_first_issues(repo)
    results = []

    for issue in issues:
        existing = get_problem_by_url(db, issue["html_url"])
        if existing:
            continue

        problem = create_problem(db, "github", issue["title"], issue["body"], issue["html_url"])

        try:
            brief_data = translate_issue_to_brief(issue["title"], issue["body"], issue["html_url"])
            brief = create_brief(
                db,
                problem.id,
                brief_data["title"],
                brief_data["difficulty"],
                brief_data["core_task"],
                brief_data["recommended_stack"]
            )

            for tag_name in brief_data["tags"]:
                tag = get_or_create_tag(db, tag_name)
                attach_tag_to_brief(db, brief.id, tag.id)

            results.append({"title": issue["title"], "status": "success"})
        except ValueError as e:
            results.append({"title": issue["title"], "status": "failed", "error": str(e)})

    return {"results": results}


@router.post("/ingest-devpost")
def ingest_devpost(search_term: Optional[str] = Query(None), db: Session = Depends(get_db)):
    challenges = fetch_hackathon_challenges(search_term=search_term if search_term else "")
    brief_ids = []

    for challenge in challenges:
        if not challenge["html_url"]:
            continue

        existing = get_problem_by_url(db, challenge["html_url"])
        if existing:
            continue

        problem = create_problem(db, "devpost", challenge["title"], challenge["body"], challenge["html_url"])

        try:
            brief_data = translate_issue_to_brief(challenge["title"], challenge["body"], challenge["html_url"])
            brief = create_brief(
                db,
                problem.id,
                brief_data["title"],
                brief_data["difficulty"],
                brief_data["core_task"],
                brief_data["recommended_stack"]
            )

            for tag_name in brief_data["tags"]:
                tag = get_or_create_tag(db, tag_name)
                attach_tag_to_brief(db, brief.id, tag.id)

            brief_ids.append(brief.id)
        except ValueError:
            continue

    return {"ingested_source": "devpost", "briefs_created": brief_ids}


@router.post("/ingest-blogs")
def ingest_blogs(urls: list[str] = Body(...), db: Session = Depends(get_db)):
    blog_posts = fetch_multiple_blog_posts(urls)
    brief_ids = []

    for post in blog_posts:
        existing = get_problem_by_url(db, post["html_url"])
        if existing:
            continue

        problem = create_problem(db, "blog", post["title"], post["body"], post["html_url"])

        try:
            brief_data = translate_issue_to_brief(post["title"], post["body"], post["html_url"])
            brief = create_brief(
                db,
                problem.id,
                brief_data["title"],
                brief_data["difficulty"],
                brief_data["core_task"],
                brief_data["recommended_stack"]
            )

            for tag_name in brief_data["tags"]:
                tag = get_or_create_tag(db, tag_name)
                attach_tag_to_brief(db, brief.id, tag.id)

            brief_ids.append(brief.id)
        except ValueError:
            continue

    return {"ingested_source": "blog", "briefs_created": brief_ids}
