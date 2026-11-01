# How `web/app.py` works

This file is the front door of the D2T website. It does not score genes itself. It receives a browser request, checks who the user is, calls one helper, and sends a response back.

Read this in order. That is the same order Python uses when the server starts, and then the order a real visit follows.

The project version used in examples is `0.1.0` (`src/__init__.py`).

---

## 1. What happens before any page loads

You start the site with `web/server.py`:

```python
uvicorn.run("web.app:app", host="0.0.0.0", port=8080, reload=False)
```

`uvicorn` is the program that listens on port 8080. The string `"web.app:app"` means: open the module `web/app.py`, and use the object named `app`.

Python then reads `app.py` from the top line to the bottom **once**. While it reads, it:

1. Imports libraries.
2. Builds the `app` object.
3. Defines the data shapes (`RunRequest`, `RegisterRequest`, `LoginRequest`).
4. Registers every function that has `@app.get` or `@app.post` as a URL.

No pipeline runs during that read. A function under `@app.get` runs later, only when a browser asks for that URL.

After the file is loaded, uvicorn calls the startup function, then waits for requests.

---

## 2. The first lines

```python
"""D2T web application - FastAPI entrypoint (API routes only)."""

from __future__ import annotations
```

The quoted line is a docstring. It is a note for humans. Python stores it, but it does not change behavior.

`from __future__ import annotations` tells Python to treat type hints such as `str | None` as notes, not as code that runs immediately. You can write `list[str]` on older and newer Python the same way. It does not change the website.

---

## 3. Libraries, one by one

### `pathlib.Path`

```python
from pathlib import Path
```

`Path` is a safe way to join folders. `Path("web") / "static"` becomes the static folder path on Windows or Linux. This file uses it only to find the folder that contains `app.py`.

### FastAPI pieces

```python
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
```

| Name | What it is | Where this file uses it |
| --- | --- | --- |
| `FastAPI` | The application object. It maps a URL plus a method (`GET` or `POST`) to a Python function. | `app = FastAPI(...)` |
| `HTTPException` | A way to stop a function and return an error code with a message. | `raise HTTPException(400, "disease is required")` |
| `Query` | Extra rules for a value that comes after `?` in the URL. | `top_n` on the network route |
| `Request` | The incoming HTTP request: URL, headers, cookies. | Home page, logout |
| `HTMLResponse` | Tells FastAPI the reply is an HTML page, not JSON. | Home page |
| `Response` | A reply you build yourself: body bytes, content type, headers, cookies. | Login cookie, zip download, PDF download |
| `StaticFiles` | Serves files as-is: CSS, JavaScript, images. | `/static` |
| `Jinja2Templates` | Fills an HTML template with variables. | `index.html` |
| `BaseModel` | A class that describes JSON the browser sends. FastAPI reads the JSON and builds an object, or rejects bad JSON. | `RunRequest`, `RegisterRequest`, `LoginRequest` |
| `Field` | Extra rules on one model field. | Email at least 3 characters, password at least 8 |

HTTP status codes used here:

| Code | Meaning in this file |
| --- | --- |
| 200 | Success. FastAPI uses this when you `return` a dict or a `Response` without setting another code. |
| 400 | The request is missing something or has a bad value. |
| 401 | The user is not logged in, or the password is wrong. |
| 404 | The run, job, or file was not found. A private run also returns 404, so a stranger cannot tell that it exists. |

### Project imports

```python
from src import __version__
```

`__version__` is the string `"0.1.0"`. It is shown on the home page, the health check, and the catalog.

```python
from src.lib.registry.db import init_db
from src.lib.registry.migrate import migrate_legacy_runs
from src.lib.registry.repository import archive_run, user_can_access_run
```

| Function | When it runs | What it does |
| --- | --- | --- |
| `init_db()` | Once at startup | Creates the SQLite tables (users, sessions, runs, jobs, artifacts) if they are not there yet. |
| `migrate_legacy_runs()` | Once at startup | Registers older run folders that existed before the user database, so they still appear. |
| `archive_run(run_id)` | When the user archives a run | Marks that run archived. Archived runs fail the access check. |
| `user_can_access_run(user_id, run_id)` | Before almost every run URL | Returns `True` only if the run exists, is not archived, and belongs to this user (or is an old run with no owner). |

`list_jobs_for_user` is imported later, inside the jobs list function, from the same repository module. It reads the last 50 job rows for that user from the database.

