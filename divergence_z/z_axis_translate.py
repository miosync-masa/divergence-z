#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Z-Axis Translation System v3.1 (Step1/2/3) — OpenAI Responses API版
Operation: Babel Inverse — 「神の呪いを逆算せよ」

v3.1 Changes:
- Episode Memory integration (persona = 人格, episode = 記憶)
- episode_file support in request YAML
- Relevant episode extraction based on scene/context matching
- STEP1: Episode context for deeper WHY analysis (character motivation)
- STEP3: z_relevance + canonical_quotes for HOW translation guidance
- Smart episode scoring: translation_critical > emotional_impact > keyword match
- episodes/ directory auto-discovery

v3.0 Changes:
- z decomposition: z + z_mode + z_leak + z_confidence
- Layer A (observation) / Layer B (inference) two-layer structure
- arc information support
- age_expression_rules integration
- z_mode-based breakdown patterns

実行例:
  python z_axis_translate.py --config requests/subaru_test.yaml
  python z_axis_translate.py --config requests/test.yaml --intensity high
  python z_axis_translate.py --demo
  python z_axis_translate.py --demo --dry-run

必要:
  pip install requests pyyaml python-dotenv
"""

from __future__ import annotations

import argparse
import json
import os
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import yaml
from dotenv import load_dotenv
from anthropic import Anthropic


load_dotenv()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.2")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-4-6")
USE_CLAUDE_FOR_STEP3 = os.getenv("USE_CLAUDE_FOR_STEP3", "true").lower() == "true"

# -----------------------------
# JSON schema definitions v3.0
# -----------------------------

STEP1_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "layer_a": {
            "type": "object",
            "additionalProperties": False,
            "description": "Observation layer - what can be directly inferred from the utterance",
            "properties": {
                "z": {"type": "number", "minimum": 0.0, "maximum": 1.0, "description": "Z-axis intensity (0.0-1.0)"},
                "z_mode": {
                    "type": "string",
                    "enum": ["collapse", "rage", "numb", "plea", "shame", "leak", "none"],
                    "description": "Type of emotional breakdown"
                },
                "z_leak": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["stutter", "ellipsis", "repetition", "negation_concealment", "negation_counter", "negation_declaration", "overwrite", "trailing", "self_negation"]
                    },
                    "description": "Surface markers to apply"
                },
                "z_confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0, "description": "Confidence in z assessment"},
                "emotion_label": {"type": "string", "maxLength": 50, "description": "Short emotion label"},
                "listener_type": {
                    "type": "string",
                    "enum": ["other_specific", "other_general", "self", "absent"],
                    "description": "Who is the utterance directed at"
                },
            },
            "required": ["z", "z_mode", "z_leak", "z_confidence", "emotion_label", "listener_type"],
        },
        "layer_b": {
            "type": "object",
            "additionalProperties": False,
            "description": "Inference layer - hypothetical completion (optional use)",
            "properties": {
                "probable_cause": {"type": "string", "maxLength": 200},
                "subtext": {"type": "string", "maxLength": 200},
                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            },
            "required": ["probable_cause", "subtext", "confidence"],
        },
        "activated_conflicts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "axis": {"type": "string"},
                    "side_a": {"type": "string"},
                    "side_b": {"type": "string"},
                    "activation": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                },
                "required": ["axis", "side_a", "side_b", "activation"],
            },
        },
        "bias": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "mode": {"type": "string"},
                "pattern": {"type": "string"},
                "tendencies": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["mode", "pattern", "tendencies"],
        },
        "arc": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "arc_id": {"type": "string", "description": "Identified arc pattern"},
                "arc_phase": {"type": "string", "enum": ["rise", "break", "bottom", "recovery", "stable"], "description": "Current phase in arc"},
                "arc_target": {"type": "string", "enum": ["speaker", "relationship", "scene"], "description": "What is changing"},
            },
            "required": ["arc_id", "arc_phase", "arc_target"],
        },
        "triggers": {"type": "array", "items": {"type": "string"}},
        "risk_flags": {"type": "array", "items": {"type": "string"}},
        "activated_episodes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Episode IDs from the episode menu that are relevant to understanding this utterance. Select 0-5 most relevant episodes.",
        },
    },
    "required": ["layer_a", "layer_b", "activated_conflicts", "bias", "arc", "triggers", "risk_flags", "activated_episodes"],
}

STEP2_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "waves": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "wave_a": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "label": {"type": "string"},
                        "strength": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    },
                    "required": ["label", "strength"],
                },
                "wave_b": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "label": {"type": "string"},
                        "strength": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    },
                    "required": ["label", "strength"],
                },
            },
            "required": ["wave_a", "wave_b"],
        },
        "interference": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "type": {"type": "string", "enum": ["constructive", "destructive", "mixed"]},
                "notes": {"type": "string", "maxLength": 280},
            },
            "required": ["type", "notes"],
        },
        "surface_markers": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "hesitation_level": {"type": "string", "enum": ["low", "medium", "high"]},
                "negation_first": {"type": "boolean"},
                "negation_type": {
                    "type": "string",
                    "enum": ["concealment", "declaration", "rationalization", "counter", "none"],
                },
                "listener_type": {
                    "type": "string",
                    "enum": ["other_specific", "other_general", "self", "absent"],
                },
                "self_directed_rebinding": {"type": "boolean"},
                "self_correction": {"type": "boolean"},
                "leak_then_overwrite": {"type": "boolean"},
                "residual_marker": {"type": "string"},
                "z_mode": {
                    "type": "string",
                    "enum": ["collapse", "rage", "numb", "plea", "shame", "leak", "none"],
                },
                "z_leak": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "z_axis_intensity": {"type": "string", "enum": ["low", "medium", "high"]},
            },
            "required": [
                "hesitation_level",
                "negation_first",
                "negation_type",
                "listener_type",
                "self_directed_rebinding",
                "self_correction",
                "leak_then_overwrite",
                "residual_marker",
                "z_mode",
                "z_leak",
                "z_axis_intensity",
            ],
        },
        "analysis_summary": {"type": "string", "maxLength": 280},
    },
    "required": ["waves", "interference", "surface_markers", "analysis_summary"],
}

STEP3_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "translation": {"type": "string"},
        "z_signature": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "z": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "z_mode": {
                    "type": "string",
                    "enum": ["collapse", "rage", "numb", "plea", "shame", "leak", "none"],
                },
                "z_leak_applied": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Which z_leak markers were actually applied"
                },
                "hesitation_level": {"type": "string", "enum": ["low", "medium", "high"]},
                "negation_first": {"type": "boolean"},
                "negation_type": {
                    "type": "string",
                    "enum": ["concealment", "declaration", "rationalization", "counter", "none"],
                },
                "listener_type": {
                    "type": "string",
                    "enum": ["other_specific", "other_general", "self", "absent"],
                },
                "self_directed_rebinding": {"type": "boolean"},
                "self_correction": {"type": "boolean"},
                "leak_then_overwrite": {"type": "boolean"},
                "residual_marker": {"type": "string"},
            },
            "required": [
                "z",
                "z_mode",
                "z_leak_applied",
                "hesitation_level",
                "negation_first",
                "negation_type",
                "listener_type",
                "self_directed_rebinding",
                "self_correction",
                "leak_then_overwrite",
                "residual_marker",
            ],
        },
        "arc": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "arc_id": {"type": "string"},
                "arc_phase": {"type": "string"},
                "arc_position": {"type": "integer", "description": "Position in dialogue sequence"},
            },
            "required": ["arc_id", "arc_phase", "arc_position"],
        },
        "notes": {"type": "string", "maxLength": 280},
        "alternatives": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["translation", "z_signature", "arc", "notes", "alternatives"],
}


# -----------------------------
# YAML v3.0 Helper Functions
# -----------------------------

def extract_v3_features(persona_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    YAML v3.0からlanguage, emotion_states, example_lines, triggers,
    age, age_expression_rules, arc_defaultsを抽出。
    v2.0との後方互換性も維持。
    """
    # v3.0 新規フィールド
    age_data = persona_dict.get("age", {})
    
    return {
        "language": persona_dict.get("language", {}),
        "emotion_states": persona_dict.get("emotion_states", []),
        "example_lines": persona_dict.get("example_lines", []),
        "triggers": persona_dict.get("triggers", []),
        # v3.0 additions
        "age": age_data,
        "mental_maturity": age_data.get("mental_maturity", "teen_mature"),
        "age_context": age_data.get("age_context", ""),
        "age_expression_rules": persona_dict.get("age_expression_rules", {}),
        "arc_defaults": persona_dict.get("arc_defaults", {}),
    }


