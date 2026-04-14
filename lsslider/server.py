from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from .theory import TheoryManager

LOGGER = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent / "static"


class EvaluateRequest(BaseModel):
    model: str = Field(default="folpsv2")
    backend: str = Field(default="direct")
    params: dict[str, float] = Field(default_factory=dict)


def create_app() -> FastAPI:
    app = FastAPI(title="Galaxy Clustering Slider", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    manager = TheoryManager()

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/config")
    def get_config() -> dict:
        return manager.app_config()

    @app.post("/api/evaluate")
    def post_evaluate(payload: EvaluateRequest) -> JSONResponse:
        try:
            result = manager.evaluate(model_key=payload.model, backend=payload.backend, params=payload.params)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # pragma: no cover
            LOGGER.exception("Evaluation failed")
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return JSONResponse(result)

    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str) -> FileResponse:
        if not STATIC_DIR.exists():
            raise HTTPException(status_code=404, detail="Frontend build not found. Run `npm run build` first.")

        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")

        target = (STATIC_DIR / full_path).resolve() if full_path else STATIC_DIR / "index.html"
        if target.is_file() and (target == STATIC_DIR / "index.html" or STATIC_DIR in target.parents):
            return FileResponse(target)

        index_file = STATIC_DIR / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        raise HTTPException(status_code=404, detail="Frontend entrypoint not found.")

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the galaxy clustering slider demo.")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"), help="Host interface to bind.")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")), help="Port to bind.")
    parser.add_argument("--reload", action="store_true", help="Enable uvicorn auto-reload.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run("lsslider.server:create_app", factory=True, host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
