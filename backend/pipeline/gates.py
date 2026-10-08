"""
Automated quality gates: decide which extracted ideas may enter the ready queue.

Order: eligibility -> structure -> source red flags -> source grounding -> duplicates -> score.
Every gate function is pure and returns (passed, reason, score_part). A reason is "code: detail", several
problems from one gate are joined with "; ". Writes only gate_status, gate_failures, gate_score, gated_at,
duplicate_of_brief_id and (when empty) the row's embedding; never ready_to_publish or published_* columns.

Thresholds are calibrated (2026-10) on the 49 published briefs so all of them pass:
- structure ranges: published title 19-64 chars, problem_summary 85-278, target_user 22-155, features 2-5,
  learning outcomes 2-3, tech stack 1-4; extraction never fills what_youll_need / how_to_begin for
  rescoped ideas, so those are optional.
- lexical overlap of brief title+problem with raw_title+raw_text: published minimum 0.0 for HN (a comment
  paraphrased with no shared word), 0.20 for Stack Exchange, 0.263 for web grounding. Rejected rows have the
  same median (0.44) as published ones, so overlap only screens out briefs unrelated to their source.
- red flags apply to the item's own text (the comment for comment-mode HN rows, whose title and STORY line
  belong to the parent). "i made", "i created", "sign up" and "show hn" inside a body are not flags: they
  occur in published or valid needs.
- duplicates: published briefs never exceed 0.72 cosine similarity to each other and no confirmed duplicate
  exists to calibrate on, so DUPLICATE_THRESHOLD uses the 0.85 default (old scripts rejected above 0.88).

gate_score (0-100) = structure (25) + source confidence (15) + overlap (25) + specificity (20) + recency (15):
- structure:   25 * (complete core fields / 7); core = title, problem_summary, target_user, >=2 features,
               >=2 learning outcomes, >=1 tech, valid difficulty
- confidence:  confidence_flag high 15, missing 10, low 5
- overlap:     25 * min(1, overlap / OVERLAP_FULL_SCORE)
- specificity: 20 * min(1, salient words in title+problem / SPECIFICITY_FULL_SCORE)
- recency:     15 * max(0, 1 - age_days / 1095); 7.5 when source_date is unknown
Within a run, candidates are de-duplicated in score order (higher first; ties: older source_date, then id).
"""
import html
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import numpy as np

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.models import Brief, PipelineRun, RawIdea
from pipeline.ingest import safe_error

STAGE = "gates"
COMMIT_EVERY = 50

VALID_IDEA = ("true", "needs_rescope")
DIFFICULTIES = ("beginner", "intermediate", "advanced")
TITLE_LEN = (10, 120)
PROBLEM_LEN = (60, 600)
TARGET_LEN = (10, 300)
FEATURES_COUNT = (1, 8)
LEARNING_COUNT = (1, 6)
STACK_COUNT = (0, 8)
LIST_ITEM_MAX = 300
OPTIONAL_TEXT_MAX = 3000
PLACEHOLDER = re.compile(r"\b(?:n/a|tbd|tba|lorem|ipsum)\b", re.I)
PLACEHOLDER_VALUES = {"none", "null", "-", "...", "?"}

RED_FLAG_PATTERNS = {
    "i_built": r"\bi (?:just )?built\b",
    "we_built": r"\bwe(?: just|'ve| have)? built\b",
    "we_launched": r"\bwe(?: just|'ve| have)? launched\b",
    "check_out_my": r"\bcheck out (?:my|our)\b",
    "my_startup": r"\bmy (?:startup|saas)\b",
    "hiring": r"\b(?:we(?:'re| are) hiring|now hiring|is hiring)\b",
    "waitlist": r"\b(?:join|sign up for) (?:the|our) wait ?list\b",
    "promo_code": r"\b(?:promo|discount|coupon) code\b",
    "affiliate": r"\baffiliate link\b|[?&](?:ref|aff|affiliate)=",
}
PITCH_TITLE = re.compile(r"^\s*(?:show|launch) hn\b", re.I)
DOMAIN_BLOCKLIST = frozenset()

SOURCE_OVERLAP_MIN = {"stackexchange_softwarerecs": 0.15, "web_grounding": 0.20}
DEFAULT_OVERLAP_MIN = 0.0
FETCH_TIMEOUT_SECONDS = 10

DUPLICATE_THRESHOLD = 0.85

