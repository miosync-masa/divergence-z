"""Divergence-Z サイドカー API（FastAPI）。

Electron / Tauri から子プロセスとして起動され、127.0.0.1 だけで待ち受ける。
全リクエストに起動ごとのトークン（Authorization: Bearer / ?token=）を要求する。
API キーはメモリにだけ保持し、ディスク・ログ・ジョブ記録には書かない。
"""

from __future__ import annotations

import asyncio
import hmac
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from divergence_z.chapter_translator import (NOTES_FILE, collect_source_files, estimate_chapter,
                                             open_book)
from divergence_z.core import (Keys, check_fit, dump_yaml, get_model, list_models,
                               load_source_corpus)

from divergence_z.chat import ChatStore, load_template, save_template, template_path
from divergence_z.core import estimate_tokens

from .jobs import TERMINAL, JobManager
from .projects import STEPS, Project, ProjectRegistry
from .tasks import RUNNERS, chat_system

VERSION = "0.2.0"
_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


# =============================================================================
# request models
# =============================================================================

class KeysIn(BaseModel):
    openai: Optional[str] = None            # "" でクリア、None で変更なし
    anthropic: Optional[str] = None
    openai_base_url: Optional[str] = None


class ProjectIn(BaseModel):
    root: str
    name: Optional[str] = None
    work: Optional[str] = None
    source: Optional[str] = None
    output_lang: Optional[str] = None
    review_cast: Optional[bool] = None
    models: Optional[Dict[str, Dict[str, str]]] = None


class ProjectPatch(BaseModel):
    name: Optional[str] = None
    work: Optional[str] = None
    source: Optional[str] = None
    output_lang: Optional[str] = None
    review_cast: Optional[bool] = None
    models: Optional[Dict[str, Dict[str, str]]] = None


class JobIn(BaseModel):
    type: str
    project_id: str
    params: Dict[str, Any] = Field(default_factory=dict)


class YamlIn(BaseModel):
    yaml: str


class TemplateIn(BaseModel):
    text: str


class ChatIn(BaseModel):
    character: str
    model: Optional[str] = None
    effort: Optional[str] = None
    user_profile: str = ""
    title: str = ""


class EstimateIn(BaseModel):
    steps: List[str] = Field(default_factory=lambda: ["cast", "persona", "episode", "translate"])
    characters: Optional[List[str]] = None
    langs: List[str] = Field(default_factory=lambda: ["en"])
    chapters: str = ""
    max_section_chars: int = 6000


# =============================================================================
# app
# =============================================================================