def get_emotion_state_by_z_mode(
    emotion_states: List[Dict[str, Any]], 
    z_mode: str,
    z_intensity: str = "high",
) -> Dict[str, Any]:
    """
    z_mode と z_intensity に対応する emotion_state を返す。
    該当がなければデフォルト。
    """
    # まず z_mode でマッチ
    for state in emotion_states:
        if state.get("z_mode") == z_mode:
            # z_intensity も一致すればベスト
            if state.get("z_intensity") == z_intensity:
                return state
    
    # z_mode だけでマッチ
    for state in emotion_states:
        if state.get("z_mode") == z_mode:
            return state
    
    # z_intensity だけでマッチ（フォールバック）
    for state in emotion_states:
        if state.get("z_intensity") == z_intensity:
            return state
    
    # デフォルト
    return {
        "surface_markers_hint": {
            "hesitation": 2,
            "stutter_count": 1,
            "negation_type": "none",
            "overwrite": "optional",
            "residual": "optional",
        },
        "z_leak": ["ellipsis"],
    }


def get_age_expression_rules(
    age_expression_rules: Dict[str, Any],
    z_intensity: str,
) -> Dict[str, Any]:
    """
    age_expression_rules から高z/低z時のパターンを取得。
    """
    if z_intensity == "high":
        return age_expression_rules.get("high_z_patterns", {})
    else:
        return age_expression_rules.get("low_z_patterns", {})


def format_example_lines(
    example_lines: List[Dict[str, Any]], 
    z_mode: Optional[str] = None,
    max_examples: int = 3,
) -> str:
    """
    example_linesをfew-shot用テキストにフォーマット。
    z_mode が指定されていれば、そのモードの例を優先。
    """
    if not example_lines:
        return "(No example lines provided)"
    
    # z_mode でフィルタ（あれば）
    if z_mode and z_mode != "none":
        filtered = [ex for ex in example_lines if ex.get("z_mode") == z_mode]
        if filtered:
            example_lines = filtered + [ex for ex in example_lines if ex.get("z_mode") != z_mode]
    
    lines = []
    for ex in example_lines[:max_examples]:
        tags = ex.get("tags", [])
        tags_str = ", ".join(tags) if tags else "general"
        line = ex.get("line", "")
        situation = ex.get("situation", "")
        z_mode_ex = ex.get("z_mode", "none")
        lines.append(f"- [{tags_str}] (z_mode={z_mode_ex}) ({situation}) {line}")
    
    return "\n".join(lines)


