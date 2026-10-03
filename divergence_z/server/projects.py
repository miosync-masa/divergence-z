"""プロジェクト（作品1つ = フォルダ1つ）。

MyProject/
  project.yaml          作品名・原稿のパス・言語・ステップごとのモデル設定
  casts/ personas/ episodes/
  translations/<lang>/  chapter_translator の出力
  .dz/jobs/<id>.json    ジョブ履歴（API キーは含まない）

既存の CLI 出力フォルダもそのまま開ける（project.yaml が無ければ既定値で作る）。
開いたプロジェクトの一覧は ~/.divergence_z/projects.json に保持する。
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from divergence_z.chapter_translator import find_character_file
from divergence_z.core import dump_yaml

STEPS = ("cast", "persona", "episode", "translate", "voice", "generate")

DEFAULT_MODELS: Dict[str, Dict[str, str]] = {
    "cast": {"model": "gpt-5.6-sol", "effort": "high"},
    "persona": {"model": "gpt-5.6-sol", "effort": "max"},
    "episode": {"model": "gpt-5.6-sol", "effort": "max"},
    "translate": {"model": "gpt-5.6-sol", "effort": "high"},
    "voice": {"model": "claude-opus-5-5", "effort": "high"},
    "generate": {"model": "claude-opus-5-5", "effort": "high"},
}

REGISTRY_PATH = Path(os.getenv("DZ_HOME") or Path.home() / ".divergence_z") / "projects.json"


@dataclass
class Project:
    id: str
    root: Path
    name: str
    work: str = ""
    source: str = ""                       # 原稿フォルダ / ファイル（絶対パス推奨）
    output_lang: str = "ja"                # persona / episode の説明文の言語
    cast_file: str = "casts/cast.yaml"
    review_cast: bool = True               # pipeline で人物表の確認待ちを挟むか
    models: Dict[str, Dict[str, str]] = field(default_factory=lambda: dict(DEFAULT_MODELS))

    # --- paths ---------------------------------------------------------------

    @property
    def cast_path(self) -> Path:
        return self.root / self.cast_file

    @property
    def persona_dir(self) -> Path:
        return self.root / "personas"

    @property
    def episode_dir(self) -> Path:
        return self.root / "episodes"

    def translation_dir(self, lang: str) -> Path:
        return self.root / "translations" / lang

    @property
    def jobs_dir(self) -> Path:
        return self.root / ".dz" / "jobs"

    def source_path(self) -> Path:
        p = Path(self.source)
        return p if p.is_absolute() else (self.root / p)

    def persona_file(self, label: str) -> Optional[Path]:
        return find_character_file(label, self.persona_dir, "persona")

    def episode_file(self, label: str) -> Optional[Path]:
        return find_character_file(label, self.episode_dir, "episode")

    def model_for(self, step: str) -> Dict[str, str]:
        return {**DEFAULT_MODELS.get(step, {}), **(self.models.get(step) or {})}

    # --- cast ----------------------------------------------------------------

    def cast(self) -> Dict[str, Any]:
        if not self.cast_path.exists():
            return {}
        return yaml.safe_load(self.cast_path.read_text(encoding="utf-8")) or {}

    def cast_text(self) -> str:
        return self.cast_path.read_text(encoding="utf-8") if self.cast_path.exists() else ""

    def cast_labels(self, importance: Optional[str] = None) -> List[str]:
        return [c["label"] for c in self.cast().get("characters") or []
                if c.get("label") and (importance is None or c.get("importance") == importance)]

    # --- persistence -----------------------------------------------------------

    def to_config(self) -> Dict[str, Any]:
        return {"name": self.name, "work": self.work, "source": self.source,
                "output_lang": self.output_lang, "cast_file": self.cast_file,
                "review_cast": self.review_cast, "models": self.models}

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "root": str(self.root), **self.to_config(),
                "models": {s: self.model_for(s) for s in STEPS}}

    def save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "project.yaml").write_text(dump_yaml(self.to_config()), encoding="utf-8")


def project_id_for(root: Path) -> str:
    return hashlib.sha1(str(root.resolve()).encode()).hexdigest()[:12]


def load_project(root: Path) -> Project:
    root = root.resolve()
    cfg_path = root / "project.yaml"
    cfg = (yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}) if cfg_path.exists() else {}
    project = Project(id=project_id_for(root), root=root, name=cfg.get("name") or root.name)
    for key in ("work", "source", "output_lang", "cast_file", "review_cast"):
        if key in cfg:
            setattr(project, key, cfg[key])
    project.models = {**DEFAULT_MODELS, **(cfg.get("models") or {})}

    # CLI で作ったフォルダ: casts/ に人物表が1つだけあればそれを使う
    if not cfg.get("cast_file") and not project.cast_path.exists():
        found = sorted((root / "casts").glob("*_cast.yaml")) if (root / "casts").is_dir() else []
        if len(found) == 1:
            project.cast_file = str(found[0].relative_to(root))
    return project


class ProjectRegistry:
    def __init__(self, path: Path = REGISTRY_PATH):
        self.path = path
        self._lock = threading.Lock()
        self._projects: Dict[str, Project] = {}
        for root in self._read():
            if Path(root).is_dir():
                p = load_project(Path(root))
                self._projects[p.id] = p

    def _read(self) -> List[str]:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8")).get("projects", [])
            except (json.JSONDecodeError, OSError):
                return []
        return []

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"projects": [str(p.root) for p in self._projects.values()]},
                                        ensure_ascii=False, indent=1), encoding="utf-8")

    def list(self) -> List[Project]:
        return list(self._projects.values())

    def get(self, project_id: str) -> Optional[Project]:
        return self._projects.get(project_id)

    def open(self, root: Path, **config: Any) -> Project:
        """既存フォルダを開く / 新規作成する。config で project.yaml の値を上書き"""
        with self._lock:
            project = load_project(root)
            for key, value in config.items():
                if value is not None and hasattr(project, key):
                    setattr(project, key, value)
            project.save()
            self._projects[project.id] = project
            self._write()
            return project

    def update(self, project: Project) -> None:
        with self._lock:
            project.save()
            self._projects[project.id] = project

    def close(self, project_id: str) -> None:
        with self._lock:
            self._projects.pop(project_id, None)
            self._write()