OVERLAP_FULL_SCORE = 0.6
SPECIFICITY_FULL_SCORE = 20
RECENCY_DAYS = 1095

STOP_WORDS = frozenset("""about above after again against all also although always among because been before being below
between both could does doing down during each either else even ever every from further have having here hers herself
himself however into itself just like more most much must neither none once only other ought ours ourselves over same
shall should some such than that their theirs them themselves then there these they this those through under until upon
very want what when where which while whom whose will with within without would your yours yourself yourselves make made
many may might need needs using used able allow allows help helps based simple easy user users people app apps tool
tools""".split())

# --- text helpers ---

def salient_words(text) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) >= 4 and w not in STOP_WORDS}

def overlap(brief_text, source_text) -> float:
    """Share of the brief's salient words that also appear in the source text."""
    words = salient_words(brief_text)
    return len(words & salient_words(source_text)) / len(words) if words else 0.0

def own_text(raw_title, raw_text) -> str:
    """The item's own words: the comment for comment-mode HN rows (title belongs to the parent), else title + body."""
    raw_text = raw_text or ""
    if "MATCHING COMMENT:" in raw_text:
        return raw_text.split("MATCHING COMMENT:", 1)[1]
    match = re.search(r"(?:POST TEXT:|QUESTION BODY:)(.*?)(?:\n\nMETADATA:|$)", raw_text, re.S)
    return f"{raw_title or ''}\n{match.group(1) if match else raw_text}"

def domain(url) -> str:
    return (urlparse(url or "").hostname or "").lower().removeprefix("www.")

def same_domain(a: str, b: str) -> bool:
    return bool(a) and (a == b or a.endswith("." + b) or b.endswith("." + a))

def html_to_text(page: str) -> str:
    page = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", page or "")
    return html.unescape(re.sub(r"(?s)<[^>]+>", " ", page))

# --- candidate ---

def effective_fields(row) -> dict:
    """Brief fields to gate: rescoped_version for needs_rescope, the extracted columns otherwise."""
    if row.is_valid_idea == "needs_rescope":
        rescoped = row.rescoped_version if isinstance(row.rescoped_version, dict) else {}
        get = rescoped.get
    else:
        get = {
            "title": row.extracted_title, "problem_summary": row.problem_summary, "target_user": row.target_user,
            "suggested_features": row.suggested_features, "learning_outcomes": row.learning_outcomes,
            "suggested_tech_stack": row.suggested_tech_stack, "difficulty_estimate": row.difficulty_estimate,
            "what_youll_need": row.what_youll_need, "how_to_begin": row.how_to_begin,
        }.get
    keys = ("title", "problem_summary", "target_user", "suggested_features", "learning_outcomes",
            "suggested_tech_stack", "difficulty_estimate", "what_youll_need", "how_to_begin")
    return {key: get(key) for key in keys}

def brief_text(fields: dict) -> str:
    """Text embedded for duplicate checks; matches what daily_publish stores on briefs."""
    return f"{fields.get('title')} {fields.get('problem_summary')}"

# --- gates ---

def gate_eligibility(row):
    if (row.processed_at is None or row.gate_status != "pending" or row.published_brief_id is not None):
        return False, "not_eligible", 0.0
    if row.is_valid_idea == "false":
        return False, "rejected_by_extraction", 0.0
    if row.is_valid_idea not in VALID_IDEA:
        return False, "not_eligible", 0.0
    return True, None, 0.0

def _check_text(problems, name, value, bounds):
    if not isinstance(value, str) or not value.strip():
        problems.append(f"missing_field: {name}")
    elif not bounds[0] <= len(value.strip()) <= bounds[1]:
        problems.append(f"out_of_range: {name} length {len(value.strip())} not in {bounds[0]}..{bounds[1]}")

def _check_list(problems, name, value, bounds):
    if value is None and bounds[0] == 0:
        return
    if not isinstance(value, list):
        problems.append(f"missing_field: {name}")
    elif not bounds[0] <= len(value) <= bounds[1]:
        problems.append(f"out_of_range: {name} count {len(value)} not in {bounds[0]}..{bounds[1]}")
    elif any(not isinstance(item, str) or not item.strip() or len(item) > LIST_ITEM_MAX for item in value):
        problems.append(f"bad_list_item: {name}")