def format_trigger_info(triggers: List[Dict[str, Any]]) -> str:
    """
    triggersをテキストにフォーマット（v3.0: z_mode_shift対応）。
    """
    if not triggers:
        return "(No specific triggers defined)"
    
    lines = []
    for t in triggers:
        trigger = t.get("trigger", "")
        reaction = t.get("reaction", "")
        z_delta = t.get("z_delta", "")
        z_mode_shift = t.get("z_mode_shift", "")
        effect = t.get("surface_effect", "")
        lines.append(f"- Trigger: {trigger} → {reaction} (Δz={z_delta}, mode_shift={z_mode_shift}, effect={effect})")
    
    return "\n".join(lines)


def format_arc_defaults(arc_defaults: Dict[str, Any]) -> str:
    """
    arc_defaults をテキストにフォーマット。
    """
    if not arc_defaults:
        return "(No arc defaults defined)"
    
    lines = []
    targets = arc_defaults.get("typical_arc_targets", [])
    if targets:
        lines.append(f"Typical arc targets: {', '.join(targets)}")
    
    patterns = arc_defaults.get("common_arc_patterns", [])
    for p in patterns:
        arc_id = p.get("arc_id", "")
        phases = p.get("phases", [])
        notes = p.get("notes", "")
        lines.append(f"- {arc_id}: {' → '.join(phases)} ({notes})")
    
    return "\n".join(lines)


# -----------------------------
# Episode Memory Functions v1.0
# -----------------------------