```python
from web.auth import (
    CurrentUser, OptionalUser, authenticate_user, bootstrap_admin_if_configured,
    end_session, get_current_user, register_user, start_session,
)
```

These live in `web/auth.py`. `app.py` only calls them.

| Name | Kind | What it does |
| --- | --- | --- |
| `register_user(email, password, name=...)` | function | Stores a new user. Raises `ValueError` if the email exists or the password is shorter than 8 characters. Returns a user record. |
| `authenticate_user(email, password)` | function | Checks the password. Returns the user, or `None` if the email or password is wrong. |
| `start_session(response, user_id)` | function | Creates a session token and sets a cookie named `d2t_session` on the reply. The cookie lasts 7 days. The browser sends it back on later requests. |
| `end_session(response, request)` | function | Deletes that session and tells the browser to drop the cookie. |
| `get_current_user(request)` | function | Reads the cookie, loads the user, or raises 401. |
| `bootstrap_admin_if_configured()` | function | If the environment variables `D2T_BOOTSTRAP_EMAIL` and `D2T_BOOTSTRAP_PASSWORD` are set, and that email is new, it creates an admin user. |
| `CurrentUser` | type used as a function argument | FastAPI runs `get_current_user` before the route. If there is no valid cookie, the route never runs and the reply is 401. |
| `OptionalUser` | type used as a function argument | Same lookup, but a missing cookie becomes `user=None` instead of an error. Used by `/api/auth/me`. |

`get_current_user` is imported and not called by name in `app.py`. It still matters: `CurrentUser` depends on it.

```python
from web.catalog import APPROACH_MODES, PIPELINE_LAYERS, RUN_MODES
```

These are plain Python dictionaries and lists that describe the pipeline for the web page. They are not the science code.

- `PIPELINE_LAYERS` — foundation, Track A, Track B, fusion, and the step names inside each layer.
- `RUN_MODES` — `full`, `foundation`, `trackA`, `trackB`, `custom`.
- `APPROACH_MODES` — `both`, `track_a`, `track_b`. This is the choice on the launch form.

```python
from web.downloads import build_run_zip
from web.evidence import build_evidence_card
from web.llm_narrative import generate_gene_narrative
from web.network_graph import build_network_graph
from web.pdf_export import build_report_pdf
from web.report import build_report
from web.runner import get_job, list_jobs, start_job
from web.runs import list_runs, preview_csv, run_status
```

| Function | Input | Output |
| --- | --- | --- |
| `build_run_zip(run_id)` | run id | The run folder packed as zip bytes. Raises `FileNotFoundError` if the folder is missing. |
| `build_evidence_card(run_id, gene)` | run id and gene symbol | A dict of scores and evidence rows for that gene. |
| `generate_gene_narrative(run_id, gene)` | run id and gene symbol | A dict with a short written summary of that gene. |
| `build_network_graph(run_id, top_n=40)` | run id and how many genes | A dict of nodes and links for the network picture. |
| `build_report_pdf(run_id)` | run id | PDF bytes. |
| `build_report(run_id)` | run id | A dict of report sections (known genes, top Track A, top Track B, fusion). |
| `start_job(...)` | mode, parameters, user id | A `Job` object. The pipeline runs in a background thread. The function returns as soon as the job is queued. |
| `get_job(job_id)` | job id | The live `Job`, or `None` if this server process does not have it in memory. |
| `list_jobs()` | none | Jobs currently stored in memory in this process. |
| `list_runs(user_id=...)` | user id | A list of dicts, one per run the user may see. |
| `preview_csv(run_id, artifact, limit=25)` | which table to peek at | A dict with column names and the first rows. Raises `FileNotFoundError` or `ValueError`. |
| `run_status(run_id)` | run id | A dict saying which step files exist. |

---

## 4. The app object, static files, and templates

```python
WEB_DIR = Path(__file__).resolve().parent
```

`__file__` is the path of `app.py`. `.resolve()` makes it absolute. `.parent` is the `web` folder. So `WEB_DIR` is `d:\D2T\web` on this machine.

```python
app = FastAPI(title="D2T Target Discovery", version=__version__)
```

`title` and `version` are labels. FastAPI shows them on the automatic docs page at `http://127.0.0.1:8080/docs`. They do not change the science.

```python
app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
```