def _placeholders(fields: dict):
    for name, value in fields.items():
        for text in (value if isinstance(value, list) else [value]):
            if isinstance(text, str) and (PLACEHOLDER.search(text) or text.strip().lower() in PLACEHOLDER_VALUES):
                yield name

def structure_completeness(fields: dict) -> float:
    core = [
        isinstance(fields.get("title"), str) and bool(fields["title"].strip()),
        isinstance(fields.get("problem_summary"), str) and bool(fields["problem_summary"].strip()),
        isinstance(fields.get("target_user"), str) and bool(fields["target_user"].strip()),
        isinstance(fields.get("suggested_features"), list) and len(fields["suggested_features"]) >= 2,
        isinstance(fields.get("learning_outcomes"), list) and len(fields["learning_outcomes"]) >= 2,
        isinstance(fields.get("suggested_tech_stack"), list) and len(fields["suggested_tech_stack"]) >= 1,
        fields.get("difficulty_estimate") in DIFFICULTIES,
    ]
    return sum(core) / len(core)

def gate_structure(fields: dict):
    problems = []
    _check_text(problems, "title", fields.get("title"), TITLE_LEN)
    _check_text(problems, "problem_summary", fields.get("problem_summary"), PROBLEM_LEN)
    _check_text(problems, "target_user", fields.get("target_user"), TARGET_LEN)
    _check_list(problems, "suggested_features", fields.get("suggested_features"), FEATURES_COUNT)
    _check_list(problems, "learning_outcomes", fields.get("learning_outcomes"), LEARNING_COUNT)
    _check_list(problems, "suggested_tech_stack", fields.get("suggested_tech_stack"), STACK_COUNT)
    if fields.get("difficulty_estimate") not in DIFFICULTIES:
        problems.append(f"bad_difficulty: {fields.get('difficulty_estimate')!r}")
    for name in ("what_youll_need", "how_to_begin"):
        value = fields.get(name)
        if value is not None and (not isinstance(value, str) or len(value) > OPTIONAL_TEXT_MAX):
            problems.append(f"out_of_range: {name}")
    problems += [f"placeholder: {name}" for name in dict.fromkeys(_placeholders(fields))]
    return not problems, "; ".join(problems) or None, 25 * structure_completeness(fields)

def gate_red_flags(raw_title, raw_text, source_url):
    problems = []
    own = own_text(raw_title, raw_text)
    if "MATCHING COMMENT:" not in (raw_text or "") and PITCH_TITLE.search(raw_title or ""):
        problems.append("red_flag: show_or_launch_hn_title")
    lowered = own.lower()
    problems += [f"red_flag: {name}" for name, pattern in RED_FLAG_PATTERNS.items() if re.search(pattern, lowered)]
    if domain(source_url) in DOMAIN_BLOCKLIST:
        problems.append(f"blocked_domain: {domain(source_url)}")
    return not problems, "; ".join(problems) or None, 0.0

def verify_source(url: str, text: str, fetcher, threshold: float):
    """(ok, detail): the URL must load (status < 400) without leaving its domain, and the page must share the brief's words."""
    try:
        status, final_url, page = fetcher.fetch(url, timeout=FETCH_TIMEOUT_SECONDS)
    except Exception as e:
        return False, f"fetch failed ({type(e).__name__})"
    if status >= 400:
        return False, f"http {status}"
    if not same_domain(domain(final_url), domain(url)):
        return False, "redirected to another domain"
    page_overlap = overlap(text, page)
    if page_overlap < threshold:
        return False, f"page overlap {page_overlap:.2f} < {threshold:.2f}"
    return True, None

def gate_grounding(fields: dict, source: str, source_url: str, raw_title, raw_text, fetcher):
    problems = []
    threshold = SOURCE_OVERLAP_MIN.get(source, DEFAULT_OVERLAP_MIN)
    text = brief_text(fields)
    source_overlap = overlap(text, f"{raw_title} {raw_text}")
    if source_overlap < threshold:
        problems.append(f"low_source_overlap: {source_overlap:.2f} < {threshold:.2f}")
    if source == "web_grounding":
        ok, detail = verify_source(source_url, text, fetcher, threshold)
        if not ok:
            problems.append(f"unverified_source: {detail}")
    return not problems, "; ".join(problems) or None, 25 * min(1.0, source_overlap / OVERLAP_FULL_SCORE)