def load_episode_data(episode_path: str) -> Dict[str, Any]:
    """
    Episode YAMLファイルを読み込む。
    """
    with open(episode_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def format_episode_menu(episode_data: Dict[str, Any]) -> str:
    """
    STEP1用: エピソードの「メニュー」をコンパクトに生成。
    LLMがこのメニューを見て、どのエピソードが関連するか判断する。
    
    ※ エピソード選択はLLMが行う。Pythonによる機械的キーワードマッチは使わない。
    """
    episodes = episode_data.get("episodes", [])
    if not episodes:
        return ""
    
    lines = ["## EPISODE MEMORY MENU"]
    lines.append("Select which episodes are relevant to understanding THIS utterance.")
    lines.append("Return their episode_id values in the activated_episodes field.\n")
    
    for ep in episodes:
        ep_id = ep.get("episode_id", "")
        title = ep.get("title", "")
        timeline = ep.get("timeline", "")
        impact = ep.get("emotional_impact", "")
        # 1行サマリー（最初の一文のみ、80文字制限）
        summary = ep.get("summary", "").strip().split("\n")[0][:80]
        lines.append(f"- {ep_id}: {title} [{timeline}] ({impact}) — {summary}")
    
    return "\n".join(lines)


def lookup_episodes_by_ids(
    episode_data: Dict[str, Any],
    episode_ids: List[str],
) -> List[Dict[str, Any]]:
    """
    STEP1が選んだepisode_idsに基づいて、エピソードの詳細情報をルックアップ。
    
    ※ これは辞書引き（IDベースのルックアップ）なので機械処理で問題ない。
       エピソードの「選択」はSTEP1のLLMが行っている。
    """
    episodes = episode_data.get("episodes", [])
    id_set = set(episode_ids)
    return [ep for ep in episodes if ep.get("episode_id") in id_set]


def format_episode_for_step1(
    relevant_episodes: List[Dict[str, Any]],
    episode_data: Dict[str, Any],
) -> str:
    """
    STEP1用: エピソード記憶をキャラクター理解のコンテキストとしてフォーマット。
    WHY this character feels this way — 感情の根拠を提供。
    
    ※ この関数はSTEP1がactivated_episodesを選択した後、
       STEP3への情報として使う。STEP1自体にはメニューのみ渡す。
    """
    if not relevant_episodes:
        return ""
    
    lines = ["## CHARACTER MEMORY (Episode Context)"]
    lines.append("The following episodes from the character's past are relevant to understanding")
    lines.append("WHY they feel the way they do in this scene:\n")
    
    for ep in relevant_episodes:
        ep_id = ep.get("episode_id", "")
        title = ep.get("title", "")
        summary = ep.get("summary", "").strip()
        impact = ep.get("emotional_impact", "")
        
        lines.append(f"### {title} [{impact}]")
        lines.append(summary)
        
        # character_state_change があれば追加
        state_change = ep.get("character_state_change", {})
        if state_change:
            perm = state_change.get("permanent", "")
            if perm:
                lines.append(f"  → Permanent effect: {perm}")
        
        lines.append("")
    
    # cross_episode_arcs の translation_implications
    arcs = episode_data.get("cross_episode_arcs", [])
    relevant_arc_ids = {ep.get("episode_id") for ep in relevant_episodes}
    
    for arc in arcs:
        involved = set(arc.get("involved_episodes", []))
        if involved & relevant_arc_ids:
            impl = arc.get("translation_implications", "").strip()
            if impl:
                lines.append(f"### Arc: {arc.get('arc_title', '')}")
                lines.append(impl)
                lines.append("")
    
    return "\n".join(lines)


def format_episode_for_step3(
    relevant_episodes: List[Dict[str, Any]],
    episode_data: Dict[str, Any],
) -> str:
    """
    STEP3用: 翻訳に直接影響するz_relevanceとcanonical_quotesをフォーマット。
    HOW to translate — 翻訳判断の具体的根拠を提供。
    """
    if not relevant_episodes:
        return ""
    
    lines = ["## EPISODE MEMORY (Translation Guidance)"]
    lines.append("Use the following episode-specific translation guidance.\n")
    
    for ep in relevant_episodes:
        title = ep.get("title", "")
        z_rel = ep.get("z_relevance", "").strip()
        
        if z_rel:
            lines.append(f"### {title}")
            lines.append(f"[Translation Relevance] {z_rel}")
        
        # canonical_quotes (verified: true のみ翻訳参照用)
        quotes = ep.get("canonical_quotes", [])
        verified_quotes = [q for q in quotes if q.get("verified") is True]
        if verified_quotes:
            lines.append("[Verified Canonical Quotes]")
            for q in verified_quotes[:3]:
                quote_text = q.get("quote", "")
                context = q.get("context", "")
                lines.append(f'  - "{quote_text}" ({context})')
        
        lines.append("")
    
    # memory_integration の persona_connections
    memory_int = episode_data.get("memory_integration", {})
    connections = memory_int.get("persona_connections", [])
    relevant_ep_ids = {ep.get("episode_id") for ep in relevant_episodes}
    
    relevant_connections = []
    for conn in connections:
        conn_eps = set(conn.get("related_episodes", []))
        if conn_eps & relevant_ep_ids:
            relevant_connections.append(conn)
    
    if relevant_connections:
        lines.append("### Persona↔Episode Connections")
        for conn in relevant_connections:
            element = conn.get("persona_element", "")
            note = conn.get("integration_note", "").strip()
            if note:
                lines.append(f"  [{element}]")
                lines.append(f"  {note}")
        lines.append("")
    
    # translation_critical_episodes のリーズン
    tc_episodes = memory_int.get("translation_critical_episodes", [])
    relevant_tc = [tc for tc in tc_episodes if tc.get("episode") in relevant_ep_ids]
    if relevant_tc:
        lines.append("### Translation-Critical Notes")
        for tc in relevant_tc:
            lines.append(f"  - {tc.get('episode', '')}: {tc.get('reason', '')}")
        lines.append("")
    
    return "\n".join(lines)


# -----------------------------
# Config loader
# -----------------------------

def load_config(config_path: str) -> Dict[str, Any]:
    """
    YAML設定ファイルを読み込む。
    persona_file が指定されていればそのファイルも読み込んでマージする。
    episode_file が指定されていればエピソードデータも読み込む。
    """
    config_path = Path(config_path)
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    if 'persona_file' in config and config['persona_file']:
        persona_path = config_path.parent / config['persona_file']
        if not persona_path.exists():
            persona_path = Path(config['persona_file'])
        
        with open(persona_path, 'r', encoding='utf-8') as f:
            persona_data = yaml.safe_load(f)
        config['persona_yaml'] = yaml.dump(persona_data, allow_unicode=True, default_flow_style=False)
    
    elif 'persona' in config:
        config['persona_yaml'] = yaml.dump(config['persona'], allow_unicode=True, default_flow_style=False)
    
    # Episode file loading (v1.0)
    if 'episode_file' in config and config['episode_file']:
        episode_path = config_path.parent / config['episode_file']
        if not episode_path.exists():
            # Try episodes/ subdirectory
            episode_path = config_path.parent / "episodes" / config['episode_file']
        if not episode_path.exists():
            # Try absolute path
            episode_path = Path(config['episode_file'])
        
        if episode_path.exists():
            config['episode_data'] = load_episode_data(str(episode_path))
            print(f"📖 Episode loaded: {episode_path.name} ({config['episode_data'].get('meta', {}).get('total_episodes', '?')} episodes)")
        else:
            print(f"⚠️ Episode file not found: {config['episode_file']} (continuing without episode context)")
            config['episode_data'] = {}
    else:
        config['episode_data'] = {}
    
    return config


# -----------------------------
# OpenAI Responses API (requests版)
# -----------------------------

class OpenAIResponsesClient:
    def __init__(self, api_key: Optional[str] = None, base_url: str = OPENAI_BASE_URL, timeout: int = 60):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY が未設定です。環境変数に設定してください。")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _extract_output_text(resp_json: Dict[str, Any]) -> str:
        out_parts: List[str] = []
        for item in resp_json.get("output", []) or []:
            for c in item.get("content", []) or []:
                if c.get("type") == "output_text" and "text" in c:
                    out_parts.append(c["text"])
        return "".join(out_parts).strip()

    def create_structured(
        self,
        *,
        model: str,
        name: str,
        schema: Dict[str, Any],
        messages: List[Dict[str, str]],
        max_output_tokens: int = 1000,
        temperature: float = 0.2,
        dry_run: bool = False,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        payload = {
            "model": model,
            "input": messages,
            "max_output_tokens": max_output_tokens,
            "temperature": temperature,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": name,
                    "schema": schema,
                    "strict": True,
                }
            },
        }

        if dry_run:
            return payload, {"_dry_run": True}

        url = f"{self.base_url}/responses"
        for attempt in range(5):
            r = requests.post(url, headers=self._headers(), data=json.dumps(payload), timeout=self.timeout)
            if r.status_code == 200:
                resp_json = r.json()
                txt = self._extract_output_text(resp_json)
                try:
                    parsed = json.loads(txt) if txt else {}
                except json.JSONDecodeError:
                    parsed = {"_parse_error": True, "_raw_text": txt}
                return payload, parsed

            if r.status_code in (429, 500, 502, 503, 504):
                sleep_s = (0.5 * (2 ** attempt)) + random.random() * 0.2
                time.sleep(sleep_s)
                continue

            raise RuntimeError(f"OpenAI API error: {r.status_code} {r.text}")

        raise RuntimeError("OpenAI API retry exceeded")

# -----------------------------
# Claude Client for STEP3 (Literary Translation)
# -----------------------------

