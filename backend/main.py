import os
import shutil
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Request

from backend.services.repo_service import RepoService
from backend.services.pdf_service import PDFService
from backend.services.orchestrator_service import OrchestratorService
from backend.config import logger

app = FastAPI(title="Enterprise AI Code Review System")

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

orchestrator = OrchestratorService()


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/review")
async def review_repo(
    repo_url: str = Form(...),
    roles_file: UploadFile = File(...)
):
    try:
        # Save uploaded PDF
        upload_path = f"temp_{roles_file.filename}"
        with open(upload_path, "wb") as buffer:
            shutil.copyfileobj(roles_file.file, buffer)

        # Read roles
        roles_text = PDFService.read_roles(upload_path)

        # Clone repo
        repo_dir = RepoService.clone_repo(repo_url)
        repo_files = RepoService.read_code(repo_dir)

        repo_text = ""
        for file in repo_files:
            repo_text += f"\nFILE: {file['file']}\n{file['content']}\n"

        result = orchestrator.execute(repo_text)

        os.remove(upload_path)

        return result

    except Exception as e:
        logger.error(str(e))
        raise HTTPException(status_code=500, detail=str(e))
