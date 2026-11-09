"""
Primary category of a posting for the home page navigation: deterministic keyword scoring, no model calls, no column.

Each keyword is matched as a whole word (any case) in the title (3 points), the tech stack (2 points) and the core task
(1 point). The category with the most points wins; a tie goes to the category listed first, and no match at all is
OTHER. STACK_IGNORE keywords only count in the title and core task, because "HTML/CSS" or "OpenAI API" in a stack says
nothing about the problem. The slugs are part of the API (?category=) and must match frontend/lib/categories.ts.
"""
import re

CATEGORIES = (
    ("ai", "AI and Machine Learning", (
        "ai", "llm", "llms", "openai", "gpt", "chatgpt", "machine learning", "neural", "prompt", "prompts", "chatbot",
        "conversational bot", "ai models", "ai model", "ai agent", "ai agents", "agents", "mcp", "claude", "local llm")),
    ("developer-tools", "Developer Tools", (
        "api", "apis", "mock", "cli", "command-line", "command line", "terminal", "linter", "lint", "compiler",
        "compilers", "compile", "c++", "codebase", "source code", "repository", "repositories", "github", "git",
        "documentation", "readme", "environment variable", "env", "component library", "programming language",
        "programming languages", "cron", "proxy", "sdk", "debug", "deploy", "boilerplate", "metadata", "regex",
        "regular expressions", "hardware", "iot", "firmware", "embedded", "arduino", "raspberry pi", "sensor", "sensors",
        "serial port", "static site", "site generator", "code review", "code reviews", "testing", "regression", "json",
        "schema", "protobuf", "markdown", "curl", "build config", "dependency", "dependencies", "library deprecation",
        "html", "css", "hostname", "localhost", "slash command", "slash commands")),
    ("data", "Data and Analytics", (
        "analytics", "analysis", "analyze", "data visualization", "charting", "chart", "charts", "statistics", "trends",
        "frequency", "valuation", "corpus", "ngram", "metrics", "monitor", "monitoring", "dashboard", "estimate",
        "estimator", "map", "maps", "mapping", "geospatial", "gis", "dataset", "datasets", "satellite", "orbit",
        "visualizer", "visualize", "visualization", "embedding", "embeddings", "data pipeline", "pipeline")),
    ("productivity", "Productivity and Automation", (
        "reminder", "reminders", "schedule", "scheduler", "scheduling", "calendar", "notes", "notetaker", "notification",
        "notifications", "organize", "organizer", "mind map", "automate", "automation", "automatically", "workflow",
        "sync", "backup", "settings", "profile switcher", "tab", "tabs", "time zones", "timezone", "inventory",
        "spellcheck", "autocorrect", "keyboard", "foreground", "window", "self-checkout", "tracker", "bluetooth",
        "headset", "media key", "media control", "pdf", "clipboard", "email", "inbox", "chat history", "export",
        "scratch note", "wiki", "project management", "knowledge", "google docs", "documents", "signature",
        "checklist")),
    ("security-privacy", "Security and Privacy", (
        "privacy", "private", "anonymous", "anonymously", "anonymity", "ad-blocking", "ad-free", "ads", "cookie",
        "cookies", "encryption", "crypto", "secret", "secrets", "audit", "password", "passwords", "security",
        "tracking", "spending limits", "manipulative", "parental control", "parental controls")),
    ("mobile", "Mobile Apps", (
        "android", "ios", "iphone", "mobile app", "mobile app development", "kotlin", "swift", "react native",
        "flutter")),
    ("media-games", "Media, Games and Creative", (
        "game", "games", "gaming", "gamers", "music", "musicians", "gig", "gigs", "band", "photo", "photos",
        "photographers", "image", "images", "video", "videos", "youtube", "audio", "acoustic", "speaker", "book",
        "books", "ebook", "ebooks", "reader", "readers", "magazine", "articles", "jpeg", "jpeg xl", "ffmpeg",
        "watermarks", "map annotation", "documentary", "kindle", "digest", "news", "sketch", "wireframe", "designers")),
    ("money-work", "Money, Work and Business", (
        "subscription", "subscriptions", "expense", "expenses", "billing", "bills", "payment", "payments", "invoice",
        "invoices", "quote", "quotes", "tax", "taxes", "freelancer", "freelancers", "job", "jobs", "job seekers",
        "recruiters", "saas", "referral", "donation", "price", "prices", "pricing", "cost", "costs", "budget",
        "real estate", "selling price", "charges", "credit cards", "contractor", "fax", "faxes", "bureaucratic",
        "investment", "investments", "portfolio", "stock", "stocks", "dividend", "drip", "e-commerce", "ecommerce",
        "product review", "product reviews", "shopping", "menu", "orders", "restaurant", "food business", "founder",
        "founders", "startup", "startups", "accounting", "arbitrage", "prediction market", "bank", "transaction",
        "transactions", "budgeting", "engineering culture", "employer", "employers", "workplace", "company reviews")),
    ("life-health", "Health, Home and Everyday Life", (
        "health", "healthcare", "medical", "patients", "fitness", "workout", "workouts", "injury", "injuries", "pain",
        "gratitude", "diary", "mood", "dating", "daters", "homeowners", "renovation", "home improvement", "community",
        "social media", "appeal", "appeals", "kindness", "dating apps", "compatibility", "ambulance", "surgeries",
        "mris", "pronunciation", "vocabulary", "language learners", "wine", "food", "recipe", "recipes", "politician",
        "politicians", "civic", "reflection", "medication", "medications", "elderly", "caregivers", "posture",
        "eye strain", "feed", "personalized feed")),
)
OTHER = "other"
SLUGS = tuple(slug for slug, _, _ in CATEGORIES) + (OTHER,)
WEIGHTS = {"title": 3, "stack": 2, "core_task": 1}
STACK_IGNORE = frozenset({"api", "apis", "html", "css"})

_PATTERNS = {
    slug: [(keyword, re.compile(r"(?<![\w+])" + re.escape(keyword) + r"(?![\w+])", re.I)) for keyword in keywords]
    for slug, _, keywords in CATEGORIES
}


def category_scores(title, core_task, stack) -> dict:
    """Points per category slug (OTHER excluded)."""
    if isinstance(stack, str):
        stack = [stack]
    elif not isinstance(stack, (list, tuple)):
        stack = []
    fields = {"title": title or "", "stack": " ; ".join(str(item) for item in stack), "core_task": core_task or ""}
    return {
        slug: sum(WEIGHTS[field] for field, text in fields.items() for keyword, pattern in patterns
                  if not (field == "stack" and keyword in STACK_IGNORE) and pattern.search(text))
        for slug, patterns in _PATTERNS.items()
    }


def classify(title, core_task, stack) -> str:
    """The one primary category slug of a posting."""
    best, best_score = OTHER, 0
    for slug, score in category_scores(title, core_task, stack).items():
        if score > best_score:
            best, best_score = slug, score
    return best
