"""
OryaAgent v7.0 — FastAPI entry point.

MVP phase: bootstrap project structure.
"""

from fastapi import FastAPI

app = FastAPI(
    title="OryaAgent",
    description="Senior Python coding agent with UI and long-term memory",
    version="7.0.0",
)


@app.get("/health")
async def health_check():
    """Health check endpoint for M-00 bootstrap verification."""
    return {"status": "ok", "message": "OryaAgent API is running"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
