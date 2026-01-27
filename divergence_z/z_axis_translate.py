#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Z-Axis Translation System (Step1/2/3) — OpenAI Responses API版
Operation: Babel Inverse — 「神の呪いを逆算せよ」

- STEP1: ハミルトニアン抽出（逆問題）: persona×context→H
- STEP2: 干渉縞分析: conflict×bias→interference pattern
- STEP3: Z軸保存翻訳生成: target languageで同型の干渉縞を再演

実行例:
  # YAML設定ファイルで実行
  python z_axis_translate.py --config requests/kurisu_test.yaml

  # 強度を上書き
  python z_axis_translate.py --config requests/test.yaml --intensity high

  # 内蔵デモ（紅莉栖）
  python z_axis_translate.py --demo

  # リクエストだけ確認（APIを叩かない）
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

load_dotenv()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1")


# -----------------------------
# JSON schema definitions
# -----------------------------

STEP1_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
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
        "listener_type": {
            "type": "string",
            "enum": ["other_specific", "other_general", "self", "absent"],
            "description": "Who is the utterance directed at, inferred from relationship/context"
        },
        "triggers": {"type": "array", "items": {"type": "string"}},
        "risk_flags": {"type": "array", "items": {"type": "string"}},
        "analysis_summary": {"type": "string", "maxLength": 280},
    },
    "required": ["activated_conflicts", "bias", "listener_type", "triggers", "risk_flags", "analysis_summary"],
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
                    "enum": ["concealment", "declaration", "rationalization", "none"],
                    "description": "Type of negation: concealment (hiding true feelings), declaration (asserting truth), rationalization (logical justification), none (no negation)"
                },
                "listener_type": {
                    "type": "string",
                    "enum": ["other_specific", "other_general", "self", "absent"],
                    "description": "Who is the utterance directed at: other_specific (specific person present), other_general (general audience), self (monologue/self-talk), absent (talking about absent person)"
                },
                "self_directed_rebinding": {
                    "type": "boolean",
                    "description": "Does the speaker need to re-convince themselves? True when listener is 'self' and speaker fails to fully believe their own denial."
                },
                "self_correction": {"type": "boolean"},
                "leak_then_overwrite": {"type": "boolean"},
                "residual_marker": {"type": "string"},
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
                "hesitation_level": {"type": "string", "enum": ["low", "medium", "high"]},
                "negation_first": {"type": "boolean"},
                "negation_type": {
                    "type": "string",
                    "enum": ["concealment", "declaration", "rationalization", "none"],
                    "description": "Type of negation preserved in translation"
                },
                "listener_type": {
                    "type": "string",
                    "enum": ["other_specific", "other_general", "self", "absent"],
                    "description": "Who the utterance is directed at"
                },
                "self_directed_rebinding": {
                    "type": "boolean",
                    "description": "Whether the translation includes self-rebinding (double negation for self-convincing)"
                },
                "self_correction": {"type": "boolean"},
                "leak_then_overwrite": {"type": "boolean"},
                "residual_marker": {"type": "string"},
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
                "z_axis_intensity",
            ],
        },
        "notes": {"type": "string", "maxLength": 280},
        "alternatives": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["translation", "z_signature", "notes", "alternatives"],
}


# -----------------------------
# YAML v2.0 Helper Functions
# -----------------------------