def gate_duplicate(match, threshold: float = DUPLICATE_THRESHOLD):
    """match: (kind, id, similarity) of the nearest vector, or None."""
    if match is None or match[2] < threshold:
        return True, None, 0.0
    kind, match_id, similarity = match
    return False, f"duplicate: {kind} {match_id} similarity {similarity:.3f}", 0.0

def score_extras(fields: dict, confidence_flag, source_date, now: datetime) -> float:
    confidence = {"high": 15.0, "low": 5.0}.get(confidence_flag, 10.0)
    specificity = 20 * min(1.0, len(salient_words(brief_text(fields))) / SPECIFICITY_FULL_SCORE)
    if source_date is None:
        recency = 7.5
    else:
        age_days = (now.replace(tzinfo=None) - source_date).days
        recency = 15 * max(0.0, 1 - age_days / RECENCY_DAYS)
    return confidence + specificity + recency

def evaluate_static(row, fetcher, now: datetime):
    """Gates 2-4 and the score. Returns (failures, score, fields)."""
    fields = effective_fields(row)
    results = {
        "structure": gate_structure(fields),
        "red_flags": gate_red_flags(row.raw_title, row.raw_text, row.source_url),
        "grounding": gate_grounding(fields, row.source, row.source_url, row.raw_title, row.raw_text, fetcher),
    }
    failures = [{"gate": gate, "reason": reason} for gate, (passed, reason, _) in results.items() if not passed]
    score = sum(part for _, _, part in results.values()) + score_extras(fields, row.confidence_flag, row.source_date, now)
    return failures, round(score, 2), fields

def score_order(item):
    """Sort key: higher score first, then older source_date (unknown last), then id."""
    row, score = item[0], item[1]
    return (-score, row.source_date is None, row.source_date or datetime.max, row.id)

# --- duplicates ---

class VectorPool:
    """Brute-force cosine search over brief and passed raw-idea embeddings (no index covers 3072 dimensions)."""

    def __init__(self):
        self.entries = []  # (kind, id, owner_raw_idea_id)
        self.matrix = np.zeros((0, 0), dtype=np.float32)

    def add(self, kind: str, entry_id: int, vector, owner_raw_idea_id=None):
        vec = np.asarray(vector, dtype=np.float32)
        norm = np.linalg.norm(vec)
        if not norm:
            return
        vec = vec / norm
        self.matrix = vec[None, :] if not self.entries else np.vstack([self.matrix, vec])
        self.entries.append((kind, entry_id, owner_raw_idea_id))

    def nearest(self, vector, raw_idea_id=None):
        """(kind, id, similarity) of the closest entry, ignoring the raw idea itself and its own brief."""
        if not self.entries:
            return None
        vec = np.asarray(vector, dtype=np.float32)
        vec = vec / (np.linalg.norm(vec) or 1.0)
        sims = self.matrix @ vec
        for i, (kind, entry_id, owner) in enumerate(self.entries):
            if raw_idea_id is not None and ((kind == "raw" and entry_id == raw_idea_id) or owner == raw_idea_id):
                sims[i] = -np.inf
        best = int(np.argmax(sims))
        if not np.isfinite(sims[best]):
            return None
        kind, entry_id, _ = self.entries[best]
        return kind, entry_id, float(sims[best])

def load_pool(db) -> VectorPool:
    pool = VectorPool()
    for brief_id, raw_idea_id, vector in db.query(Brief.id, Brief.raw_idea_id, Brief.embedding).filter(Brief.embedding.isnot(None)):
        pool.add("brief", brief_id, vector, owner_raw_idea_id=raw_idea_id)
    for raw_id, vector in db.query(RawIdea.id, RawIdea.embedding).filter(RawIdea.gate_status == "passed", RawIdea.embedding.isnot(None)):
        pool.add("raw", raw_id, vector)
    return pool

# --- clients ---

class GeminiEmbedClient:
    """Default embedding client (gemini-embedding-001, 3072 dims, same as briefs). Tests inject a fake."""

    def embed(self, text: str):
        from llm.translate import generate_embedding
        return list(generate_embedding(text))

class RequestsFetcher:
    """Default fetcher: fetch(url, timeout) -> (status, final_url, page_text). Tests inject a fake."""

    def fetch(self, url: str, timeout: int):
        import requests
        response = requests.get(url, timeout=timeout, allow_redirects=True, headers={"User-Agent": "the-problem-network-gates/1.0"})
        return response.status_code, response.url, html_to_text(response.text[:500_000])

# --- stage ---

