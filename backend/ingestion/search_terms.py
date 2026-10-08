"""Search terms and local intent scoring for organic ingestion.

Pure data and pure functions. No network, no database.
Used by hn_ingest, stackexchange_ingest and the extraction ordering.
"""
import re

# Strong: the author states an unmet need or a wish. Weight 3.
STRONG_PHRASES = [
    "wish there was", "wish there were", "wish this existed", "wish something existed",
    "wish someone would build", "wish someone would make", "wish i could find",
    "why doesn't this exist", "why does this not exist", "why isn't there",
    "why is there no", "there should be an app", "there should be a tool",
    "someone should build", "someone should make", "somebody should build",
    "somebody should make", "i would pay for", "i'd pay for", "i would happily pay",
    "take my money", "shut up and take my money", "would pay for a tool",
    "can't find a tool", "can't find an app", "cannot find a tool", "cannot find an app",
    "can't find software", "couldn't find anything that", "could not find anything that",
    "i can't find anything that", "nothing out there", "no good solution",
    "no good tool", "no good app", "no good alternative", "there must be a better way",
    "i want to create something like", "i want to build something like",
    "i want to make something like", "i want to build a tool", "i want to build an app",
    "i want to make an app that", "i want to create an app that", "i'm thinking of building",
    "i am thinking of building", "thinking about building a tool", "thinking about making an app",
    "does anyone know of a tool", "does anyone know of an app", "does anyone know a tool",
    "does anyone know an app", "does anybody know of a tool", "does anyone know of any software",
    "is there a tool that", "is there an app that", "is there a software that",
    "is there a program that", "is there a service that", "is there a website that",
    "is there a browser extension that", "is there a plugin that", "is there an extension that",
    "is there a script that", "is there a library that", "is there a way to automatically",
    "is there any tool", "is there any app", "is there any software", "is there any service",
    "is there something like", "is there anything like", "is there a simple tool",
    "has anyone built", "has anyone made", "has anyone created a tool",
    "has anyone built an app", "anyone built a tool", "anyone know of a tool",
    "anyone know of an app", "looking for a tool", "looking for an app",
    "looking for software", "looking for a program", "looking for a service",
    "looking for a website", "looking for a browser extension", "looking for a plugin",
    "looking for a script", "looking for a simple tool", "looking for something that can",
    "looking for an alternative to", "looking for a replacement for",
    "in search of a tool", "in search of an app", "in search of software",
    "i need a tool", "i need an app", "i need software", "i need a script",
    "i need a program", "i need a simple tool", "i need something that can",
    "we need a tool", "we need an app", "need a tool that", "need an app that",
    "need software that", "need a script that", "need a plugin that",
    "what tool do you use", "what app do you use", "what software do you use",
    "what do you use to track", "what do you use to manage", "what do you use for",
    "how do you keep track of", "how do you manage", "how do you organize",
    "how do you stay on top of", "how do you deal with", "how do you automate",
]

# Medium: pain, friction, manual work, builder intent. Weight 2.
MEDIUM_PHRASES = [
    "pain point", "biggest pain", "biggest frustration", "biggest problem",
    "frustrated with", "frustrating that", "fed up with", "sick of", "tired of",
    "tired of doing", "hate having to", "hate that i have to", "annoying that",
    "annoyed that", "struggling with", "struggle to", "struggle with",
    "hard to keep track", "hard to track", "difficult to keep track",
    "no way to", "no easy way to", "no simple way to", "missing feature",
    "feature request", "should be easier to", "tedious", "time consuming",
    "time-consuming", "waste hours", "wasting hours", "waste of time",
    "keep forgetting", "i keep losing", "keeps getting lost", "doing this manually",
    "do this manually", "manually every", "manual process", "by hand every",
    "copy and paste", "copy-paste", "repetitive", "spreadsheet", "google sheet",
    "excel sheet", "cobbled together", "duct tape", "workaround", "hacky solution",
    "my current workflow", "current solution is", "current process is",
    "what problems are worth solving", "what problem should i solve",
    "problems worth solving", "unsolved problems", "unmet need", "unmet needs",
    "what do you wish existed", "what tool do you wish", "what's missing in",
    "what is missing in", "what app is missing", "ideas that need building",
    "what should i build", "what can i build", "what to build", "need project ideas",
    "looking for project ideas", "project ideas", "side project idea", "side project ideas",
    "weekend project", "app idea", "app ideas", "startup idea", "business idea",
    "micro saas idea", "saas idea", "tool idea", "idea for a tool", "idea for an app",
    "would anyone use", "would you use", "would you pay for", "who would use",
    "is there demand for", "is there a market for", "validate my idea",
    "feedback on my idea", "market gap", "gap in the market", "gap in the market for",
    "recommend a tool", "recommend an app", "recommend software", "recommendations for software",
    "recommendations for a tool", "recommendations for an app", "best tool for",
    "best app for", "best software for", "alternative to", "alternatives to",
    "free alternative", "open source alternative", "self hosted alternative",
    "self-hosted alternative", "simple way to", "easy way to", "better way to",
    "anyone else struggle", "anyone else frustrated", "does anyone else have this problem",
    "is it just me or", "how do i automate", "how can i automate", "how to automate",
]

