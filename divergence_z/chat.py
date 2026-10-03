#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Character Chat — ペルソナとエピソードを入れたキャラクターと会話する

システム指示 = 共通テンプレート（利用者が編集できる）に、そのキャラクターの
ペルソナ YAML とエピソード YAML を省略せず丸ごと差し込んだもの。

  テンプレートの置き場所: $DZ_HOME/chat_template.md（既定 ~/.divergence_z/chat_template.md）
  差し込み口:
    {{CHARACTER}}        キャラクター名（人物表のラベル）
    {{PERSONA_EPISODE}}  ペルソナ YAML ＋ エピソード YAML（＋ユーザー情報）
    {{USER}}             ユーザー情報（任意。無ければ {{PERSONA_EPISODE}} の後ろに付ける）

会話ログはプロジェクトフォルダの chats/<id>.json に保存する（手元の PC だけ）。
システム指示が長いので、Anthropic ではプロンプトキャッシュを使う。
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from divergence_z.core import LLM, LLMResult, Progress, resolve_progress

DEFAULT_TEMPLATE = """客観ではなく{{CHARACTER}}の主観として応答してください。主語は{{CHARACTER}}自身です。
知識などは以下のペルソナとエピソードにあわせて、知り得ないことは推論で答えないこと。

{{PERSONA_EPISODE}}

上記のペルソナとエピソードにしたがい、{{CHARACTER}}として、会話の流れと相手の気持ちを
踏まえた自然な応答を返してください。
"""

MAX_HISTORY_MESSAGES = 60     # 履歴として渡す直近のメッセージ数（user + assistant）

_THINKING = re.compile(r"<thinking>.*?(</thinking>|$)", re.S)


def chat_home() -> Path:
    return Path(os.getenv("DZ_HOME") or Path.home() / ".divergence_z")


def template_path() -> Path:
    return chat_home() / "chat_template.md"


def load_template() -> str:
    path = template_path()
    if path.exists():
        return path.read_text(encoding="utf-8")
    return DEFAULT_TEMPLATE


def save_template(text: str) -> None:
    path = template_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def strip_thinking(text: str) -> str:
    """表示用: <thinking>…</thinking> を除く（ログには原文を残す）"""
    stripped = _THINKING.sub("", text).strip()
    # <thinking> が閉じられずに返ってきて全部消えた場合は、原文を見せる
    return stripped or text.strip()


def build_system(template: str, character: str, persona_text: str = "", episode_text: str = "",
                 user_profile: str = "") -> str:
    """テンプレートにキャラクター名・ペルソナ・エピソード・ユーザー情報を差し込む（YAML は省略しない）"""
    blocks: List[str] = []
    if persona_text.strip():
        blocks.append(f"## ペルソナ（{character}）\n```yaml\n{persona_text.strip()}\n```")
    if episode_text.strip():
        blocks.append(f"## エピソード記憶（{character}）\n```yaml\n{episode_text.strip()}\n```")
    user_block = f"## ユーザー情報\n{user_profile.strip()}" if user_profile.strip() else ""
    if "{{USER}}" not in template and user_block:
        blocks.append(user_block)

    text = template.replace("{{PERSONA_EPISODE}}", "\n\n".join(blocks))
    text = text.replace("{{USER}}", user_block)
    return text.replace("{{CHARACTER}}", character)


class ChatStore:
    """プロジェクトフォルダの chats/ に会話を1件1ファイルで保存する"""

    def __init__(self, root: Path):
        self.dir = Path(root) / "chats"
        self._lock = threading.Lock()

    def _path(self, chat_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{12}", chat_id):
            raise KeyError(chat_id)
        return self.dir / f"{chat_id}.json"

    def list(self) -> List[Dict[str, Any]]:
        if not self.dir.is_dir():
            return []
        out = []
        for f in self.dir.glob("*.json"):
            try:
                c = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            last = next((m for m in reversed(c.get("messages") or []) if m.get("role") == "assistant"), None)
            out.append({k: c.get(k) for k in ("id", "title", "character", "model", "effort",
                                              "created", "updated")}
                       | {"messages": len(c.get("messages") or []),
                          "preview": (last or {}).get("display", "")[:80]})
        return sorted(out, key=lambda c: c.get("updated") or 0, reverse=True)

    def get(self, chat_id: str) -> Dict[str, Any]:
        path = self._path(chat_id)
        if not path.exists():
            raise KeyError(chat_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def save(self, chat: Dict[str, Any]) -> None:
        with self._lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            chat["updated"] = time.time()
            self._path(chat["id"]).write_text(json.dumps(chat, ensure_ascii=False, indent=1),
                                              encoding="utf-8")

    def create(self, character: str, model: str, effort: Optional[str] = None,
               user_profile: str = "", title: str = "") -> Dict[str, Any]:
        now = time.time()
        chat = {"id": uuid.uuid4().hex[:12], "title": title or character, "character": character,
                "model": model, "effort": effort, "user_profile": user_profile,
                "created": now, "updated": now, "messages": []}
        self.save(chat)
        return chat

    def delete(self, chat_id: str) -> None:
        self._path(chat_id).unlink(missing_ok=True)


def reply(chat: Dict[str, Any], text: str, *, llm: LLM, system: str,
          max_output_tokens: int = 16000, progress: Optional[Progress] = None) -> Dict[str, Any]:
    """ユーザーの発言に対するキャラクターの返事を作り、chat["messages"] に両方を追記する"""
    report = resolve_progress(progress)
    history = [{"role": m["role"], "content": m.get("display") or m["content"]}
               for m in chat["messages"][-MAX_HISTORY_MESSAGES:]]
    report(f"💬 {chat['character']} ← {text[:40]}")
    result: LLMResult = llm.complete(system, text, model=chat["model"], effort=chat.get("effort"),
                                     max_output_tokens=max_output_tokens, history=history, cache=True)
    now = time.time()
    chat["messages"].append({"role": "user", "content": text, "time": now})
    chat["messages"].append({"role": "assistant", "content": result.text,
                             "display": strip_thinking(result.text), "time": time.time(),
                             "model": result.served_by or result.model, "usage": result.usage})
    return chat["messages"][-1]
