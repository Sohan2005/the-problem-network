"""
Matching for the brief list: the search box (title, core task and stack) and the tech stack filter (stack only).

Text is lowercased, ".net" becomes "dotnet" and dots or hyphens inside words are dropped, so "Node.js", "nodejs" and
"NODE-JS" compare equal. A query is split into terms on anything other than letters, digits, '#' and '+', and every
term must match. A term matches a word that contains it or one of its aliases (js and javascript, node and nodejs, ...).
Terms of two characters or less and WHOLE_WORD_TERMS only match a whole word, so "go" does not match "mongodb" and
"java" does not match "javascript".
"""
import re
from typing import Optional

_DOT_NET = re.compile(r"(?<![a-z0-9])\.net\b")
_INNER_PUNCTUATION = re.compile(r"(?<=[a-z0-9])[.\-](?=[a-z0-9])")
_WORD = re.compile(r"[a-z0-9#+]+")

ALIAS_GROUPS = (
    ("javascript", "js", "ecmascript"),
    ("typescript", "ts"),
    ("nodejs", "node"),
    ("python", "py", "python3"),
    ("postgresql", "postgres", "psql"),
    ("react", "reactjs"),
    ("vue", "vuejs"),
    ("golang", "go"),
    ("kubernetes", "k8s"),
    ("c#", "csharp", "dotnet", "aspnet"),
    ("c++", "cpp"),
    ("mongodb", "mongo"),
    ("tailwind", "tailwindcss"),
    ("database", "db"),
)
ALIASES = {variant: group for group in ALIAS_GROUPS for variant in group}
WHOLE_WORD_TERMS = frozenset({"java"})


def fold(text: str) -> str:
    return _INNER_PUNCTUATION.sub("", _DOT_NET.sub("dotnet", text.lower()))


def terms(query: Optional[str]) -> tuple:
    """The distinct terms of a query in order; empty for None or a query without letters or digits."""
    return tuple(dict.fromkeys(_WORD.findall(fold(query)))) if query else ()


def words(*texts) -> frozenset:
    """The words of every string in texts; other values are skipped."""
    found = set()
    for text in texts:
        if isinstance(text, str):
            found.update(_WORD.findall(fold(text)))
    return frozenset(found)


def _whole_word(variant: str) -> bool:
    return len(variant) <= 2 or variant in WHOLE_WORD_TERMS


def term_matches(term: str, haystack: frozenset) -> bool:
    for variant in ALIASES.get(term, (term,)):
        if variant in haystack:
            return True
        if not _whole_word(variant) and any(variant in word for word in haystack):
            return True
    return False


def matches_all(query_terms, haystack: frozenset) -> bool:
    return all(term_matches(term, haystack) for term in query_terms)
