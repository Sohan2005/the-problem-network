from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes.briefs import router as briefs_router

app = FastAPI(
    title="The Problem Network API",
    description="Translates real-world technical problems into structured, junior-dev-friendly briefs.",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

app.include_router(briefs_router)

@app.get("/health")
def health():
    return {"status": "ok", "service": "the-problem-network-api"}
