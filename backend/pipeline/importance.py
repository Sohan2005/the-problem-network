"""
Real-world importance of a published brief: how much the underlying problem matters to the people who face it.

One LLM call per brief scores severity, frequency and reach (each 0-2); the level is computed here, not by the model:
- high:     severity 2 and frequency + reach >= 2
- medium:   severity 1 and frequency + reach >= 2, or severity 2 otherwise
- everyday: everything else
Briefs from AI_SOURCES are capped at medium (no real person reported the problem). Source engagement is not used.

run_importance rates briefs whose importance is NULL, newest first, at most max_items per run, with at most
MAX_ATTEMPTS failed attempts per brief (counted in importance_detail; the brief stays unrated). A quota error stops
the run at once without counting an attempt and logs it as 'warn' with the note 'quota'. Only briefs.importance and
briefs.importance_detail are written. Each run logs one pipeline_runs row with stage STAGE.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

from sqlalchemy import Integer, func

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.models import Brief, PipelineRun, Problem, RawIdea
from llm.gemini import GENERATION_MODEL, GeminiClient, QuotaExhausted
from pipeline.ingest import ERROR_MAX, safe_error
from pipeline.publish import AI_SOURCES

STAGE = "importance"
QUOTA_NOTE = "quota"
LEVELS = ("high", "medium", "everyday")
MAX_ATTEMPTS = 3
CALL_INTERVAL_SECONDS = 5
REASON_MAX = 200

PROMPT = """You rate how much a real-world problem matters to the people who face it. Judge the underlying problem, not the proposed app, its difficulty or the writing quality.

Score three factors, each 0, 1 or 2:
- severity: the cost of leaving the problem unsolved.
  0 = an inconvenience, or a nicer or faster way to do something people already manage (examples: organizing saved videos, converting image formats, a better terminal or file viewer).
  1 = a real, noticeable cost: hours lost every month, money regularly wasted, or work that regularly goes wrong (examples: missed meetings across time zones, unexpected API bills).
  2 = puts income, significant money, health, safety, important data or legal standing at risk, or blocks people from working (examples: finding a job, failed customer payments, medical costs, selling a home, tax mistakes).
- frequency: how often the affected people run into it. 0 = occasionally or once; 1 = weekly or monthly; 2 = daily or continuously.
- reach: how many people face it. 0 = a small niche; 1 = a sizable professional or hobby group; 2 = the general public or a very large group.
Score each factor on its own: a rare but costly problem still gets its full severity. When unsure between two scores, choose the lower one.

Return ONLY JSON: {{"severity": 0, "frequency": 0, "reach": 0, "reason": "at most 20 words"}}