`mount` attaches a file server at a URL prefix.

- A browser request for `/static/js/app.js` reads `web/static/js/app.js` and returns the file bytes.
- `name="static"` is an internal label. The templates can ask for a static URL by that name.

```python
templates = Jinja2Templates(directory=WEB_DIR / "templates")
```

This points at `web/templates`. The only page route in this file renders `index.html` from that folder. The page’s JavaScript (`web/static/js/app.js`) then calls the `/api/...` routes below.

---

## 5. The three request bodies

A `GET` request usually has no body. A `POST` from the page sends JSON. FastAPI matches that JSON to a `BaseModel`.

If a required field is missing, or a type is wrong, FastAPI answers **422** by itself. The route function does not run.

### `RunRequest` — launch a pipeline

```python
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
```

`str | None = None` means the field is optional. If the JSON omits it, the value is `None`. `mode` defaults to `"full"`. `skip_literature` and `use_snakemake` default to `False`.

Example JSON from the launch form:

```json
{
  "approach": "both",
  "disease": "Parkinson disease",
  "subtype": "idiopathic",
  "tissue": "brain",
  "skip_literature": false,
  "use_snakemake": false
}
```

| Field | Meaning |
| --- | --- |
| `mode` | Which block to run when `approach` is empty: `full`, `foundation`, `trackA`, `trackB`, or `custom`. |
| `approach` | The form’s main choice: `both`, `track_a`, or `track_b`. If this is set, it overrides `mode`. |
| `disease` | The disease words the user typed. Required for a new run. |
| `subtype` | Extra hint when Step 1 picks among similar disease ids. |
| `tissue` | Tissue words, for example `brain`. |
| `run_id` | An existing run. Required when you continue Track A or Track B on a run that already has Step 1. |
| `disease_id` | Optional ontology id if the caller already knows it. |
| `skip_literature` | If true, Step 2 skips the Europe PMC literature search. |
| `custom_step` | One step id, such as `step1` or `stepB4`, when `mode` is `custom`. |
| `use_snakemake` | If true, the runner uses the Snakemake path instead of calling the Python steps directly. |

### `RegisterRequest`

```python
class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=3)
    password: str = Field(..., min_length=8)
    name: str | None = None
```

`Field(...)` means the field is required. `min_length` rejects a shorter string before the function runs.

```json
{ "email": "ada@example.com", "password": "correct-horse", "name": "Ada" }
```

### `LoginRequest`

```python
class LoginRequest(BaseModel):
    email: str
    password: str
```

Both fields are required. There is no minimum length here. A wrong password is rejected later with 401, not by the model.

---

## 6. Startup

```python
@app.on_event("startup")
async def startup() -> None:
    init_db()
    bootstrap_admin_if_configured()
    migrate_legacy_runs()
```

`@app.on_event("startup")` registers `startup` to run once, after the app is loaded and before it accepts visitors.

`async def` means the function is allowed to wait for network or disk without blocking the description of the app. These three calls are ordinary (synchronous) work. FastAPI still runs them at startup. The `-> None` hint says the function returns nothing.

Order:

1. Create database tables.
2. Create the bootstrap admin if those two environment variables are set.
3. Register old run folders.

---

## 7. Routes, in the order a visit uses them

A decorator such as `@app.get("/health")` connects the next function to that URL. The function’s arguments are filled by FastAPI:

- A `BaseModel` argument comes from the JSON body.
- A name that appears in the path, such as `{run_id}`, comes from the URL.
- A simple argument such as `limit: int = 25` comes from the query string (`?limit=25`).
- `CurrentUser` and `OptionalUser` come from the session cookie.
- `Request` and `Response` are the raw HTTP objects.

The browser code that calls these URLs is `web/static/js/app.js`.

### `GET /health`

```python
@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": __version__}
```

No login. A monitoring check can call this to see that the process is up.

Response:

```json
{ "status": "ok", "version": "0.1.0" }
```

### `GET /`

```python
@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html", {"version": __version__})
```

`response_class=HTMLResponse` sets the content type to HTML.

`TemplateResponse` reads `web/templates/index.html`, replaces the version placeholder, and returns the page. `request` is required by the template engine so it can build links. After this page loads, its JavaScript calls the API routes.

### `GET /api/catalog`