# Weak: topical hints only. Weight 1.
WEAK_PHRASES = [
    "automate", "automation", "workflow", "tracker", "dashboard", "scheduler",
    "organizer", "reminder", "template", "converter", "generator", "checklist",
    "notification", "notifications", "sync", "integration", "browser extension",
    "chrome extension", "firefox extension", "plugin", "add-on", "script",
    "bot", "api", "web app", "mobile app", "cli tool", "command line tool",
]

# Troubleshooting and noise: these questions are rarely buildable ideas. Weight -3.
NEGATIVE_PATTERNS = [
    "error message", "stack trace", "traceback", "not working", "doesn't work",
    "does not work", "won't start", "won't open", "wont open", "keeps crashing",
    "crashes when", "how do i fix", "how to fix", "how can i fix", "fix this error",
    "blue screen", "bsod", "boot loop", "bootloop", "won't boot", "won't turn on",
    "permission denied", "segmentation fault", "null pointer", "exception in",
    "syntax error", "compile error", "build failed", "failed to install",
    "can't install", "cannot install", "uninstall", "factory reset", "forgot my password",
    "battery drain", "wifi not", "no sound", "black screen", "screen flickering",
    "homework", "assignment", "exam question", "interview question",
    "show hn", "launch hn", "we just launched", "i just launched", "check out my",
    "we are hiring", "we're hiring", "who is hiring", "looking for a job",
    "sign up for", "waitlist", "promo code", "discount code", "affiliate",
]

# Template x noun generator: each template is a search phrase with a {noun} slot.
TEMPLATES = [
    "is there a {noun} that", "is there a {noun} for", "looking for a {noun} to",
    "looking for a {noun} that", "need a {noun} for", "need a {noun} that",
    "wish there was a {noun}", "wish there was a {noun} that", "anyone know a {noun}",
    "does anyone know of a {noun}", "recommend a {noun} for", "best {noun} for",
    "i want to build a {noun}", "i want to make a {noun}", "someone should build a {noun}",
    "why isn't there a {noun}", "i would pay for a {noun}", "alternative {noun} for",
]

NOUNS = [
    "tool", "app", "software", "program", "utility", "extension", "browser extension",
    "plugin", "add-on", "script", "bot", "website", "web app", "service", "platform",
    "library", "package", "cli", "dashboard", "tracker", "planner", "calculator",
    "generator", "converter", "scheduler", "manager", "organizer", "template",
    "checklist", "reminder app", "notes app", "spreadsheet", "workflow", "automation",
]

# Ask HN title openings (Algolia story search with tag ask_hn).
HN_ASK_OPENINGS = [
    "ask hn: what tool", "ask hn: what app", "ask hn: what software", "ask hn: is there a",
    "ask hn: is there an", "ask hn: looking for", "ask hn: need a", "ask hn: how do you",
    "ask hn: how do you keep track", "ask hn: how do you manage", "ask hn: how do you automate",
    "ask hn: why isn't there", "ask hn: why is there no", "ask hn: does anyone else",
    "ask hn: anyone else frustrated", "ask hn: what are you struggling with",
    "ask hn: what's your biggest pain", "ask hn: what problem", "ask hn: what problems",
    "ask hn: what would you build", "ask hn: what should i build", "ask hn: what do you wish",
    "ask hn: what's missing", "ask hn: ideas for", "ask hn: project ideas",
    "ask hn: side project", "ask hn: alternative to", "ask hn: best tool for",
    "ask hn: best way to", "ask hn: who wants to", "ask hn: would you use",
    "ask hn: would you pay", "ask hn: what are you working on",
]


def all_phrases():
    """Every search phrase, strongest first, lowercase, no duplicates."""
    seen, out = set(), []
    pools = [STRONG_PHRASES, MEDIUM_PHRASES]
    templated = [t.format(noun=n) for n in NOUNS for t in TEMPLATES]
    for pool in pools + [templated]:
        for p in pool:
            k = p.strip().lower()
            if k and k not in seen:
                seen.add(k)
                out.append(k)
    return out


def hn_phrases():
    """Phrases for Hacker News: Ask HN openings first, then everything else."""
    seen, out = set(), []
    for p in HN_ASK_OPENINGS + all_phrases():
        k = p.lower()
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


_WORD = re.compile(r"[a-z0-9']+")


def _norm(text):
    return " " + " ".join(_WORD.findall((text or "").lower())) + " "


_STRONG_N = [(" " + " ".join(_WORD.findall(p.lower())) + " ") for p in STRONG_PHRASES]
_MEDIUM_N = [(" " + " ".join(_WORD.findall(p.lower())) + " ") for p in MEDIUM_PHRASES]
_WEAK_N = [(" " + " ".join(_WORD.findall(p.lower())) + " ") for p in WEAK_PHRASES]
_NEG_N = [(" " + " ".join(_WORD.findall(p.lower())) + " ") for p in NEGATIVE_PATTERNS]


def intent_score(title, text):
    """Cheap local ranking of buildable-need intent. Higher is better.

    Counts distinct phrase hits: strong 3, medium 2, weak 1, negative -3.
    Title hits count double. Never raises.
    """
    t_title, t_all = _norm(title), _norm(f"{title} {text}")
    score = 0
    for lst, w in ((_STRONG_N, 3), (_MEDIUM_N, 2), (_WEAK_N, 1), (_NEG_N, -3)):
        for p in lst:
            if p in t_all:
                score += w
                if p in t_title:
                    score += w
    return score