def create_app(token: str, allowed_origins: Optional[List[str]] = None,
               registry: Optional[ProjectRegistry] = None, max_workers: int = 2) -> FastAPI:
    app = FastAPI(title="Divergence-Z sidecar", version=VERSION, docs_url=None, redoc_url=None,
                  openapi_url=None)
    state: Dict[str, Any] = {
        "keys": Keys(),
        "registry": registry or ProjectRegistry(),
        "jobs": JobManager(RUNNERS, max_workers=max_workers),
    }
    app.state.dz = state

    if allowed_origins:
        app.add_middleware(CORSMiddleware, allow_origins=allowed_origins, allow_credentials=False,
                           allow_methods=["*"], allow_headers=["Authorization", "Content-Type",
                                                               "Last-Event-ID"])

    @app.middleware("http")
    async def guard(request: Request, call_next):
        # DNS rebinding 対策: Host は loopback のみ
        host = (request.headers.get("host") or "").rsplit(":", 1)[0]
        if host not in _ALLOWED_HOSTS:
            return JSONResponse({"error": "forbidden host"}, status_code=403)
        if request.method == "OPTIONS" or request.url.path == "/health":
            return await call_next(request)
        auth = request.headers.get("authorization", "")
        supplied = auth[7:] if auth.lower().startswith("bearer ") else request.query_params.get("token", "")
        if not supplied or not hmac.compare_digest(supplied, token):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)

    @app.on_event("shutdown")
    def _shutdown() -> None:
        state["jobs"].shutdown()

    registry_: ProjectRegistry = state["registry"]
    jobs: JobManager = state["jobs"]

    def project_or_404(project_id: str) -> Project:
        project = registry_.get(project_id)
        if not project:
            raise HTTPException(404, "project not found")
        return project

    # --- health / session ---------------------------------------------------------

    @app.get("/health")
    def health():
        return {"ok": True, "version": VERSION}

    @app.get("/session/keys")
    def get_keys():
        k: Keys = state["keys"]
        return {"openai": bool(k.openai), "anthropic": bool(k.anthropic),
                "openai_base_url": k.openai_base_url}

    @app.put("/session/keys")
    def put_keys(body: KeysIn):
        k: Keys = state["keys"]
        for name in ("openai", "anthropic", "openai_base_url"):
            value = getattr(body, name)
            if value is not None:
                setattr(k, name, value or None)
        return get_keys()

    # --- models -----------------------------------------------------------------------

    @app.get("/models")
    def models():
        return {"models": [asdict(m) for m in list_models()]}

    # --- projects -----------------------------------------------------------------------

    @app.get("/projects")
    def projects():
        return {"projects": [p.to_dict() for p in registry_.list()]}

    @app.post("/projects")
    def open_project(body: ProjectIn):
        root = Path(body.root).expanduser()
        cfg = body.model_dump(exclude={"root"}, exclude_none=True)
        return registry_.open(root, **cfg).to_dict()

    @app.get("/projects/{project_id}")
    def get_project(project_id: str):
        project = project_or_404(project_id)
        status = {"cast": project.cast_path.exists(), "personas": {}, "episodes": {}}
        for label in project.cast_labels():
            status["personas"][label] = bool(project.persona_file(label))
            status["episodes"][label] = bool(project.episode_file(label))
        return {**project.to_dict(), "status": status}

    @app.patch("/projects/{project_id}")
    def patch_project(project_id: str, body: ProjectPatch):
        project = project_or_404(project_id)
        for key, value in body.model_dump(exclude_none=True).items():
            if key == "models":
                unknown = set(value) - set(STEPS)
                if unknown:
                    raise HTTPException(422, f"unknown steps: {sorted(unknown)}")
                project.models = {**project.models, **value}
            else:
                setattr(project, key, value)
        registry_.update(project)
        return project.to_dict()

    @app.delete("/projects/{project_id}")
    def close_project(project_id: str):
        project_or_404(project_id)
        registry_.close(project_id)   # フォルダは消さない
        return {"ok": True}

    # --- cast / persona / episode ----------------------------------------------------------

    def _write_yaml(path: Path, text: str) -> None:
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as e:
            raise HTTPException(422, f"YAML parse error: {e}")
        if not isinstance(data, dict):
            raise HTTPException(422, "YAML root must be a mapping")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    @app.get("/projects/{project_id}/cast")
    def get_cast(project_id: str):
        project = project_or_404(project_id)
        if not project.cast_path.exists():
            raise HTTPException(404, "cast sheet not found")
        text = project.cast_text()
        return {"path": project.cast_file, "yaml": text, "data": yaml.safe_load(text)}

    @app.put("/projects/{project_id}/cast")
    def put_cast(project_id: str, body: YamlIn):
        project = project_or_404(project_id)
        _write_yaml(project.cast_path, body.yaml)
        return {"ok": True, "path": project.cast_file}

    def _character_doc(project: Project, kind: str, label: str) -> Path:
        path = project.persona_file(label) if kind == "persona" else project.episode_file(label)
        if not path:
            raise HTTPException(404, f"{kind} not found: {label}")
        return path

    def register_character_docs(kind: str) -> None:
        """persona / episode の一覧・取得・編集（ルートは種類ごとに明示して衝突を避ける）"""
        base = f"/projects/{{project_id}}/{kind}s"

        def list_docs(project_id: str):
            project = project_or_404(project_id)
            directory = project.persona_dir if kind == "persona" else project.episode_dir
            files = sorted(p.name for p in directory.glob("*.yaml")) if directory.is_dir() else []
            return {"files": files}

        def get_doc(project_id: str, label: str):
            path = _character_doc(project_or_404(project_id), kind, label)
            return {"path": path.name, "yaml": path.read_text(encoding="utf-8")}

        def put_doc(project_id: str, label: str, body: YamlIn):
            path = _character_doc(project_or_404(project_id), kind, label)
            _write_yaml(path, body.yaml)
            return {"ok": True, "path": path.name}

        app.add_api_route(base, list_docs, methods=["GET"], name=f"list_{kind}s")
        app.add_api_route(base + "/{label}", get_doc, methods=["GET"], name=f"get_{kind}")
        app.add_api_route(base + "/{label}", put_doc, methods=["PUT"], name=f"put_{kind}")

    register_character_docs("persona")
    register_character_docs("episode")

    # --- translations ---------------------------------------------------------------------

    @app.get("/projects/{project_id}/translations/{lang}")
    def list_translations(project_id: str, lang: str):
        project = project_or_404(project_id)
        out_dir = project.translation_dir(lang)
        chapters = []
        for f in collect_source_files(str(project.source_path())) if project.source else []:
            done = out_dir / f"{f.stem}.{lang}.md"
            partial = out_dir / f"{f.stem}.{lang}_INCOMPLETE.md"
            chapters.append({"chapter": f.stem, "file": f.name,
                             "status": "done" if done.exists() else
                             "incomplete" if partial.exists() else "pending"})
        return {"lang": lang, "chapters": chapters, "notes": (out_dir / NOTES_FILE).exists()}

    @app.get("/projects/{project_id}/translations/{lang}/notes")
    def get_notes(project_id: str, lang: str):
        path = project_or_404(project_id).translation_dir(lang) / NOTES_FILE
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        return {"yaml": text, "data": yaml.safe_load(text) if text else {}}

    @app.put("/projects/{project_id}/translations/{lang}/notes")
    def put_notes(project_id: str, lang: str, body: YamlIn):
        path = project_or_404(project_id).translation_dir(lang) / NOTES_FILE
        _write_yaml(path, body.yaml)
        return {"ok": True}

    @app.get("/projects/{project_id}/translations/{lang}/{chapter}")
    def get_chapter(project_id: str, lang: str, chapter: str):
        project = project_or_404(project_id)
        stems = {f.stem for f in collect_source_files(str(project.source_path()))}
        if chapter not in stems:
            raise HTTPException(404, "chapter not found")
        seg = project.translation_dir(lang) / f"{chapter}.{lang}.segments.json"
        if not seg.exists():
            raise HTTPException(404, "not translated yet")
        return {"chapter": chapter, "lang": lang,
                "segments": json.loads(seg.read_text(encoding="utf-8"))}

    # --- characters / chat ----------------------------------------------------------------

    @app.get("/projects/{project_id}/characters")
    def characters(project_id: str):
        """会話・ボイスに使える人物（ペルソナがある人物）。人物表のラベル＋人物表に無い Web 生成分"""
        project = project_or_404(project_id)
        out, seen = [], set()
        for label in project.cast_labels():
            p, e = project.persona_file(label), project.episode_file(label)
            if p:
                seen.add(p.name)
                out.append({"label": label, "persona": p.name, "episode": e.name if e else None,
                            "in_cast": True})
        for f in sorted(project.persona_dir.glob("*.yaml")) if project.persona_dir.is_dir() else []:
            if f.name in seen:
                continue
            try:
                name = (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("persona", {}).get("name")
            except yaml.YAMLError:
                name = None
            label = name or f.stem
            e = project.episode_file(label)
            out.append({"label": label, "persona": f.name, "episode": e.name if e else None,
                        "in_cast": False})
        return {"characters": out}

    @app.get("/chat/template")
    def get_template():
        return {"text": load_template(), "path": str(template_path()), "custom": template_path().exists()}

    @app.put("/chat/template")
    def put_template(body: TemplateIn):
        if "{{PERSONA_EPISODE}}" not in body.text:
            raise HTTPException(422, "テンプレートに {{PERSONA_EPISODE}}（ペルソナとエピソードの差し込み口）が必要です")
        save_template(body.text)
        return {"ok": True}

    @app.get("/projects/{project_id}/chats")
    def list_chats(project_id: str):
        return {"chats": ChatStore(project_or_404(project_id).root).list()}

    @app.post("/projects/{project_id}/chats")
    def create_chat(project_id: str, body: ChatIn):
        project = project_or_404(project_id)
        if not project.persona_file(body.character):
            raise HTTPException(422, f"ペルソナがありません: {body.character}")
        m = project.model_for("voice")
        chat = ChatStore(project.root).create(body.character, body.model or m["model"],
                                              body.effort or m.get("effort"), body.user_profile,
                                              body.title)
        return chat

    def chat_or_404(project: Project, chat_id: str):
        try:
            return ChatStore(project.root).get(chat_id)
        except KeyError:
            raise HTTPException(404, "chat not found")

    @app.get("/projects/{project_id}/chats/{chat_id}")
    def get_chat(project_id: str, chat_id: str):
        project = project_or_404(project_id)
        chat = chat_or_404(project, chat_id)
        system = chat_system(project, chat)
        return {**chat, "system_chars": len(system), "system_tokens": estimate_tokens(system)}

    @app.get("/projects/{project_id}/chats/{chat_id}/system")
    def get_chat_system(project_id: str, chat_id: str):
        project = project_or_404(project_id)
        return {"text": chat_system(project, chat_or_404(project, chat_id))}

    @app.delete("/projects/{project_id}/chats/{chat_id}")
    def delete_chat(project_id: str, chat_id: str):
        project = project_or_404(project_id)
        chat_or_404(project, chat_id)
        ChatStore(project.root).delete(chat_id)
        return {"ok": True}

    # --- estimate -----------------------------------------------------------------------

    @app.post("/projects/{project_id}/estimate")
    def estimate(project_id: str, body: EstimateIn):
        """API を呼ばずに、各ステップのトークン数・コンテキスト適合・概算費用を返す"""
        from divergence_z.cast_extractor import SYSTEM_PROMPT as CAST_SYSTEM
        from divergence_z.episode_extractor import build_extraction_system_prompt
        from divergence_z.persona_extractor_v2 import build_extraction_prompt

        project = project_or_404(project_id)
        if not project.source:
            raise HTTPException(422, "project.source is not set")
        corpus, manifest = load_source_corpus(str(project.source_path()))
        cast_text = project.cast_text()
        characters = body.characters or project.cast_labels("main")
        rows: List[Dict[str, Any]] = []

        def add(step: str, target: str, prompt: str, output: int):
            m = project.model_for(step)
            fit = check_fit(get_model(m["model"]), prompt, output)
            rows.append({"step": step, "target": target, "model": m["model"], **asdict(fit)})

        if "cast" in body.steps:
            add("cast", "cast", CAST_SYSTEM + corpus, 30000)
        for label in characters if "persona" in body.steps else []:
            add("persona", label, build_extraction_prompt(project.output_lang) + corpus + cast_text, 30000)
        for label in characters if "episode" in body.steps else []:
            add("episode", label,
                build_extraction_system_prompt(project.output_lang) + corpus + cast_text, 40000)
        if "translate" in body.steps:
            book = open_book(str(project.source_path()), str(project.cast_path) if cast_text else "",
                             str(project.persona_dir), str(project.episode_dir))
            from divergence_z.chapter_translator import parse_chapter_selection
            for lang in body.langs:
                m = project.model_for("translate")
                for idx in parse_chapter_selection(body.chapters, len(book.files)):
                    # 長い章は計画 + セクションごとの呼び出しの合計
                    fit = estimate_chapter(book, idx, project.translation_dir(lang), m["model"], lang,
                                           max_section_chars=body.max_section_chars)
                    rows.append({"step": "translate", "target": f"{book.files[idx].name}:{lang}",
                                 "model": m["model"], **asdict(fit)})

        costs = [r["cost_usd"] for r in rows]
        return {
            "source": {"files": len(manifest), "chars": len(corpus)},
            "characters": characters,
            "rows": rows,
            "total_input_tokens": sum(r["input_tokens"] for r in rows),
            "total_output_tokens": sum(r["output_tokens"] for r in rows),
            "total_cost_usd": None if any(c is None for c in costs) else round(sum(costs), 2),
            "all_fit": None if any(r["fits"] is None for r in rows) else all(r["fits"] for r in rows),
            "note": "translate rows reflect personas/episodes that exist now" if "translate" in body.steps else "",
        }

    # --- jobs -----------------------------------------------------------------------------

    @app.post("/jobs", status_code=202)
    def submit_job(body: JobIn):
        project = project_or_404(body.project_id)
        if body.type not in RUNNERS:
            raise HTTPException(422, f"unknown job type: {body.type} (one of {sorted(RUNNERS)})")
        job = jobs.submit(body.type, project, body.params, state["keys"])
        return job.summary()

    @app.get("/jobs")
    def list_jobs(project_id: Optional[str] = None):
        return {"jobs": [j.summary() for j in jobs.list(project_id)]}

    def job_or_404(job_id: str):
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        return job

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str):
        return job_or_404(job_id).summary()

    @app.post("/jobs/{job_id}/cancel")
    def cancel_job(job_id: str):
        job = job_or_404(job_id)
        job.cancel()
        return job.summary()

    @app.post("/jobs/{job_id}/resume")
    def resume_job(job_id: str):
        job = job_or_404(job_id)
        if not job.resume():
            raise HTTPException(409, f"job is {job.status}, not awaiting_review")
        return job.summary()

    @app.get("/jobs/{job_id}/events")
    async def job_events(job_id: str, request: Request, last_event_id: int = 0):
        """SSE。再接続時は Last-Event-ID（または ?last_event_id=）以降を送る"""
        job = job_or_404(job_id)
        header = request.headers.get("last-event-id")
        start = int(header) if header and header.isdigit() else last_event_id

        async def stream():
            last = start
            idle = 0.0
            while True:
                if await request.is_disconnected():
                    return
                events = job.events_after(last)
                for e in events:
                    last = e.id
                    payload = json.dumps(e.data, ensure_ascii=False, default=str)
                    yield f"id: {e.id}\nevent: {e.type}\ndata: {payload}\n\n"
                if events:
                    idle = 0.0
                if job.status in TERMINAL and not job.events_after(last):
                    return
                await asyncio.sleep(0.25)
                idle += 0.25
                if idle >= 15:
                    idle = 0.0
                    yield ": keep-alive\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return app