def extract_v2_features(persona_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    YAML v2.0からlanguage, emotion_states, example_lines, triggersを抽出。
    存在しない場合は空のデフォルトを返す（v1.0との後方互換性）。
    """
    return {
        "language": persona_dict.get("language", {}),
        "emotion_states": persona_dict.get("emotion_states", []),
        "example_lines": persona_dict.get("example_lines", []),
        "triggers": persona_dict.get("triggers", []),
    }


def get_emotion_state_constraints(
    emotion_states: List[Dict[str, Any]], 
    z_intensity: str
) -> Dict[str, Any]:
    """
    z_intensity (low/medium/high) に対応するemotion_stateの
    surface_markers_hintを返す。該当がなければデフォルト。
    """
    for state in emotion_states:
        if state.get("z_intensity") == z_intensity:
            return state.get("surface_markers_hint", {})
    # デフォルト（v1.0互換）
    return {
        "hesitation": "default",
        "negation_first": "default",
        "stutter_count": "default",
        "overwrite": "optional",
        "residual": "optional",
    }


def format_example_lines(
    example_lines: List[Dict[str, Any]], 
    max_examples: int = 3
) -> str:
    """
    example_linesをfew-shot用テキストにフォーマット（最大max_examples個）。
    """
    if not example_lines:
        return "(No example lines provided)"
    
    lines = []
    for ex in example_lines[:max_examples]:
        tags = ex.get("tags", [])
        tags_str = ", ".join(tags) if tags else "general"
        line = ex.get("line", "")
        situation = ex.get("situation", "")
        lines.append(f"- [{tags_str}] ({situation}) {line}")
    
    return "\n".join(lines)


def format_trigger_info(triggers: List[Dict[str, Any]]) -> str:
    """
    triggersをテキストにフォーマット。
    """
    if not triggers:
        return "(No specific triggers defined)"
    
    lines = []
    for t in triggers:
        trigger = t.get("trigger", "")
        reaction = t.get("reaction", "")
        z_delta = t.get("z_delta", "")
        effect = t.get("surface_effect", "")
        lines.append(f"- Trigger: {trigger} → {reaction} (Δz={z_delta}, effect={effect})")
    
    return "\n".join(lines)


# -----------------------------
# Config loader
# -----------------------------

def load_config(config_path: str) -> Dict[str, Any]:
    """
    YAML設定ファイルを読み込む。
    persona_file が指定されていればそのファイルも読み込んでマージする。
    """
    config_path = Path(config_path)
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    # persona_file があればそのファイルを読み込んでpersona_yamlを生成
    if 'persona_file' in config and config['persona_file']:
        persona_path = config_path.parent / config['persona_file']
        if not persona_path.exists():
            # 絶対パスとしても試す
            persona_path = Path(config['persona_file'])
        
        with open(persona_path, 'r', encoding='utf-8') as f:
            persona_data = yaml.safe_load(f)
        config['persona_yaml'] = yaml.dump(persona_data, allow_unicode=True, default_flow_style=False)
    
    # persona が直接定義されている場合
    elif 'persona' in config:
        config['persona_yaml'] = yaml.dump(config['persona'], allow_unicode=True, default_flow_style=False)
    
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
        """
        Responses APIの返却JSONから output_text (SDKの便利プロパティ相当) を抽出する。
        """
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
        max_output_tokens: int = 800,
        temperature: float = 0.2,
        dry_run: bool = False,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        text.format=json_schema を使って「必ず指定スキーマに一致するJSON」を返させる。
        """
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
# STEP prompts
# -----------------------------

def build_step1_messages(persona_yaml: str, scene: str, relationship: str, context_block: str,
                         target_line: str, target_lang: str, z_axis_intensity: str) -> List[Dict[str, str]]:
    system = (
        "You are STEP1 Hamiltonian Extractor for Z-Axis Translation.\n"
        "Task: infer the active conflict axes and bias mode that produced the TARGET line.\n\n"
        "[LISTENER TYPE INFERENCE]\n"
        "Based on the Relationship and Context, determine who the utterance is directed at:\n"
        "- 'other_specific': Speaking TO a specific person who is PRESENT in the scene\n"
        "- 'other_general': Speaking to a general audience or unspecified listeners\n"
        "- 'self': MONOLOGUE / SELF-TALK. Key indicators:\n"
        "  * Relationship mentions '自分自身', 'self', '独り言', 'monologue'\n"
        "  * Context shows the speaker is ALONE or talking to themselves\n"
        "  * No one else is listening or responding\n"
        "- 'absent': Talking ABOUT someone who is NOT present (muttering about them)\n\n"
        "Output MUST follow the provided JSON schema. Do NOT include chain-of-thought.\n"
        "analysis_summary must be <= 25 words.\n"
    )
    user = (
        f"[Persona YAML]\n{persona_yaml}\n\n"
        f"[Scene]\n{scene}\n\n"
        f"[Relationship]\n{relationship}\n\n"
        f"[Conversation Block]\n{context_block}\n\n"
        f"[TARGET]\n{target_line}\n\n"
        f"[Target Language]\n{target_lang}\n"
        f"[Z Axis Intensity]\n{z_axis_intensity}\n"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_step2_messages(step1_json: Dict[str, Any], target_line: str, target_lang: str, z_axis_intensity: str, relationship: str = "") -> List[Dict[str, str]]:
    system = (
        "You are STEP2 Interference Pattern Analyzer for Z-Axis Translation.\n"
        "Given STEP1 output, estimate WaveA (true intent) vs WaveB (suppression) and the observable surface markers.\n\n"
        "[NEGATION TYPE CLASSIFICATION]\n"
        "If the utterance contains negation, classify its type:\n"
        "- 'concealment': Hiding true feelings (e.g., tsundere denial). True intent is OPPOSITE of surface.\n"
        "  Example: 'It's not like I did it for you' (but actually did it for you)\n"
        "  Characteristics: conflict present, self-deception, double negation in monologue\n"
        "- 'declaration': Asserting truth, correcting misunderstanding. True intent MATCHES surface.\n"
        "  Example: 'It's not for you. I did it for myself.' (genuinely meant)\n"
        "  Characteristics: no conflict, direct assertion, no self-deception\n"
        "- 'rationalization': Logical justification to mask emotional motivation.\n"
        "  Example: 'This isn't wrong. It's justice.' (self-justification)\n"
        "  Characteristics: conflict 'resolved' through logic, cold/rigid tone\n"
        "- 'none': No negation in the utterance.\n\n"
        "[LISTENER TYPE - USE STEP1's listener_type]\n"
        "STEP1 has already inferred the listener_type. Use that value.\n"
        "But verify against the relationship info provided below.\n\n"
        "[SELF-DIRECTED REBINDING]\n"
        "When listener_type is 'self' AND negation_type is 'concealment':\n"
        "- The speaker is trying to convince THEMSELVES of a lie they know is false.\n"
        "- This often fails, requiring a SECOND denial to re-convince.\n"
        "- Set self_directed_rebinding: true when this double-denial pattern is needed.\n"
        "- Example: 'It's not for him... I mean, it's NOT.' (the 'I mean, it's NOT' is rebinding)\n"
        "- This does NOT occur when listener is 'other' (one denial is enough for others).\n\n"
        "Output MUST follow the provided JSON schema. Do NOT include chain-of-thought.\n"
        "analysis_summary must be <= 25 words.\n"
    )
    user = (
        f"[STEP1 JSON]\n{json.dumps(step1_json, ensure_ascii=False)}\n\n"
        f"[Relationship]\n{relationship}\n\n"
        f"[TARGET]\n{target_line}\n"
        f"[Target Language]\n{target_lang}\n"
        f"[Requested Z Axis Intensity]\n{z_axis_intensity}\n"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_step3_messages(
    step1_json: Dict[str, Any], 
    step2_json: Dict[str, Any], 
    target_line: str, 
    target_lang: str,
    persona_dict: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, str]]:
    """
    STEP3プロンプトを構築（YAML v2.0対応版）。
    
    v2.0の場合:
    - emotion_statesからsurface_markers_hintを取得
    - example_linesをfew-shot例として注入（2-4個）
    - languageとtriggersの情報も活用
    """
    # v2.0特徴の抽出（persona_dictがあれば）
    v2_features = extract_v2_features(persona_dict) if persona_dict else {}
    
    # Z強度を取得（STEP2から）
    z_intensity = step2_json.get("surface_markers", {}).get("z_axis_intensity", "medium")
    
    # emotion_statesから制約を取得
    constraints = get_emotion_state_constraints(
        v2_features.get("emotion_states", []), 
        z_intensity
    )
    
    # few-shot例をフォーマット
    examples_text = format_example_lines(
        v2_features.get("example_lines", []), 
        max_examples=3
    )
    
    # 言語設定
    language_info = v2_features.get("language", {})
    language_block = ""
    if language_info:
        fp = language_info.get("first_person", "")
        sp = language_info.get("second_person_user", "")
        addr = language_info.get("address_style", "")
        language_block = f"""
[CHARACTER VOICE]
First person: {fp}
Second person (to user): {sp}
Address style: {addr}
"""
    
    # トリガー情報
    trigger_text = format_trigger_info(v2_features.get("triggers", []))
    
    # 制約ブロックを構築
    constraint_block = f"""
[SURFACE MARKER CONSTRAINTS] (from emotion_state @ z={z_intensity})
- hesitation: {constraints.get('hesitation', 'default')}
- stutter_count: {constraints.get('stutter_count', 'default')}
- negation_first: {constraints.get('negation_first', 'default')}
- overwrite: {constraints.get('overwrite', 'optional')}
- residual: {constraints.get('residual', 'optional')}
"""
    
    system = f"""You are STEP3 Z-Axis Preserving Translator.

Goal: translate TARGET into the target language while preserving:
  - Semantics (meaning)
  - Style (register)
  - Dynamics (conflict×bias interference pattern)
  - Negation Type (the DIRECTION of negation, not just the form)
  - Listener Type (WHO the utterance is directed at)

[NEGATION TYPE PRESERVATION]
The negation_type from STEP2 indicates what the negation is DOING:
- 'concealment': The speaker is HIDING their true feelings. Keep the denial but let warmth leak.
  → Use stutters, ellipsis, defensive tags like "or anything", "okay?"
- 'declaration': The speaker is STATING truth. Keep it direct and confident.
  → Clean negation, no hesitation, assertive tone
- 'rationalization': The speaker is JUSTIFYING themselves. Keep it logical and cold.
  → Formal phrasing, logical connectors, minimal emotion
- 'none': No negation to preserve.

[LISTENER TYPE EFFECTS ON TRANSLATION]
- 'other_specific': Standard denial with defensive tags ("okay?", "got it?")
- 'other_general': Slightly more formal/distanced denial
- 'self': CRITICAL - Monologue requires DIFFERENT treatment:
  → The self is the HARDEST listener (they know their own truth)
  → NO defensive tags like "okay?" (no one to confirm with)
  → May need REBINDING if self_directed_rebinding is true
- 'absent': Talking about someone not present, may use third person

[SELF-DIRECTED REBINDING - CRITICAL FOR MONOLOGUE]
When self_directed_rebinding is TRUE:
- The speaker is trying to convince THEMSELVES but FAILING
- They need a SECOND denial to re-convince: "I mean— it's not."
- This is a SELF-REPAIR operation, not explanation
- Example pattern: "It's not for him... I mean, it's NOT."
                    ^^^^^first denial^^^^  ^^^rebinding^^^
- The rebinding shows the speaker doesn't fully believe their own lie
- This is UNIQUE to self-directed speech and MUST be preserved

CRITICAL: Preserve the ARROW DIRECTION, not just the negation word.

{constraint_block}

[EXAMPLE LINES] (for tone/vocabulary reference ONLY — do NOT copy)
{examples_text}

[KNOWN TRIGGERS]
{trigger_text}

Use the surface_markers to realize hesitation/negation/leak/overwrite/residual.
Output MUST follow the provided JSON schema. Do NOT include chain-of-thought.
"""
    
    user = f"""{language_block}
[STEP1 JSON]
{json.dumps(step1_json, ensure_ascii=False)}

[STEP2 JSON]
{json.dumps(step2_json, ensure_ascii=False)}

[TARGET]
{target_line}

[Target Language]
{target_lang}

Constraints:
- Keep it natural in the target language.
- Do not over-explain; the dynamics must be implicit in phrasing.
- Provide up to 2 alternatives.
- Match the character's voice (first_person, address_style) if specified.
"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


# -----------------------------
# Orchestrator (STEP1→2→3)
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
) -> Dict[str, Any]:
    """
    Z軸翻訳を実行する。
    STEP1（ハミルトニアン抽出）→ STEP2（干渉縞分析）→ STEP3（翻訳生成）
    
    YAML v2.0対応: persona_yamlにlanguage, emotion_states, example_lines, triggers
    が含まれていれば、STEP3でそれらを活用する。
    """
    # persona_yamlをパースしてv2.0機能を抽出
    try:
        persona_dict = yaml.safe_load(persona_yaml)
    except yaml.YAMLError:
        persona_dict = {}  # パース失敗時は空辞書（v1.0互換モード）
    
    # STEP1: ハミルトニアン抽出（逆問題）
    s1_msgs = build_step1_messages(persona_yaml, scene, relationship, context_block, target_line, target_lang, z_axis_intensity)
    s1_payload, step1 = client.create_structured(
        model=model,
        name="step1_hamiltonian",
        schema=STEP1_SCHEMA,
        messages=s1_msgs,
        max_output_tokens=700,
        temperature=0.2,
        dry_run=dry_run,
    )
    if dry_run:
        return {"step1_request": s1_payload}

    # STEP2: 干渉縞分析
    s2_msgs = build_step2_messages(step1, target_line, target_lang, z_axis_intensity, relationship)
    _, step2 = client.create_structured(
        model=model,
        name="step2_interference",
        schema=STEP2_SCHEMA,
        messages=s2_msgs,
        max_output_tokens=700,
        temperature=0.2,
        dry_run=False,
    )

    # STEP3: Z軸保存翻訳生成（v2.0: persona_dictも渡す）
    s3_msgs = build_step3_messages(step1, step2, target_line, target_lang, persona_dict=persona_dict)
    _, step3 = client.create_structured(
        model=model,
        name="step3_translation",
        schema=STEP3_SCHEMA,
        messages=s3_msgs,
        max_output_tokens=500,
        temperature=0.4,
        dry_run=False,
    )

    return {"step1": step1, "step2": step2, "step3": step3}


# -----------------------------
# Demo data (Kurisu example)
# -----------------------------

DEMO_PERSONA_YAML = """persona:
  name: "牧瀬紅莉栖"
  source: "Steins;Gate"
  type: "ツンデレ × 天才科学者"
conflict_axes:
  - "論理的でいたい" vs "感情が溢れる"
  - "好意を認めたい" vs "素直になれない"
  - "強くありたい" vs "本当は甘えたい"
  - "認められたい" vs "照れくさい"
bias:
  default_mode: "照れ隠し・強がり"
  pattern: "ツン → 素直 → 即座にツンで上書き"
weakness:
  primary: "好意への直接的言及"
  secondary: "『助手』『クリスティーナ』等のあだ名"
"""

DEMO_CONTEXT_BLOCK = """[岡部] なあ、紅莉栖
[紅莉栖] …何よ
[岡部] お前、俺のこと好きだろ？
[紅莉栖] はぁ!? 何言ってんの！
[岡部] 図星か
[紅莉栖] まあ…別にいいんだけどさ…うん
"""

DEMO_SCENE = "ラボ、二人きり"
DEMO_RELATIONSHIP = "両思い、未告白"
DEMO_TARGET_LINE = "まあ…別にいいんだけどさ…うん"
DEMO_TARGET_LANG = "en"
DEMO_Z_INTENSITY = "high"


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Z-Axis Translation System — Operation: Babel Inverse",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # YAML設定ファイルで実行
  python z_axis_translate.py --config requests/kurisu_test.yaml

  # 強度を上書き
  python z_axis_translate.py --config requests/test.yaml --intensity high

  # 内蔵デモ（紅莉栖）
  python z_axis_translate.py --demo

  # リクエストだけ確認
  python z_axis_translate.py --demo --dry-run
        """
    )
    ap.add_argument("--model", default=DEFAULT_MODEL, help="使用するモデル")
    ap.add_argument("--config", type=str, help="YAML設定ファイルのパス")
    ap.add_argument("--intensity", type=str, choices=["low", "medium", "high"],
                    help="Z軸強度（configの値を上書き）")
    ap.add_argument("--demo", action="store_true", help="内蔵の紅莉栖デモを実行")
    ap.add_argument("--dry-run", action="store_true", help="APIを叩かず、STEP1のリクエストを出力")
    ap.add_argument("--output", "-o", type=str, help="結果をJSONファイルに出力")
    args = ap.parse_args()

    # 引数チェック
    if not args.demo and not args.config:
        print("Error: --demo または --config のいずれかを指定してください。")
        print("Use --help for usage information.")
        return

    client = OpenAIResponsesClient()

    if args.config:
        # YAML設定ファイルから読み込み
        config = load_config(args.config)
        
        # 必須フィールドのチェック
        required_fields = ['scene', 'relationship', 'context_block', 'target_line', 'target_lang']
        for field in required_fields:
            if field not in config:
                print(f"Error: 設定ファイルに '{field}' が必要です。")
                return
        
        if 'persona_yaml' not in config:
            print("Error: persona_file または persona の定義が必要です。")
            return
        
        # 強度の上書き
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
        )
    else:
        # 内蔵デモ
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

    # 出力
    result_json = json.dumps(out, ensure_ascii=False, indent=2)
    
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(result_json)
        print(f"Result saved to: {args.output}")
    else:
        print(result_json)


if __name__ == "__main__":
    main()
