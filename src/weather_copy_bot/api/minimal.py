"""Minimal FastAPI test endpoint."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def api_health() -> Dict[str, Any]:
    return {"status": "ok", "message": "Polymeteo minimal test", "path": "api/health"}


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "message": "Polymeteo minimal test", "path": "health"}


@app.get("/")
def root() -> Dict[str, Any]:
    return {"status": "ok", "service": "polymeteo-api"}
