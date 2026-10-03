"""ジョブ種別ごとの処理。ライブラリ関数を呼び、成果物をプロジェクトフォルダに保存する。

各 runner は (job, keys) を受け取り、UI に返す result dict を返す。
キャラクター1人・章1つごとに job.check() で中止を確認する。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from divergence_z.cast_extractor import extract_cast
from divergence_z.chapter_translator import (chapter_output_path, open_book,
                                             parse_chapter_selection, translate_chapter)
from divergence_z.core import LLM, Keys, load_source_corpus
from divergence_z.episode_extractor import extract_episodes, output_path_for
from divergence_z.episode_generator import generate_episodes, save_episodes
from divergence_z.persona_extractor_v2 import extract_persona
from divergence_z.persona_extractor_v2 import save_persona as save_extracted_persona
from divergence_z.persona_generator import generate_persona
from divergence_z.persona_generator import save_persona as save_generated_persona
from divergence_z.persona_voice import (DEFAULT_RESPONSE_STEPS, DEFAULT_THINKING_STEPS,
                                        respond_voice, transform_voice)

from .jobs import Job, JobInputError, Runner
from .projects import Project


# =============================================================================
# helpers
# =============================================================================

def _llm(job: Job, keys: Keys) -> LLM:
    return LLM(keys, progress=lambda m: job.progress(m), cancel=job.cancel_token)


def _track(job: Job, llm: LLM) -> None:
    job.usage = llm.total_usage()


def _rel(project: Project, path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(project.root))
    except ValueError:
        return str(path)


class _Corpus:
    """ジョブ内で原稿を1回だけ読む"""

    def __init__(self, job: Job):
        self.job = job
        self._text: Optional[str] = None

    @property
    def text(self) -> str:
        if self._text is None:
            project = self.job.project
            if not project.source:
                raise JobInputError("project.source (原稿フォルダ) が設定されていません")
            src = project.source_path()
            if not src.exists():
                raise JobInputError(f"原稿が見つかりません: {src}")
            self._text, manifest = load_source_corpus(str(src))
            self.job.progress(f"📖 {len(manifest)} file(s), {len(self._text):,} chars")
        return self._text


def _characters(job: Job, explicit: Optional[List[str]]) -> List[str]:
    """明示指定 > 人物表の main > エラー"""
    if explicit:
        return list(explicit)
    mains = job.project.cast_labels("main")
    if not mains:
        raise JobInputError("characters を指定するか、人物表（importance: main）を用意してください")
    return mains


def _step(job: Job, step: str) -> Dict[str, str]:
    cfg = job.project.model_for(step)
    override = job.params.get("models", {}).get(step) or {}
    return {**cfg, **override}


# =============================================================================
# build steps
# =============================================================================

def run_cast(job: Job, keys: Keys, corpus: Optional[_Corpus] = None,
             llm: Optional[LLM] = None) -> Dict[str, Any]:
    project = job.project
    corpus = corpus or _Corpus(job)
    llm = llm or _llm(job, keys)
    m = _step(job, "cast")
    job.progress("🗂  Cast sheet", step="cast")
    result = extract_cast(corpus.text, llm=llm, work=project.work or project.name,
                          hint=job.params.get("hint", ""), model=m["model"], effort=m.get("effort"),
                          progress=job.progress)
    _track(job, llm)
    path = project.cast_path
    if result.data is None:
        path = path.with_name(path.stem + "_BROKEN.yaml")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.yaml_text, encoding="utf-8")
    job.artifact("cast", _rel(project, path), ok=result.data is not None,
                 characters=len(result.characters))
    if result.data is None:
        raise JobInputError(f"人物表の YAML が壊れています（{_rel(project, path)}）: {result.error}")
    return {"cast_file": _rel(project, path),
            "characters": [{"label": c.get("label"), "importance": c.get("importance")}
                           for c in result.characters]}


def run_persona(job: Job, keys: Keys, corpus: Optional[_Corpus] = None,
                llm: Optional[LLM] = None, characters: Optional[List[str]] = None) -> Dict[str, Any]:
    project = job.project
    corpus = corpus or _Corpus(job)
    llm = llm or _llm(job, keys)
    m = _step(job, "persona")
    labels = characters or _characters(job, job.params.get("characters"))
    force = bool(job.params.get("force"))
    done: List[Dict[str, Any]] = []
    for i, label in enumerate(labels):
        job.check()
        existing = project.persona_file(label)
        if existing and not force:
            job.progress(f"⏭  persona exists: {label}", step="persona", index=i, total=len(labels))
            done.append({"character": label, "path": _rel(project, existing), "skipped": True})
            continue
        job.progress(f"🎭 persona: {label}", step="persona", index=i, total=len(labels))
        r = extract_persona(corpus.text, label, llm=llm, model=m["model"], effort=m.get("effort"),
                            output_lang=project.output_lang, cast_text=project.cast_text(),
                            progress=job.progress)
        _track(job, llm)
        path = save_extracted_persona(r.yaml_text, label, str(project.persona_dir))
        job.artifact("persona", _rel(project, Path(path)), character=label, valid=r.valid,
                     issues=r.issues)
        done.append({"character": label, "path": _rel(project, Path(path)), "valid": r.valid,
                     "issues": r.issues})
    return {"personas": done}


def run_episode(job: Job, keys: Keys, corpus: Optional[_Corpus] = None,
                llm: Optional[LLM] = None, characters: Optional[List[str]] = None) -> Dict[str, Any]:
    project = job.project
    corpus = corpus or _Corpus(job)
    llm = llm or _llm(job, keys)
    m = _step(job, "episode")
    labels = characters or _characters(job, job.params.get("characters"))
    force = bool(job.params.get("force"))
    done: List[Dict[str, Any]] = []
    for i, label in enumerate(labels):
        job.check()
        existing = project.episode_file(label)
        if existing and not force:
            job.progress(f"⏭  episode exists: {label}", step="episode", index=i, total=len(labels))
            done.append({"character": label, "path": _rel(project, existing), "skipped": True})
            continue
        job.progress(f"📖 episodes: {label}", step="episode", index=i, total=len(labels))
        persona_path = project.persona_file(label)
        r = extract_episodes(corpus.text, label, llm=llm, work=project.work or project.name,
                             model=m["model"], effort=m.get("effort"),
                             output_lang=project.output_lang,
                             persona_text=persona_path.read_text(encoding="utf-8") if persona_path else "",
                             cast_text=project.cast_text(),
                             max_episodes=int(job.params.get("max_episodes", 20)),
                             progress=job.progress)
        _track(job, llm)
        path, ok = save_episodes(r.yaml_text, str(output_path_for(label, str(project.episode_dir))),
                                 r.issues)
        info = {"character": label, "path": _rel(project, Path(path)), "valid": r.valid,
                "issues": r.issues, "episodes": r.episode_count,
                "quotes_total": r.quotes_total, "quotes_missing": len(r.quotes_missing)}
        job.artifact("episode", info["path"], **{k: v for k, v in info.items() if k != "path"})
        done.append(info)
    return {"episodes": done}


def run_translate(job: Job, keys: Keys, llm: Optional[LLM] = None,
                  lang: Optional[str] = None) -> Dict[str, Any]:
    project = job.project
    llm = llm or _llm(job, keys)
    m = _step(job, "translate")
    lang = lang or job.params.get("lang") or "en"
    if not project.source:
        raise JobInputError("project.source (原稿フォルダ) が設定されていません")
    book = open_book(str(project.source_path()), str(project.cast_path) if project.cast_path.exists() else "",
                     str(project.persona_dir), str(project.episode_dir))
    out_dir = project.translation_dir(lang)
    chapters = parse_chapter_selection(job.params.get("chapters", ""), len(book.files))
    force = bool(job.params.get("force"))
    results: List[Dict[str, Any]] = []
    for n, idx in enumerate(chapters):
        job.check()
        name = book.files[idx].name
        if chapter_output_path(book, idx, out_dir, lang).exists() and not force:
            job.progress(f"⏭  already translated: {name}", step="translate", index=n,
                         total=len(chapters), lang=lang)
            results.append({"chapter": name, "skipped": True})
            continue
        job.progress(f"🌐 {name} → {lang}", step="translate", index=n, total=len(chapters), lang=lang)
        r = translate_chapter(book, idx, llm=llm, out_dir=out_dir, target_lang=lang,
                              model=m["model"], effort=m.get("effort"),
                              previous=int(job.params.get("previous", 2)), progress=job.progress)
        _track(job, llm)
        info = {"chapter": name, "complete": r.complete, "segments": r.segments,
                "issues": r.issues, "notes_added": r.notes_added, "notes_error": r.notes_error}
        job.artifact("translation", _rel(project, r.output_path), lang=lang,
                     **{k: v for k, v in info.items()})
        results.append(info)
    return {"lang": lang, "chapters": results}


# =============================================================================
# voice / web generation
# =============================================================================

def _load_yaml(path: Path) -> Dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _resolve_persona(project: Project, ref: str) -> Path:
    path = project.persona_file(ref) or (project.root / ref)
    if not path.exists():
        raise JobInputError(f"persona が見つかりません: {ref}")
    return path


def run_voice(job: Job, keys: Keys) -> Dict[str, Any]:
    project = job.project
    p = job.params
    if not p.get("persona") or not p.get("input"):
        raise JobInputError("persona と input は必須です")
    llm = _llm(job, keys)
    m = _step(job, "voice")
    persona = _load_yaml(_resolve_persona(project, p["persona"]))
    ep_path = project.episode_file(p["persona"])
    episode = _load_yaml(ep_path) if ep_path and p.get("use_episode", True) else None
    target = _load_yaml(_resolve_persona(project, p["target"])) if p.get("target") else None

    phase1 = transform_voice(llm=llm, persona_data=persona, input_text=p["input"],
                             context=p.get("context", ""),
                             thinking_steps_template=DEFAULT_THINKING_STEPS,
                             target_persona_data=target, episode_data=episode,
                             model=m["model"], effort=m.get("effort"),
                             show_thinking=bool(p.get("show_thinking")),
                             output_lang=p.get("output_lang"))
    _track(job, llm)
    result: Dict[str, Any] = {"phase1": phase1}
    if p.get("dual") and target:
        job.check()
        target_ep_path = project.episode_file(p["target"])
        result["phase2"] = respond_voice(
            llm=llm, responder_data=target, speaker_data=persona,
            speaker_utterance=phase1["output"], context=p.get("context", ""),
            response_steps_template=DEFAULT_RESPONSE_STEPS,
            responder_episode_data=_load_yaml(target_ep_path) if target_ep_path else None,
            model=m["model"], effort=m.get("effort"), show_thinking=bool(p.get("show_thinking")),
            output_lang=p.get("output_lang"))
        _track(job, llm)
    return result


def run_generate_persona(job: Job, keys: Keys) -> Dict[str, Any]:
    project, p = job.project, job.params
    if not p.get("name") or not p.get("source"):
        raise JobInputError("name と source は必須です")
    llm = _llm(job, keys)
    m = _step(job, "generate")
    lang = p.get("lang") or project.output_lang
    r = generate_persona(p["name"], p["source"], p.get("desc", ""), llm=llm, output_lang=lang,
                         model=m["model"], effort=m.get("effort"),
                         web_search=p.get("web_search", True), progress=job.progress)
    _track(job, llm)
    path = save_generated_persona(r.yaml_text, p["name"], lang, str(project.persona_dir))
    job.artifact("persona", _rel(project, Path(path)), character=p["name"], valid=r.valid,
                 issues=r.issues)
    return {"path": _rel(project, Path(path)), "valid": r.valid, "issues": r.issues,
            "searches": r.research.searches if r.research else 0}


def run_generate_episodes(job: Job, keys: Keys) -> Dict[str, Any]:
    project, p = job.project, job.params
    if not p.get("name") or not p.get("source"):
        raise JobInputError("name と source は必須です")
    llm = _llm(job, keys)
    m = _step(job, "generate")
    persona_path = project.persona_file(p["name"])
    r = generate_episodes(p["name"], p["source"], p.get("desc", ""), llm=llm,
                          model=m["model"], effort=m.get("effort"),
                          output_lang=p.get("lang") or project.output_lang,
                          web_search=p.get("web_search", True),
                          include_sequel=bool(p.get("sequel")),
                          max_episodes=int(p.get("max_episodes", 20)),
                          persona_text=persona_path.read_text(encoding="utf-8") if persona_path else "",
                          progress=job.progress)
    _track(job, llm)
    safe = re.sub(r'[\\/:*?"<>|]', "", p["name"].replace(" ", "_"))
    path, ok = save_episodes(r.yaml_text, str(project.episode_dir / f"{safe}_Episode.yaml"), r.issues)
    job.artifact("episode", _rel(project, Path(path)), character=p["name"], valid=r.valid,
                 episodes=r.episode_count)
    return {"path": _rel(project, Path(path)), "valid": r.valid, "issues": r.issues,
            "episodes": r.episode_count}


# =============================================================================
# pipeline
# =============================================================================

def run_pipeline(job: Job, keys: Keys) -> Dict[str, Any]:
    """人物表 →（確認待ち）→ persona / episode → 翻訳 を一気通貫で"""
    project, p = job.project, job.params
    corpus = _Corpus(job)
    llm = _llm(job, keys)
    result: Dict[str, Any] = {}

    if project.cast_path.exists() and not p.get("force_cast"):
        job.progress(f"⏭  cast exists: {_rel(project, project.cast_path)}", step="cast")
    else:
        result["cast"] = run_cast(job, keys, corpus, llm)

    review = p.get("review_cast", project.review_cast)
    if review:
        job.wait_for_review("cast_ready", cast_file=_rel(project, project.cast_path))

    characters = _characters(job, p.get("characters"))
    job.progress(f"🎭 characters: {', '.join(characters)}", step="plan")
    result["persona"] = run_persona(job, keys, corpus, llm, characters)
    result["episode"] = run_episode(job, keys, corpus, llm, characters)

    result["translate"] = []
    for lang in p.get("translate_langs") or []:
        job.check()
        result["translate"].append(run_translate(job, keys, llm, lang))
    return result


RUNNERS: Dict[str, Runner] = {
    "cast": run_cast,
    "persona": run_persona,
    "episode": run_episode,
    "translate": run_translate,
    "voice": run_voice,
    "generate_persona": run_generate_persona,
    "generate_episodes": run_generate_episodes,
    "pipeline": run_pipeline,
}
