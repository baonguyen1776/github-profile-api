from __future__ import annotations

from fastapi import FastAPI

from routes.header import router as header_router
from routes.stack import router as stack_router
from routes.contributions import preview_router, router as contributions_router


app = FastAPI(
    title="GitHub Profile SVG API",
    description="Generate animated SVG cards from public GitHub profile data.",
    version="0.1.0",
)
app.include_router(header_router)
app.include_router(stack_router)
app.include_router(contributions_router)
app.include_router(preview_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