def _reason_codes(failures):
    for failure in failures:
        for part in (failure["reason"] or "").split("; "):
            yield part.split(":", 1)[0]

class _Run:
    def __init__(self, db, deadline):
        self.db, self.deadline, self.written = db, deadline, 0
        self.summary = {"rejected_by_extraction": 0, "examined": 0, "passed": 0, "failed": 0, "duplicate": 0,
                        "deferred": 0, "stopped_by_budget": False, "failure_reasons": {}}

    def out_of_time(self):
        if time.monotonic() >= self.deadline:
            self.summary["stopped_by_budget"] = True
        return self.summary["stopped_by_budget"]

    def write(self, row, status, failures, score, duplicate_of_brief_id=None, counter=None):
        row.gate_status = status
        row.gate_failures = failures
        row.gate_score = score
        row.gated_at = datetime.now(timezone.utc)
        if duplicate_of_brief_id is not None:
            row.duplicate_of_brief_id = duplicate_of_brief_id
        self.summary[counter or status] += 1
        for code in _reason_codes(failures):
            self.summary["failure_reasons"][code] = self.summary["failure_reasons"].get(code, 0) + 1
        self.written += 1
        if self.written % COMMIT_EVERY == 0:
            self.db.commit()

def gate_rows(db, rows, embed_client, fetcher, deadline, now=None, run=None) -> dict:
    """Apply gates 2-6 to already-selected eligible rows and write the outcomes. Rows left pending were not decided."""
    run = run or _Run(db, deadline)
    now = now or datetime.now(timezone.utc)
    candidates = []
    for row in rows:
        if run.out_of_time():
            break
        run.summary["examined"] += 1
        failures, score, fields = evaluate_static(row, fetcher, now)
        if failures:
            run.write(row, "failed", failures, score)
        else:
            candidates.append((row, score, fields))

    pool = load_pool(db) if candidates else None
    for row, score, fields in sorted(candidates, key=score_order):
        if run.out_of_time():
            break
        vector = row.embedding
        if vector is None:
            try:
                vector = embed_client.embed(brief_text(fields))
            except Exception:
                run.summary["deferred"] += 1
                continue
            row.embedding = vector
        match = pool.nearest(vector, raw_idea_id=row.id)
        passed, reason, _ = gate_duplicate(match)
        if passed:
            run.write(row, "passed", [], score)
            pool.add("raw", row.id, vector)
        else:
            run.write(row, "duplicate", [{"gate": "duplicates", "reason": reason}], score,
                      duplicate_of_brief_id=match[1] if match[0] == "brief" else None)
    db.commit()
    return run.summary

def run_gates(db, embed_client, fetcher, max_items, budget_seconds) -> dict:
    """
    Gate pending extracted rows, oldest first, at most max_items valid rows (plus up to max_items rows the
    extraction rejected, which leave the queue as failed). Logs one pipeline_runs row and returns a summary.
    """
    deadline = time.monotonic() + budget_seconds
    started_at = datetime.now(timezone.utc)
    run = _Run(db, deadline)
    status, error = "ok", None
    pending = (RawIdea.processed_at.isnot(None), RawIdea.gate_status == "pending", RawIdea.published_brief_id.is_(None))
    oldest = (RawIdea.fetched_at.asc().nullsfirst(), RawIdea.id.asc())
    try:
        rejected = db.query(RawIdea).filter(*pending, RawIdea.is_valid_idea == "false").order_by(*oldest).limit(max_items).all()
        for row in rejected:
            if run.out_of_time():
                break
            run.write(row, "failed", [{"gate": "eligibility", "reason": "rejected_by_extraction"}], None,
                      counter="rejected_by_extraction")
        db.commit()
        if not run.out_of_time():
            rows = db.query(RawIdea).filter(*pending, RawIdea.is_valid_idea.in_(VALID_IDEA)).order_by(*oldest).limit(max_items).all()
            gate_rows(db, rows, embed_client, fetcher, deadline, run=run)
    except Exception as e:
        db.rollback()
        status, error = "error", safe_error(e)

    summary = run.summary
    db.add(PipelineRun(stage=STAGE, started_at=started_at, finished_at=datetime.now(timezone.utc),
                       rows_in=summary["rejected_by_extraction"] + summary["examined"], rows_out=summary["passed"],
                       status=status, error=error))
    db.commit()
    return {"status": status, "error": error, **summary}
