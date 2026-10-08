"""
Gemini access through the google.genai package (free tier only: no tools, no search grounding).

GeminiClient.generate(prompt) -> str uses the default generation settings unless generation_config is given;
GeminiClient.embed(text) -> list[float] uses gemini-embedding-001 at 3072 dimensions, the same vectors as briefs.
The underlying google.genai client is created on first use; tests pass a fake object with the same methods instead.
Both raise QuotaExhausted when the free quota (per minute or per day) is used up, so stages can stop cleanly.
"""
import os

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

load_dotenv()

GENERATION_MODEL = "gemini-3.5-flash-lite"
EMBEDDING_MODEL = "gemini-embedding-001"  # never change: stored vectors must stay comparable
EMBEDDING_DIMENSIONS = 3072
TIMEOUT_SECONDS = 60

class QuotaExhausted(Exception):
    """HTTP 429 / RESOURCE_EXHAUSTED from Gemini: the free-tier quota is used up for now."""

def _is_quota_error(exc: errors.APIError) -> bool:
    return exc.code == 429 or exc.status == "RESOURCE_EXHAUSTED"

class GeminiClient:
    """generate(prompt) -> str and embed(text) -> list[float] with a per-request timeout."""

    def __init__(self, model_name: str = GENERATION_MODEL, timeout_seconds: int = TIMEOUT_SECONDS,
                 generation_config: dict = None, client=None):
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self.generation_config = generation_config
        self._client = client

    @property
    def client(self):
        if self._client is None:
            self._client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"),
                                        http_options=types.HttpOptions(timeout=int(self.timeout_seconds * 1000)))
        return self._client

    def generate(self, prompt: str) -> str:
        config = types.GenerateContentConfig(**self.generation_config) if self.generation_config else None
        try:
            return self.client.models.generate_content(model=self.model_name, contents=prompt, config=config).text
        except errors.APIError as e:
            if _is_quota_error(e):
                raise QuotaExhausted(f"generate: {e.code} {e.status}") from e
            raise

    def embed(self, text: str) -> list:
        try:
            result = self.client.models.embed_content(
                model=EMBEDDING_MODEL,
                contents=text,
                config=types.EmbedContentConfig(output_dimensionality=EMBEDDING_DIMENSIONS),
            )
        except errors.APIError as e:
            if _is_quota_error(e):
                raise QuotaExhausted(f"embed: {e.code} {e.status}") from e
            raise
        return list(result.embeddings[0].values)

def generate(prompt: str) -> str:
    return GeminiClient().generate(prompt)

def embed(text: str) -> list:
    return GeminiClient().embed(text)
