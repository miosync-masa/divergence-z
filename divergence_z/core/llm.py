"""LLM 呼び出しの共通層（BYOK）。

    llm = LLM(Keys(openai="sk-...", anthropic="sk-ant-..."))   # UI からキーを渡す
    llm = LLM(Keys.from_env())                                  # CLI は環境変数 / .env
    result = llm.complete(system, user, model="gpt-5.6-sol", effort="high")

モデルごとの差（推論の指定方法、background 必須、web search の tool type 等）は
core.models の登録表で吸収し、呼び出し側はモデル名と effort だけを渡す。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .models import ModelSpec, get_model
from .progress import Progress, resolve

# budget 方式（旧 Anthropic モデル）で effort を thinking トークン数に読み替える
_BUDGET_BY_EFFORT = {"low": 2048, "medium": 8000, "high": 16000, "xhigh": 24000, "max": 32000}

_OPENAI_TERMINAL = {"completed", "failed", "cancelled", "incomplete", "expired"}


class LLMError(RuntimeError):
    pass


class LLMRefusal(LLMError):
    pass


@dataclass
class Keys:
    openai: Optional[str] = None
    anthropic: Optional[str] = None
    openai_base_url: Optional[str] = None

    @classmethod
    def from_env(cls) -> "Keys":
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
        return cls(
            openai=os.getenv("OPENAI_API_KEY"),
            anthropic=os.getenv("ANTHROPIC_API_KEY"),
            openai_base_url=os.getenv("OPENAI_BASE_URL"),
        )


@dataclass
class LLMResult:
    text: str
    model: str
    provider: str
    effort: Optional[str]
    elapsed_seconds: float
    background: bool = False
    searches: int = 0
    usage: Dict[str, Any] = field(default_factory=dict)
    served_by: Optional[str] = None     # fallback が走った場合は実際に応答したモデル
    response_id: Optional[str] = None
    thinking: str = ""                  # show_thinking=True のときの思考（要約）


class LLM:
    def __init__(self, keys: Optional[Keys] = None, timeout: float = 1800.0,
                 progress: Optional[Progress] = None):
        self.keys = keys or Keys.from_env()
        self.timeout = timeout
        self.progress = resolve(progress)
        self._openai = None
        self._anthropic = None

    # --- clients (lazy: 片方のキーしか無くても動くように) -------------------------

    def _openai_client(self):
        if self._openai is None:
            if not self.keys.openai:
                raise LLMError("OpenAI API key is required for this model")
            from openai import OpenAI
            self._openai = OpenAI(api_key=self.keys.openai, base_url=self.keys.openai_base_url,
                                  timeout=self.timeout)
        return self._openai

    def _anthropic_client(self):
        if self._anthropic is None:
            if not self.keys.anthropic:
                raise LLMError("Anthropic API key is required for this model")
            from anthropic import Anthropic
            self._anthropic = Anthropic(api_key=self.keys.anthropic, timeout=self.timeout)
        return self._anthropic

    # --- public ---------------------------------------------------------------

    def complete(self, system: str, user: str, model: str, effort: Optional[str] = None,
                 max_output_tokens: Optional[int] = None, web_search: bool = False,
                 max_searches: int = 8, background: Optional[bool] = None,
                 show_thinking: bool = False, spec: Optional[ModelSpec] = None) -> LLMResult:
        spec = spec or get_model(model)
        if effort and spec.efforts and effort not in spec.efforts:
            raise LLMError(f"{spec.id} does not support effort '{effort}' "
                           f"(supported: {', '.join(spec.efforts)})")
        effort = effort or spec.default_effort
        if spec.provider == "anthropic":
            return self._complete_anthropic(spec, system, user, effort, max_output_tokens,
                                            web_search, max_searches, show_thinking)
        if spec.provider == "openai":
            if web_search:
                raise LLMError("web_search is supported on Anthropic models only in this build")
            return self._complete_openai(spec, system, user, effort, max_output_tokens, background)
        raise LLMError(f"Unknown provider: {spec.provider}")

    # --- OpenAI Responses API ---------------------------------------------------

    def _complete_openai(self, spec: ModelSpec, system: str, user: str, effort: Optional[str],
                         max_output_tokens: Optional[int], background: Optional[bool]) -> LLMResult:
        client = self._openai_client()
        use_background = spec.background if background is None else background
        params: Dict[str, Any] = {
            "model": spec.id,
            "input": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_output_tokens": max_output_tokens or spec.max_output or 65536,
        }
        if spec.reasoning == "effort" and effort:
            params["reasoning"] = {"effort": effort}
        if use_background:
            # background は後から retrieve するため store 必須
            params["background"] = True
            params["store"] = True

        self.progress(f"🚀 {spec.id} (OpenAI Responses){f' / effort={effort}' if effort else ''}"
                      f"{' / background' if use_background else ''}")
        start = time.time()
        response = client.responses.create(**params)
        if use_background:
            response = self._poll_openai(client, response, start)
        elapsed = time.time() - start

        status = getattr(response, "status", None)
        if status == "failed":
            raise LLMError(f"Response failed: {getattr(response, 'error', None)}")
        if status == "incomplete":
            raise LLMError(f"Response incomplete: {getattr(response, 'incomplete_details', None)}. "
                           f"Raise max_output_tokens or lower effort.")

        text = getattr(response, "output_text", None) or "".join(
            getattr(c, "text", "") or ""
            for item in (getattr(response, "output", None) or [])
            for c in (getattr(item, "content", None) or [])
            if getattr(c, "type", None) == "output_text"
        )
        usage = getattr(response, "usage", None)
        self.progress(f"⏱️  {elapsed:.1f}s")
        return LLMResult(
            text=text.strip(), model=spec.id, provider="openai",
            effort=effort if spec.reasoning == "effort" else None,
            elapsed_seconds=elapsed, background=use_background,
            usage=usage.model_dump() if hasattr(usage, "model_dump") else {},
            response_id=getattr(response, "id", None),
        )

    def _poll_openai(self, client, response, start: float, interval: int = 10):
        status = getattr(response, "status", None)
        while status not in _OPENAI_TERMINAL:
            if time.time() - start > self.timeout:
                try:
                    client.responses.cancel(response.id)
                except Exception:
                    pass
                raise LLMError(f"Background job timed out after {self.timeout:.0f}s")
            self.progress(f"   ⏳ {int(time.time() - start)}s, status={status}")
            time.sleep(interval)
            response = client.responses.retrieve(response.id)
            status = getattr(response, "status", None)
        return response

    # --- Anthropic Messages API -------------------------------------------------

    def _complete_anthropic(self, spec: ModelSpec, system: str, user: str, effort: Optional[str],
                            max_output_tokens: Optional[int], web_search: bool,
                            max_searches: int, show_thinking: bool = False) -> LLMResult:
        client = self._anthropic_client()
        max_tokens = max_output_tokens or min(spec.max_output or 64000, 64000)
        params: Dict[str, Any] = {"model": spec.id, "max_tokens": max_tokens, "system": system}

        if spec.reasoning == "adaptive":
            # 新しいモデルは思考本文を返さない（既定 omitted）。表示したい場合は要約を要求する
            params["thinking"] = ({"type": "adaptive", "display": "summarized"} if show_thinking
                                  else {"type": "adaptive"})
            if effort:
                params["output_config"] = {"effort": effort}
        elif spec.reasoning == "budget" and effort and effort != "none":
            budget = _BUDGET_BY_EFFORT.get(effort, 16000)
            params["thinking"] = {"type": "enabled", "budget_tokens": budget}
            params["max_tokens"] = max(max_tokens, budget + 8000)

        if web_search:
            if not spec.web_search:
                raise LLMError(f"{spec.id} has no web_search tool configured")
            params["tools"] = [{"type": spec.web_search, "name": "web_search",
                                "max_uses": max_searches}]

        if spec.fallbacks:
            # 安全分類器で断られたとき、同じリクエストを別モデルで自動再実行（server-side）
            params["betas"] = ["server-side-fallback-2026-07-01"]
            params["fallbacks"] = "default"
            messages_api = client.beta.messages
        else:
            messages_api = client.messages

        self.progress(f"🚀 {spec.id} (Anthropic){f' / effort={effort}' if effort else ''}"
                      f"{' / web_search' if web_search else ''}")
        start = time.time()
        messages: List[Dict[str, Any]] = [{"role": "user", "content": user}]
        content: List[Any] = []
        response = None
        # web search 等の server tool は pause_turn で一時停止することがある → 続きを要求
        for _ in range(6):
            with messages_api.stream(messages=messages, **params) as stream:
                response = stream.get_final_message()
            content.extend(response.content)
            if response.stop_reason != "pause_turn":
                break
            messages = messages + [{"role": "assistant", "content": response.content}]
        elapsed = time.time() - start

        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            raise LLMRefusal(f"Request declined ({getattr(details, 'category', None)}): "
                             f"{getattr(details, 'explanation', '')}")
        if response.stop_reason == "max_tokens":
            self.progress("   ⚠️  Output hit max_tokens — result may be truncated")

        text = "".join(b.text for b in content if getattr(b, "type", None) == "text")
        searches = sum(1 for b in content if getattr(b, "type", None) == "server_tool_use"
                       and getattr(b, "name", None) == "web_search")
        thinking = "\n".join(getattr(b, "thinking", "") or "" for b in content
                             if getattr(b, "type", None) == "thinking")
        usage = getattr(response, "usage", None)
        self.progress(f"⏱️  {elapsed:.1f}s{f' / {searches} search(es)' if web_search else ''}")
        return LLMResult(
            text=text.strip(), model=spec.id, provider="anthropic",
            effort=effort if spec.reasoning != "none" else None,
            elapsed_seconds=elapsed, searches=searches,
            usage=usage.model_dump() if hasattr(usage, "model_dump") else {},
            served_by=getattr(response, "model", None),
            response_id=getattr(response, "id", None),
            thinking=thinking.strip(),
        )
