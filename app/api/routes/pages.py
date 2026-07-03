"""Routes that serve HTML pages (the dashboard)."""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

APP_DIR = Path(__file__).resolve().parents[2]  # .../app

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def dashboard(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html")