```python
@app.get("/api/catalog")
async def api_catalog() -> dict:
    return {
        "version": __version__,
        "layers": PIPELINE_LAYERS,
        "modes": RUN_MODES,
        "approaches": APPROACH_MODES,
    }
```

No login. The page calls this to draw the step list and the launch choices. The data is the catalog from `web/catalog.py`, plus the version.

### `POST /api/auth/register`

```python
async def api_register(body: RegisterRequest, response: Response) -> dict:
```

- `body` is the JSON, already checked by `RegisterRequest`.
- `response` is the reply FastAPI will send. `start_session` writes the cookie onto it.

Flow:

1. `register_user` saves the user.
2. If it raises `ValueError` (duplicate email, short password), the function raises `HTTPException(400, str(e))`. `from e` keeps the original error attached for logs.
3. `start_session` sets the cookie.
4. The JSON body tells the page who just registered.

Success example:

```json
{ "user_id": "…", "email": "ada@example.com", "name": "Ada" }
```

The cookie is in the response headers, not in this JSON.

### `POST /api/auth/login`

Same shape as register, but `authenticate_user` returns `None` for a bad password. The route then raises 401 with the text `"Invalid email or password"`. A match starts a session and returns the same user JSON.

### `POST /api/auth/logout`

```python
async def api_logout(request: Request, response: Response) -> dict:
    end_session(response, request)
    return {"ok": True}
```

`request` is needed because the cookie arrives on the request. `response` is needed to delete the cookie on the way out. No `CurrentUser` check: logging out with no cookie still returns `{"ok": true}`.

### `GET /api/auth/me`

```python
async def api_me(user: OptionalUser) -> dict:
```

The page calls this on load to decide whether to show the login form or the tool.

Logged out:

```json
{ "authenticated": false }
```

Logged in:

```json
{ "authenticated": true, "user_id": "…", "email": "ada@example.com", "name": "Ada" }
```

### `_require_run` — not a URL

```python
def _require_run(user: OptionalUser, run_id: str) -> None:
    uid = user.user_id if user else None
    if not user_can_access_run(uid, run_id):
        raise HTTPException(404, "Run not found")
```

The leading `_` means “used inside this file.” FastAPI does not expose it.

It takes the user id, or `None` if there is no user, and asks the registry. Failure is always 404. Every route that names a run calls this first.

The argument type is `OptionalUser`, but the callers pass a `CurrentUser`. That is allowed: a logged-in user is one possible value of “user or nothing.”

### `GET /api/runs`

```python
async def api_runs(user: CurrentUser) -> dict:
    return {"runs": list_runs(user_id=user.user_id)}
```

`CurrentUser` stops the request with 401 if the cookie is missing. Then `list_runs` returns that user’s runs. The page uses this for the run list.

### `GET /api/runs/{run_id}/status`

`{run_id}` is a path parameter. For the URL `/api/runs/web_ab12cd34/status`, FastAPI sets `run_id` to `"web_ab12cd34"`.

The function checks access, then returns `run_status(run_id)`. That dict includes `exists`, which artifact files are present, and a `steps` list with `done: true` or `done: false` for each pipeline step. The progress view polls this while a job runs.

### `GET /api/runs/{run_id}/report`

Checks access, then `build_report(run_id)`. If the run folder is missing, `FileNotFoundError` becomes 404. The report page uses this JSON.

### `GET /api/runs/{run_id}/preview/{artifact}`

```python
async def api_preview(run_id: str, artifact: str, user: CurrentUser, limit: int = 25) -> dict:
```

Two path pieces and one query value.

Example: `/api/runs/web_ab12cd34/preview/track_b?limit=25`

`artifact` must be a name `preview_csv` knows, such as `known_genes`, `track_a`, `track_b`, or `fusion`. A bad name raises `ValueError` and becomes 400. A missing file becomes 404. `limit` defaults to 25, so the table preview stays small.

### `POST /api/runs/{run_id}/archive`

Checks access, calls `archive_run(run_id)`, and returns:

```json
{ "run_id": "web_ab12cd34", "archived": true }
```

`archive_run` returns nothing. The name `reg` in the source is unused. The important effect is the database update: the run is archived, so later access checks fail.

### `POST /api/jobs` — start the pipeline

```python
async def api_start_job(body: RunRequest, user: CurrentUser) -> dict:
```

This is the Launch button. The user must be logged in. The function checks the combination of fields before it starts anything:

