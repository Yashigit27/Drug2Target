"""D2T web application - FastAPI entrypoint (API routes only)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from src import __version__
from src.lib.registry.db import init_db
from src.lib.registry.migrate import migrate_legacy_runs
from src.lib.registry.repository import archive_run, user_can_access_run
from web.auth import (
    CurrentUser,
    OptionalUser,
    authenticate_user,
    bootstrap_admin_if_configured,
    end_session,
    get_current_user,
    register_user,
    start_session,
)
from web.catalog import APPROACH_MODES, PIPELINE_LAYERS, RUN_MODES
from web.downloads import build_run_zip
from web.evidence import build_evidence_card
from web.llm_narrative import generate_gene_narrative
from web.network_graph import build_network_graph
from web.pdf_export import build_report_pdf
from web.report import build_report
from web.runner import get_job, list_jobs, start_job
from web.runs import list_runs, preview_csv, run_status

WEB_DIR = Path(__file__).resolve().parent

app = FastAPI(title="D2T Target Discovery", version=__version__)
app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
templates = Jinja2Templates(directory=WEB_DIR / "templates")


class RunRequest(BaseModel):
    mode: str = "full"
    approach: str | None = None
    disease: str | None = None
    subtype: str | None = None
    tissue: str | None = None
    run_id: str | None = None
    disease_id: str | None = None
    skip_literature: bool = False
    custom_step: str | None = None
    use_snakemake: bool = False


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=3)
    password: str = Field(..., min_length=8)
    name: str | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


@app.on_event("startup")
async def startup() -> None:
    init_db()
    bootstrap_admin_if_configured()
    migrate_legacy_runs()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html", {"version": __version__})


@app.get("/api/catalog")
async def api_catalog() -> dict:
    return {
        "version": __version__,
        "layers": PIPELINE_LAYERS,
        "modes": RUN_MODES,
        "approaches": APPROACH_MODES,
    }


@app.post("/api/auth/register")
async def api_register(body: RegisterRequest, response: Response) -> dict:
    try:
        user = register_user(body.email, body.password, name=body.name)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    start_session(response, user.user_id)
    return {"user_id": user.user_id, "email": user.email, "name": user.name}


@app.post("/api/auth/login")
async def api_login(body: LoginRequest, response: Response) -> dict:
    user = authenticate_user(body.email, body.password)
    if not user:
        raise HTTPException(401, "Invalid email or password")
    start_session(response, user.user_id)
    return {"user_id": user.user_id, "email": user.email, "name": user.name}


@app.post("/api/auth/logout")
async def api_logout(request: Request, response: Response) -> dict:
    end_session(response, request)
    return {"ok": True}


@app.get("/api/auth/me")
async def api_me(user: OptionalUser) -> dict:
    if not user:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "user_id": user.user_id,
        "email": user.email,
        "name": user.name,
    }


def _require_run(user: OptionalUser, run_id: str) -> None:
    uid = user.user_id if user else None
    if not user_can_access_run(uid, run_id):
        raise HTTPException(404, "Run not found")


@app.get("/api/runs")
async def api_runs(user: CurrentUser) -> dict:
    return {"runs": list_runs(user_id=user.user_id)}


@app.get("/api/runs/{run_id}/status")
async def api_run_status(run_id: str, user: CurrentUser) -> dict:
    _require_run(user, run_id)
    return run_status(run_id)


@app.get("/api/runs/{run_id}/report")
async def api_run_report(run_id: str, user: CurrentUser) -> dict:
    _require_run(user, run_id)
    try:
        return build_report(run_id)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e


@app.get("/api/runs/{run_id}/preview/{artifact}")
async def api_preview(run_id: str, artifact: str, user: CurrentUser, limit: int = 25) -> dict:
    _require_run(user, run_id)
    try:
        return preview_csv(run_id, artifact, limit=limit)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/runs/{run_id}/archive")
async def api_archive_run(run_id: str, user: CurrentUser) -> dict:
    _require_run(user, run_id)
    reg = archive_run(run_id)
    return {"run_id": run_id, "archived": True}


@app.post("/api/jobs")
async def api_start_job(body: RunRequest, user: CurrentUser) -> dict:
    if body.approach:
        if body.approach not in APPROACH_MODES:
            raise HTTPException(400, "invalid approach")
        if not body.disease:
            raise HTTPException(400, "disease is required")
    elif body.mode in ("full", "foundation") and not body.disease:
        raise HTTPException(400, "disease is required")
    elif body.mode == "custom" and not body.custom_step:
        raise HTTPException(400, "custom_step is required")
    elif body.mode == "custom" and body.custom_step == "step1" and not body.disease:
        raise HTTPException(400, "disease is required for step1")
    elif body.mode == "custom" and body.custom_step != "step1" and not body.run_id:
        raise HTTPException(400, "run_id is required for this step")
    elif body.mode in ("trackA", "trackB") and not body.run_id:
        raise HTTPException(400, "run_id is required")

    if body.run_id:
        _require_run(user, body.run_id)

    params = {
        "disease": body.disease,
        "subtype": body.subtype,
        "tissue": body.tissue,
        "run_id": body.run_id,
        "disease_id": body.disease_id,
        "skip_literature": body.skip_literature,
    }
    try:
        job = start_job(
            body.mode,
            params,
            custom_step=body.custom_step,
            approach=body.approach,
            use_snakemake=body.use_snakemake,
            user_id=user.user_id,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"job_id": job.id, "run_id": job.run_id, "status": job.status}


@app.get("/api/jobs")
async def api_jobs(user: CurrentUser) -> dict:
    from src.lib.registry.repository import list_jobs_for_user

    db_jobs = list_jobs_for_user(user.user_id, limit=50)
    mem = {j.id: j for j in list_jobs()}
    out = []
    for rec in db_jobs:
        live = mem.get(rec.job_id)
        out.append(
            {
                "id": rec.job_id,
                "run_id": rec.run_id,
                "command": rec.command,
                "status": live.status if live else rec.status,
                "log": (live.log[-20:] if live else (rec.log_summary or "").split("\n")[-20:]),
                "error": live.error if live else rec.error,
                "started_at": rec.started_at,
                "finished_at": rec.finished_at,
            }
        )
    return {"jobs": out}


@app.get("/api/jobs/{job_id}")
async def api_job(job_id: str, user: CurrentUser) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.user_id and job.user_id != user.user_id:
        raise HTTPException(404, "Job not found")
    return {
        "id": job.id,
        "run_id": job.run_id,
        "command": job.command,
        "status": job.status,
        "log": job.log,
        "error": job.error,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }


@app.get("/api/runs/{run_id}/download")
async def api_run_download(run_id: str, user: CurrentUser) -> Response:
    _require_run(user, run_id)
    try:
        data = build_run_zip(run_id)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{run_id}_artifacts.zip"'},
    )


@app.get("/api/runs/{run_id}/report.pdf")
async def api_run_report_pdf(run_id: str, user: CurrentUser) -> Response:
    _require_run(user, run_id)
    try:
        data = build_report_pdf(run_id)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{run_id}_report.pdf"'},
    )


@app.get("/api/runs/{run_id}/evidence/{gene}")
async def api_evidence_card(run_id: str, gene: str, user: CurrentUser) -> dict:
    _require_run(user, run_id)
    try:
        return build_evidence_card(run_id, gene)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e


@app.get("/api/runs/{run_id}/network")
async def api_network_graph(
    run_id: str, user: CurrentUser, top_n: int = Query(40, ge=5, le=120)
) -> dict:
    _require_run(user, run_id)
    try:
        return build_network_graph(run_id, top_n=top_n)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e


@app.get("/api/runs/{run_id}/narrative/{gene}")
async def api_gene_narrative(run_id: str, gene: str, user: CurrentUser) -> dict:
    _require_run(user, run_id)
    try:
        return generate_gene_narrative(run_id, gene)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
