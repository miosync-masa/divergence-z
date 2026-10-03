"""モデル登録表。

UI のモデル選択・コンテキスト長チェック・費用見積もりはすべてここを参照する。
モデル名の文字列から能力を推測する処理（旧 `_is_pro_tier_model` 等）は、
登録表に無いモデルのフォールバックとしてだけ使う。

利用者が自分のモデルを足す／値を直すには YAML を置く:
    $DZ_MODELS  または  ~/.divergence_z/models.yaml
    （書式は models.example.yaml）
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Dict, List, Optional

import yaml

EFFORTS = ["none", "low", "medium", "high", "xhigh", "max"]


@dataclass(frozen=True)
class ModelSpec:
    id: str
    provider: str                          # "anthropic" | "openai"
    label: str = ""
    context_window: Optional[int] = None   # 入力上限トークン（不明なら None）
    max_output: Optional[int] = None       # 出力上限トークン
    # 推論の制御方式
    #   anthropic: "adaptive"（effort で制御）/ "budget"（旧モデル: budget_tokens）/ "none"
    #   openai:    "effort"（reasoning.effort）/ "none"
    reasoning: str = "none"
    efforts: List[str] = field(default_factory=list)
    default_effort: Optional[str] = None
    background: bool = False               # openai: 同期呼び出し不可（Pro/SOL 等）→ background + polling
    web_search: Optional[str] = None       # anthropic: server tool の type。None なら非対応
    fallbacks: bool = False                # anthropic: server-side refusal fallback を有効にするか
    price_in: Optional[float] = None       # USD / 1M input tokens
    price_out: Optional[float] = None      # USD / 1M output tokens


_ADAPTIVE = ["low", "medium", "high", "xhigh", "max"]

BUILTIN: List[ModelSpec] = [
    ModelSpec("claude-opus-5-5", "anthropic", "Claude Opus 5.5", 1_000_000, 128_000,
              "adaptive", _ADAPTIVE, "high", web_search="web_search_20260209",
              fallbacks=True, price_in=4.0, price_out=20.0),
    ModelSpec("claude-sonnet-5-5", "anthropic", "Claude Sonnet 5.5", 1_000_000, 128_000,
              "adaptive", _ADAPTIVE, "high", web_search="web_search_20260209",
              fallbacks=True, price_in=2.0, price_out=10.0),
    ModelSpec("claude-fable-5-1", "anthropic", "Claude Fable 5.1", 1_000_000, 128_000,
              "adaptive", _ADAPTIVE, "high", web_search="web_search_20250305",
              fallbacks=True, price_in=10.0, price_out=50.0),
    ModelSpec("claude-opus-4-8", "anthropic", "Claude Opus 4.8", 1_000_000, 128_000,
              "adaptive", _ADAPTIVE, "high", web_search="web_search_20260209",
              price_in=5.0, price_out=25.0),
    ModelSpec("claude-opus-4-5-20251101", "anthropic", "Claude Opus 4.5 (legacy)", 200_000, 64_000,
              "budget", ["low", "medium", "high"], "high", web_search="web_search_20250305",
              price_in=5.0, price_out=25.0),
    ModelSpec("claude-haiku-4-5", "anthropic", "Claude Haiku 4.5", 200_000, 64_000,
              "budget", ["low", "medium", "high"], "medium", web_search="web_search_20250305",
              price_in=1.0, price_out=5.0),
    # コンテキスト長・料金は利用者の契約に依存するため未設定。models.yaml で上書きする
    ModelSpec("gpt-5.6-sol", "openai", "GPT-5.6 SOL", None, None,
              "effort", EFFORTS, "max", background=True),
]


def _user_models_path() -> Path:
    return Path(os.getenv("DZ_MODELS") or Path.home() / ".divergence_z" / "models.yaml")


def _load_user_models() -> List[ModelSpec]:
    path = _user_models_path()
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    specs = []
    for entry in data.get("models") or []:
        if isinstance(entry, dict) and entry.get("id") and entry.get("provider"):
            known = {f for f in ModelSpec.__dataclass_fields__}
            specs.append(ModelSpec(**{k: v for k, v in entry.items() if k in known}))
    return specs


def registry() -> Dict[str, ModelSpec]:
    """組み込み + ユーザー定義（同じ id はユーザー定義で上書き）"""
    models = {m.id: m for m in BUILTIN}
    for m in _load_user_models():
        models[m.id] = m
    return models


def list_models(provider: Optional[str] = None) -> List[ModelSpec]:
    return [m for m in registry().values() if provider is None or m.provider == provider]


def _guess(model_id: str) -> ModelSpec:
    """登録表に無いモデルの推測（BYOK で任意のモデル名を入れられるようにするため）"""
    m = model_id.lower()
    if m.startswith("claude"):
        return ModelSpec(model_id, "anthropic", model_id, reasoning="adaptive",
                         efforts=_ADAPTIVE, default_effort="high")
    reasoning = any(k in m for k in ("gpt-5", "gpt5", "gpt-6", "gpt6", "o1", "o3", "o4", "sol"))
    return ModelSpec(model_id, "openai", model_id,
                     reasoning="effort" if reasoning else "none",
                     efforts=EFFORTS if reasoning else [],
                     default_effort="high" if reasoning else None,
                     background=("pro" in m) or ("sol" in m))


def get_model(model_id: str) -> ModelSpec:
    return registry().get(model_id) or _guess(model_id)


def with_overrides(spec: ModelSpec, **kwargs) -> ModelSpec:
    return replace(spec, **{k: v for k, v in kwargs.items() if v is not None})