class ClaudeTranslationClient:
    """Claude client specifically for STEP3 translation - better literary quality."""
    
    def __init__(self, api_key: Optional[str] = None):
        self.client = Anthropic(api_key=api_key)
    
    def translate_step3(
        self,
        *,
        model: str = CLAUDE_MODEL,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 3000,
        temperature: float = 1.0,
    ) -> Dict[str, Any]:
        """
        Execute STEP3 translation using Claude.
        Returns parsed JSON matching STEP3_SCHEMA.
        """
        json_system = system_prompt + """

## OUTPUT FORMAT
You MUST output valid JSON matching this structure:
{
  "translation": "the translated text",
  "z_signature": {
    "z": 0.0-1.0,
    "z_mode": "collapse|rage|numb|plea|shame|leak|none",
    "z_leak_applied": ["markers", "actually", "used"],
    "hesitation_level": "low|medium|high",
    "negation_first": true/false,
    "negation_type": "concealment|declaration|rationalization|counter|none",
    "listener_type": "other_specific|other_general|self|absent",
    "self_directed_rebinding": true/false,
    "self_correction": true/false,
    "leak_then_overwrite": true/false,
    "residual_marker": "marker text or empty"
  },
  "arc": {
    "arc_id": "arc name",
    "arc_phase": "phase name",
    "arc_position": position_number
  },
  "notes": "brief notes",
  "alternatives": ["alt1", "alt2"]
}

Output ONLY the JSON. No markdown code blocks. No explanation before or after."""

        response = self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=json_system,
            messages=[
                {"role": "user", "content": user_prompt}
            ]
        )
        
        raw_text = response.content[0].text.strip()
        
        # Clean up potential markdown
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:]
        if raw_text.startswith("```"):
            raw_text = raw_text[3:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
        raw_text = raw_text.strip()
        
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError as e:
            return {
                "_parse_error": True,
                "_raw_text": raw_text,
                "_error": str(e),
            }

# -----------------------------
# STEP prompts v3.0
# -----------------------------

def build_step1_messages(
    persona_yaml: str, 
    scene: str, 
    relationship: str, 
    context_block: str,
    target_line: str, 
    target_lang: str, 
    z_axis_intensity: str,
    arc_defaults_text: str = "",
    episode_context: str = "",
) -> List[Dict[str, str]]:
    system = f"""You are STEP1 Hamiltonian Extractor for Z-Axis Translation v3.0.

Task: Analyze the TARGET line and extract:
1. Layer A (observation): What can be DIRECTLY inferred from the utterance
2. Layer B (inference): Hypothetical background (lower confidence)
3. Conflict axes activation
4. Arc position

## LAYER A - OBSERVATION (REQUIRED, HIGH CONFIDENCE)
Extract ONLY what is observable in the text:
- z (0.0-1.0): Emotional intensity
- z_mode: Type of breakdown (collapse/rage/numb/plea/shame/leak/none)
- z_leak: Surface markers present (stutter/ellipsis/repetition/negation_concealment/negation_counter/negation_declaration/overwrite/trailing/self_negation)
- z_confidence: How confident you are (0.0-1.0)
- emotion_label: Short label (e.g., "自己嫌悪", "懇願", "麻痺")
- listener_type: Who is being addressed

## LAYER B - INFERENCE (OPTIONAL, LOWER CONFIDENCE)
Hypotheses that CANNOT be directly proven from text:
- probable_cause: Why this emotional state
- subtext: What is NOT being said
- confidence: How confident (usually lower than z_confidence)

## z_mode DEFINITIONS
| z_mode | Meaning | Speech Pattern |
|--------|---------|----------------|
| collapse | 崩壊、言葉が出ない | 途切れ、繰り返し、文が壊れる |
| rage | 怒り、言葉が荒れる | 流暢だが語彙が荒い、攻撃的 |
| numb | 麻痺、感情遮断 | 平坦、短文、感情が消える |
| plea | 懇願、すがる | 繰り返し、「お願い」系語彙 |
| shame | 恥、自己嫌悪 | 自己否定、言い淀み |
| leak | 漏出（ツンデレ等） | 否定→本音が漏れる |
| none | 通常状態 | 安定した発話 |

## LISTENER TYPE
- 'other_specific': Speaking TO a specific person PRESENT
- 'other_general': Speaking to general audience
- 'self': MONOLOGUE / SELF-TALK (alone, talking to themselves)
- 'absent': Talking ABOUT someone NOT present

## ARC DETECTION
Identify which arc pattern this utterance belongs to and its phase.
{arc_defaults_text}

{episode_context}

Output MUST follow the provided JSON schema. Do NOT include chain-of-thought.
"""
    user = (
        f"[Persona YAML]\n{persona_yaml}\n\n"
        f"[Scene]\n{scene}\n\n"
        f"[Relationship]\n{relationship}\n\n"
        f"[Conversation Block]\n{context_block}\n\n"
        f"[TARGET]\n{target_line}\n\n"
        f"[Target Language]\n{target_lang}\n"
        f"[Requested Z Intensity]\n{z_axis_intensity}\n"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_step2_messages(
    step1_json: Dict[str, Any], 
    target_line: str, 
    target_lang: str, 
    z_axis_intensity: str, 
    relationship: str = "",
) -> List[Dict[str, str]]:
    system = """You are STEP2 Interference Pattern Analyzer for Z-Axis Translation v3.0.

Given STEP1 output (especially Layer A), analyze:
1. Wave interference (true intent vs suppression)
2. Surface markers to apply
3. z_mode and z_leak confirmation

## USE LAYER A FROM STEP1
The Layer A values (z, z_mode, z_leak, listener_type) are your PRIMARY input.
Layer B is supplementary context only.

## NEGATION TYPE CLASSIFICATION
- 'concealment': Hiding true feelings (tsundere denial). True intent is OPPOSITE of surface.
- 'declaration': Asserting truth. True intent MATCHES surface.
- 'rationalization': Logical justification to mask emotion.
- 'counter': Denying the OTHER's claim/negation (devotion-type rebuttal). "No— that's not true!"
- 'none': No negation.

## SELF-DIRECTED REBINDING
When listener_type is 'self' AND negation_type is 'concealment':
- Speaker is trying to convince THEMSELVES of something they know is false
- Often needs a SECOND denial to re-convince
- Set self_directed_rebinding: true

## z_mode and z_leak CONFIRMATION
Confirm or adjust the z_mode and z_leak from STEP1 based on interference analysis.
The z_leak markers will be used by STEP3 for translation.

Output MUST follow the provided JSON schema. Do NOT include chain-of-thought.
"""
    user = (
        f"[STEP1 JSON]\n{json.dumps(step1_json, ensure_ascii=False)}\n\n"
        f"[Relationship]\n{relationship}\n\n"
        f"[TARGET]\n{target_line}\n"
        f"[Target Language]\n{target_lang}\n"
        f"[Requested Z Intensity]\n{z_axis_intensity}\n"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_step3_messages(
    step1_json: Dict[str, Any], 
    step2_json: Dict[str, Any], 
    target_line: str, 
    target_lang: str,
    persona_dict: Optional[Dict[str, Any]] = None,
    arc_position: int = 1,
    episode_translation_context: str = "",
) -> List[Dict[str, str]]:
    """
    STEP3プロンプトを構築（v3.0対応版）。
    
    v3.0:
    - Layer A から z_mode, z_leak を取得
    - age_expression_rules で崩れ方を決定
    - emotion_states から surface_markers_hint を取得
    """
    # v3.0特徴の抽出
    v3_features = extract_v3_features(persona_dict) if persona_dict else {}
    
    # Layer A から z_mode を取得
    layer_a = step1_json.get("layer_a", {})
    z_mode = layer_a.get("z_mode", "none")
    z_intensity = step2_json.get("surface_markers", {}).get("z_axis_intensity", "medium")
    z_leak = step2_json.get("surface_markers", {}).get("z_leak", [])
    
    # emotion_state を z_mode で取得
    emotion_state = get_emotion_state_by_z_mode(
        v3_features.get("emotion_states", []),
        z_mode,
        z_intensity,
    )
    
    # age_expression_rules を取得
    age_rules = get_age_expression_rules(
        v3_features.get("age_expression_rules", {}),
        z_intensity,
    )
    
    # few-shot例をフォーマット（z_mode でフィルタ）
    examples_text = format_example_lines(
        v3_features.get("example_lines", []),
        z_mode=z_mode,
        max_examples=3,
    )
    
    # 言語設定
    language_info = v3_features.get("language", {})
    language_block = ""
    if language_info:
        fp = language_info.get("first_person", "")
        sp = language_info.get("second_person_user", "")
        addr = language_info.get("address_style", "")
        quirks = language_info.get("speech_quirks", [])
        quirks_str = ", ".join(quirks[:3]) if quirks else "none"
        language_block = f"""
[CHARACTER VOICE]
First person: {fp}
Second person (to user): {sp}
Address style: {addr}
Speech quirks: {quirks_str}
"""
    
    # トリガー情報
    trigger_text = format_trigger_info(v3_features.get("triggers", []))
    
    # z_mode 別の崩れ方ガイダンス
    z_mode_guidance = {
        "collapse": "Speech breaks down: stutters, repetition, incomplete sentences, trailing off",
        "rage": "Fluent but harsh: aggressive vocabulary, exclamations, accusations",
        "numb": "Flat and short: minimal words, no emotion, hollow",
        "plea": "Desperate repetition: begging phrases, name repetition, trailing",
        "shame": "Self-negation: self-criticism, hesitation, low voice",
        "leak": "Denial then leak: negation first, then true feeling slips out",
        "none": "Stable speech: normal patterns, no breakdown markers",
    }
    
    # 制約ブロックを構築
    surface_hints = emotion_state.get("surface_markers_hint", {})
    constraint_block = f"""
[Z-MODE: {z_mode.upper()}]
{z_mode_guidance.get(z_mode, "Standard speech patterns")}

[Z-LEAK MARKERS TO APPLY]
{', '.join(z_leak) if z_leak else 'none'}

[SURFACE MARKER HINTS] (from persona emotion_state)
- hesitation: {surface_hints.get('hesitation', 'default')}
- stutter_count: {surface_hints.get('stutter_count', 'default')}
- negation_type: {surface_hints.get('negation_type', 'none')}
- overwrite: {surface_hints.get('overwrite', 'optional')}
- residual: {surface_hints.get('residual', 'optional')}
- tone: {surface_hints.get('tone', 'default')}

[AGE EXPRESSION RULES] ({v3_features.get('mental_maturity', 'teen_mature')})
- vocabulary: {age_rules.get('vocabulary', 'default')}
- structure: {age_rules.get('structure', 'default')}
"""
    
    system = f"""You are STEP3 Z-Axis Preserving Translator v3.0.

Goal: Translate TARGET into the target language while preserving:
  - Semantics (meaning)
  - Style (register)
  - Dynamics (conflict×bias interference pattern)
  - z_mode (TYPE of emotional breakdown)
  - z_leak (SPECIFIC markers of that breakdown)

{constraint_block}

[EXAMPLE LINES] (for tone/vocabulary reference ONLY — do NOT copy)
{examples_text}

[KNOWN TRIGGERS]
{trigger_text}

{episode_translation_context}

## z_leak MARKER APPLICATION
Apply the z_leak markers from STEP2 to realize the breakdown pattern:
- stutter: "I— I..." or "N-no..."
- ellipsis: "..." or "I just..."
- repetition: "Why, why, why" or "nobody— nobody"
- negation_concealment: Hide feelings "N-not that it's for you..."
- negation_counter: Rebut other's claim "No— that's not true!"
- negation_declaration: Assert will "I'm not looking to rule!"
- overwrite: Self-correction "I mean—"
- trailing: Fade out "...I guess" or "...or something"
- self_negation: "I'm worthless" "It's my fault"

## CRITICAL RULES
1. z_mode determines HOW speech breaks down
2. z_leak determines WHICH markers to use
3. age_expression_rules adjusts vocabulary/structure for character's maturity
4. Do NOT over-explain; dynamics must be implicit
5. Match the character's voice (first_person, quirks)

Output MUST follow the provided JSON schema. Do NOT include chain-of-thought.
"""
    
    user = f"""{language_block}
[STEP1 JSON (Layer A is primary)]
{json.dumps(step1_json, ensure_ascii=False)}

[STEP2 JSON]
{json.dumps(step2_json, ensure_ascii=False)}

[TARGET]
{target_line}

[Target Language]
{target_lang}

[Arc Position]
{arc_position}

Provide translation with up to 2 alternatives.
"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


# -----------------------------
# Orchestrator v3.0 (STEP1→2→3)
# -----------------------------

def z_axis_translate(
    *,
    client: OpenAIResponsesClient,
    model: str,
    persona_yaml: str,
    scene: str,
    relationship: str,
    context_block: str,
    target_line: str,
    target_lang: str,
    z_axis_intensity: str,
    dry_run: bool = False,
    arc_position: int = 1,
    episode_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Z軸翻訳を実行する（v3.0 + Episode Memory v1.0）。
    STEP1（Layer A/B抽出）→ STEP2（干渉縞分析）→ STEP3（翻訳生成）
    
    episode_data が提供されている場合:
    - STEP1: エピソードメニュー（コンパクト一覧）を見てLLMがactivated_episodesを選択
    - Python: activated_episodes IDで辞書引き → 詳細情報取得
    - STEP3: z_relevance + canonical_quotes を翻訳ガイダンスとして注入
    
    ※ エピソードの選択判断はLLMが行う。Pythonは辞書引き（IDルックアップ）のみ。
    """
    # persona_yamlをパースしてv3.0機能を抽出
    try:
        persona_dict = yaml.safe_load(persona_yaml)
    except yaml.YAMLError:
        persona_dict = {}
    
    # arc_defaults をフォーマット
    v3_features = extract_v3_features(persona_dict)
    arc_defaults_text = format_arc_defaults(v3_features.get("arc_defaults", {}))
    
    # Episode Memory: メニュー生成（STEP1でLLMが選択する）
    episode_menu = ""
    has_episodes = episode_data and episode_data.get("episodes")
    if has_episodes:
        episode_menu = format_episode_menu(episode_data)
        ep_count = len(episode_data.get("episodes", []))
        print(f"📖 Episode menu prepared: {ep_count} episodes available for STEP1 selection")
    
    # STEP1: Layer A/B 抽出 + エピソード選択（LLM判断）
    s1_msgs = build_step1_messages(
        persona_yaml, scene, relationship, context_block, 
        target_line, target_lang, z_axis_intensity,
        arc_defaults_text,
        episode_context=episode_menu,
    )
    s1_payload, step1 = client.create_structured(
        model=model,
        name="step1_hamiltonian_v3",
        schema=STEP1_SCHEMA,
        messages=s1_msgs,
        max_output_tokens=1000,
        temperature=0.3,
        dry_run=dry_run,
    )
    if dry_run:
        return {"step1_request": s1_payload}

    # Episode Memory: STEP1のLLM判断に基づくIDルックアップ（辞書引き）
    episode_context_step3 = ""
    if has_episodes:
        activated_ids = step1.get("activated_episodes", [])
        if activated_ids:
            relevant_eps = lookup_episodes_by_ids(episode_data, activated_ids)
            episode_context_step3 = format_episode_for_step3(relevant_eps, episode_data)
            print(f"🎭 STEP1 selected {len(activated_ids)} episodes (LLM judgment):")
            for eid in activated_ids:
                print(f"   → {eid}")
        else:
            print("📖 STEP1 selected no episodes for this scene")

    # STEP2: 干渉縞分析
    s2_msgs = build_step2_messages(step1, target_line, target_lang, z_axis_intensity, relationship)
    _, step2 = client.create_structured(
        model=model,
        name="step2_interference_v3",
        schema=STEP2_SCHEMA,
        messages=s2_msgs,
        max_output_tokens=800,
        temperature=0.3,
        dry_run=False,
    )

    # STEP3: Z軸保存翻訳生成
    s3_msgs = build_step3_messages(
        step1, step2, target_line, target_lang, 
        persona_dict=persona_dict,
        arc_position=arc_position,
        episode_translation_context=episode_context_step3,
    )
    
    if USE_CLAUDE_FOR_STEP3:
        # Use Claude for STEP3 (better literary quality)
        claude_client = ClaudeTranslationClient()
        system_prompt = s3_msgs[0]["content"] if s3_msgs[0]["role"] == "system" else ""
        user_prompt = s3_msgs[1]["content"] if len(s3_msgs) > 1 else s3_msgs[0]["content"]
        
        step3 = claude_client.translate_step3(
            model=CLAUDE_MODEL,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=1500,
            temperature=1.0,
        )
    else:
        _, step3 = client.create_structured(
            model=model,
            name="step3_translation_v3",
            schema=STEP3_SCHEMA,
            messages=s3_msgs,
            max_output_tokens=1000,
            temperature=0.7,
            dry_run=False,
        )

    return {"step1": step1, "step2": step2, "step3": step3}

# -----------------------------
# Demo data v3.0 (Subaru example)
# -----------------------------

DEMO_PERSONA_YAML = """meta:
  version: "3.0"
  character_id: "natsuki_subaru"

persona:
  name: "ナツキ・スバル"
  source: "Re:ゼロから始める異世界生活"
  type: "死に戻り能力者 × 元引きこもり"
  summary: "死に戻りの秘密を抱え、仲間のために必死に戦う少年"

age:
  chronological: 17
  mental_maturity: "teen_young"
  age_context: "元引きこもりで社会経験が浅く、精神的成熟が遅れている"

language:
  first_person: "俺"
  second_person_user: "お前"
  address_style: "基本タメ口"
  speech_quirks:
    - "自虐ギャグで場を和ませようとする"
    - "崩壊時は自分を責める言葉が繰り返される"

conflict_axes:
  - axis: "明るい自分 vs 絶望している自分"
    side_a: "仲間を守り、希望を持って前進したい"
    side_b: "何度も死んで、もう無理だと思っている"
    weight: 0.9

bias:
  default_mode: "明るく饒舌"
  pattern: "通常時は自虐ギャグ → ストレス蓄積 → 限界点で感情決壊"
  tendencies:
    - "失敗時は自分を責める言葉を繰り返す"
    - "崩壊時は「俺が悪い」「無理だ」の反復"

age_expression_rules:
  category: "teen_young"
  high_z_patterns:
    vocabulary: "平易化、繰り返し"
    structure: "短文化、途切れが多い、自己否定の反復"
  low_z_patterns:
    vocabulary: "現代語、オタク語彙"
    structure: "饒舌、テンポが速い"

emotion_states:
  - state: "shame_self_hatred"
    z_intensity: "high"
    z_mode: "shame"
    surface_markers_hint:
      hesitation: 3
      stutter_count: 3
      negation_type: "none"
      overwrite: "required"
      residual: "required"
      tone: "低く、自分を責める、涙声"
    z_leak:
      - "self_negation"
      - "repetition"
      - "ellipsis"
      - "trailing"

example_lines:
  - situation: "自己嫌悪に陥る"
    line: "俺が— 俺が悪いんだ。俺が無力で、才能がなくて……"
    tags: ["shame", "collapse"]
    z_intensity: "high"
    z_mode: "shame"

triggers:
  - trigger: "失敗の累積"
    reaction: "z_spike"
    z_delta: "+0.7"
    z_mode_shift: "shame"
    surface_effect: "自己嫌悪の反復"

arc_defaults:
  typical_arc_targets:
    - "speaker"
  common_arc_patterns:
    - arc_id: "self_hatred_spiral"
      phases: ["failure", "shame", "collapse", "bottom", "small_hope"]
"""

DEMO_CONTEXT_BLOCK = """[Scene] 白鯨戦後、一人になったスバル
[レム] スバルくんは、自分のことが嫌いですか？
"""

DEMO_SCENE = "魔女の残り香の中、精神的限界"
DEMO_RELATIONSHIP = "自分自身への独白"
DEMO_TARGET_LINE = "誰にも期待されちゃいない。誰も俺を信じちゃいない。俺は、俺が大嫌いだ。"
DEMO_TARGET_LANG = "en"
DEMO_Z_INTENSITY = "high"


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Z-Axis Translation System v3.0 — Operation: Babel Inverse",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python z_axis_translate.py --config requests/subaru_test.yaml
  python z_axis_translate.py --config requests/test.yaml --intensity high
  python z_axis_translate.py --demo
  python z_axis_translate.py --demo --dry-run
        """
    )
    ap.add_argument("--model", default=DEFAULT_MODEL, help="使用するモデル")
    ap.add_argument("--config", type=str, help="YAML設定ファイルのパス")
    ap.add_argument("--intensity", type=str, choices=["low", "medium", "high"],
                    help="Z軸強度（configの値を上書き）")
    ap.add_argument("--demo", action="store_true", help="内蔵のスバルデモを実行")
    ap.add_argument("--dry-run", action="store_true", help="APIを叩かず、STEP1のリクエストを出力")
    ap.add_argument("--output", "-o", type=str, help="結果をJSONファイルに出力")
    args = ap.parse_args()

    if not args.demo and not args.config:
        print("Error: --demo または --config のいずれかを指定してください。")
        print("Use --help for usage information.")
        return

    client = OpenAIResponsesClient()

    if args.config:
        config = load_config(args.config)
        
        required_fields = ['scene', 'relationship', 'context_block', 'target_line', 'target_lang']
        for field in required_fields:
            if field not in config:
                print(f"Error: 設定ファイルに '{field}' が必要です。")
                return
        
        if 'persona_yaml' not in config:
            print("Error: persona_file または persona の定義が必要です。")
            return
        
        z_intensity = args.intensity or config.get('z_axis_intensity', 'medium')
        
        out = z_axis_translate(
            client=client,
            model=args.model,
            persona_yaml=config['persona_yaml'],
            scene=config['scene'],
            relationship=config['relationship'],
            context_block=config['context_block'],
            target_line=config['target_line'],
            target_lang=config['target_lang'],
            z_axis_intensity=z_intensity,
            dry_run=args.dry_run,
            episode_data=config.get('episode_data', {}),
        )
    else:
        z_intensity = args.intensity or DEMO_Z_INTENSITY
        
        out = z_axis_translate(
            client=client,
            model=args.model,
            persona_yaml=DEMO_PERSONA_YAML,
            scene=DEMO_SCENE,
            relationship=DEMO_RELATIONSHIP,
            context_block=DEMO_CONTEXT_BLOCK,
            target_line=DEMO_TARGET_LINE,
            target_lang=DEMO_TARGET_LANG,
            z_axis_intensity=z_intensity,
            dry_run=args.dry_run,
        )

    result_json = json.dumps(out, ensure_ascii=False, indent=2)
    
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(result_json)
        print(f"Result saved to: {args.output}")
    else:
        print(result_json)


if __name__ == "__main__":
    main()