| Situation | Required extra field | Otherwise |
| --- | --- | --- |
| `approach` is set | It must be one of `APPROACH_MODES`, and `disease` must be set | 400 |
| `mode` is `full` or `foundation`, and there is no approach | `disease` | 400 |
| `mode` is `custom` | `custom_step` | 400 |
| custom step is `step1` | `disease` | 400 |
| custom step is anything else | `run_id` | 400 |
| `mode` is `trackA` or `trackB` | `run_id` | 400 |

If `run_id` is present, `_require_run` confirms this user may continue that run.

It then copies the science inputs into a plain dict and calls `start_job`. That function creates a job id, creates or reuses a run id, and starts the steps on a background thread. A `ValueError` from the runner (unknown mode, missing run id) becomes 400.

Immediate response, before the pipeline finishes:

```json
{ "job_id": "…uuid…", "run_id": "web_ab12cd34", "status": "queued" }
```

The page then polls the next two routes until `status` is `succeeded` or `failed`.

### `GET /api/jobs`

Lists this user’s jobs. It reads the database (`list_jobs_for_user`, last 50) and, when the same job is still in memory (`list_jobs`), prefers the live status, the last 20 log lines, and the live error. A job from an earlier server start has no memory copy, so the stored status and log summary are used.

### `GET /api/jobs/{job_id}`

`get_job` looks only in this process’s memory. Unknown id is 404. A job owned by another user is also 404. The response is the id, run id, command, status, full log, error, and start and finish times.

The page calls this together with `/status` about once a second while the bar is moving.

### `GET /api/runs/{run_id}/download`

Checks access, builds the zip in memory, and returns a `Response` whose body is those bytes.

- `media_type="application/zip"` tells the browser it is a zip file.
- `Content-Disposition: attachment; filename="web_ab12cd34_artifacts.zip"` asks the browser to download it instead of showing it.

### `GET /api/runs/{run_id}/report.pdf`

Same pattern for the PDF: `media_type="application/pdf"` and a filename ending in `_report.pdf`.

### `GET /api/runs/{run_id}/evidence/{gene}`

Example: `/api/runs/web_ab12cd34/evidence/SLC6A3`

Checks access, then returns the evidence-card dict for that gene symbol. A missing run file becomes 404.

### `GET /api/runs/{run_id}/network`

```python
async def api_network_graph(
    run_id: str, user: CurrentUser, top_n: int = Query(40, ge=5, le=120)
) -> dict:
```

`Query(40, ge=5, le=120)` means:

- the URL may say `?top_n=30`
- if it omits `top_n`, the value is 40
- a number below 5 or above 120 is rejected by FastAPI before the function runs

The page asks for `top_n=30`. The dict is the nodes and edges drawn on the network view.

### `GET /api/runs/{run_id}/narrative/{gene}`

Same access check, then `generate_gene_narrative`. The evidence panel calls this after the evidence card so the written paragraph can load on its own.

---

## 8. One visit, start to finish

1. You run `web/server.py`. Python loads `app.py`, then `startup` prepares the database.
2. The browser opens `GET /`. The reply is `index.html`.
3. The page script calls `GET /api/auth/me`. No cookie, so the reply is `authenticated: false`, and the login form is shown.
4. You submit the form. `POST /api/auth/login` checks the password and sets `d2t_session`.
5. The page calls `GET /api/catalog` and `GET /api/runs` to fill the form and the run list.
6. You type Parkinson disease, subtype idiopathic, tissue brain, and choose both tracks. The page sends `POST /api/jobs` with a `RunRequest`.
7. The reply has a `job_id` and a `run_id` while the steps are still running.
8. The page repeats `GET /api/jobs/{job_id}` and `GET /api/runs/{run_id}/status` until the job status is finished.
9. You open the report (`/report`), a table preview (`/preview/track_b`), a gene card (`/evidence/SLC6A3` and `/narrative/SLC6A3`), the network, or a download.

Every URL after login sends the cookie. `CurrentUser` turns that cookie back into `user` before the function body runs. `_require_run` then refuses any run id that is not yours.

---

## 9. What this file deliberately does not do

The scoring steps (`step01_input.py` through `stepB10_rank.py` and fusion) are started by `web/runner.py`, which `start_job` calls. `app.py` checks the request, then hands the work off. Reading a result file is done by `web/runs.py`, `web/report.py`, and the other helpers imported at the top.