Title: {title}
Who faces it: {target_user}
Problem: {problem}
Core task: {core_task}"""


def default_client():
    return GeminiClient(generation_config={"response_mime_type": "application/json", "temperature": 0})


def importance_level(severity: int, frequency: int, reach: int, ai_suggested: bool = False) -> str:
    if severity == 2 and frequency + reach >= 2:
        level = "high"
    elif (severity == 1 and frequency + reach >= 2) or severity == 2:
        level = "medium"
    else:
        level = "everyday"
    return "medium" if ai_suggested and level == "high" else level


def build_prompt(title, target_user, problem, core_task) -> str:
    return PROMPT.format(title=title or "", target_user=target_user or "unknown",
                         problem=problem or core_task or "", core_task=core_task or "")


def parse_rating(text) -> dict:
    """{severity, frequency, reach, reason} from the model reply; ValueError unless each factor is an integer 0-2."""
    body = (text or "").strip()
    if body.startswith("```"):
        body = body.strip("`").removeprefix("json").strip()
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError("rating is not a JSON object")
    scores = {}
    for key in ("severity", "frequency", "reach"):
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value not in (0, 1, 2):
            raise ValueError(f"invalid {key}: {value!r}")
        scores[key] = value
    reason = data.get("reason")
    scores["reason"] = reason[:REASON_MAX] if isinstance(reason, str) else ""
    return scores


def rate(row, llm_client) -> tuple:
    """(level, scores) for a row with title, target_user, problem_summary, core_task and source."""
    scores = parse_rating(llm_client.generate(build_prompt(row.title, row.target_user, row.problem_summary, row.core_task)))
    return importance_level(scores["severity"], scores["frequency"], scores["reach"], row.source in AI_SOURCES), scores


def _attempts():
    return func.coalesce(Brief.importance_detail["attempts"].astext.cast(Integer), 0)


def unrated_rows(db, max_items: int) -> list:
    """Unrated briefs with fewer than MAX_ATTEMPTS failed attempts, newest first, with the fields the prompt needs."""
    return (
        db.query(Brief.id, Brief.title, Brief.target_user, Brief.core_task, RawIdea.problem_summary,
                 func.coalesce(RawIdea.source, Problem.source).label("source"), _attempts().label("attempts"))
        .outerjoin(RawIdea, RawIdea.id == Brief.raw_idea_id)
        .outerjoin(Problem, Problem.id == Brief.problem_id)
        .filter(Brief.importance.is_(None), _attempts() < MAX_ATTEMPTS)
        .order_by(Brief.created_at.desc(), Brief.id.desc())
        .limit(max_items)
        .all()
    )


def rated_values(row, level: str, scores: dict, model: str, now: datetime) -> dict:
    return {"importance": level, "importance_detail": {
        **scores, "ai_suggested": row.source in AI_SOURCES, "model": model, "rated_at": now.isoformat(),
        "attempts": row.attempts + 1}}


def failed_values(row, error: str) -> dict:
    return {"importance_detail": {"attempts": row.attempts + 1, "last_error": error}}


def store(db, brief_id: int, values: dict):
    db.query(Brief).filter(Brief.id == brief_id).update(values, synchronize_session=False)
    db.commit()


def run_importance(db, llm_client, max_items: int, budget_seconds: float, now=None) -> dict:
    """Rate up to max_items unrated briefs within budget_seconds; one failing brief never stops the run."""
    deadline = time.monotonic() + budget_seconds
    started_at = datetime.now(timezone.utc)
    model = getattr(llm_client, "model_name", GENERATION_MODEL)
    summary = {"attempted": 0, "rated": 0, "failed": 0, "levels": {level: 0 for level in LEVELS},
               "stopped_by_budget": False, "quota": False}
    status, error, last_item_error = "ok", None, None
    try:
        for index, row in enumerate(unrated_rows(db, max_items)):
            if index and CALL_INTERVAL_SECONDS:
                time.sleep(max(0.0, min(CALL_INTERVAL_SECONDS, deadline - time.monotonic())))
            if time.monotonic() >= deadline:
                summary["stopped_by_budget"] = True
                break
            summary["attempted"] += 1
            try:
                level, scores = rate(row, llm_client)
            except QuotaExhausted:
                summary["attempted"] -= 1
                summary["quota"] = True
                break
            except Exception as e:
                last_item_error = safe_error(e)
                store(db, row.id, failed_values(row, last_item_error))
                summary["failed"] += 1
                continue
            store(db, row.id, rated_values(row, level, scores, model, now or datetime.now(timezone.utc)))
            summary["rated"] += 1
            summary["levels"][level] += 1
    except Exception as e:
        db.rollback()
        status, error = "error", safe_error(e)

    if error is None and summary["failed"]:
        error = f"{summary['failed']} item(s) failed; last: {last_item_error}"[:ERROR_MAX]
    if status == "ok" and summary["quota"]:
        status, error = "warn", QUOTA_NOTE if error is None else f"{QUOTA_NOTE}; {error}"[:ERROR_MAX]
    db.add(PipelineRun(stage=STAGE, started_at=started_at, finished_at=datetime.now(timezone.utc),
                       rows_in=summary["attempted"], rows_out=summary["rated"], status=status, error=error))
    db.commit()
    return {"status": status, "error": error, **summary}
