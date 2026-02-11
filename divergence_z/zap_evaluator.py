#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZAP (Z-Axis Preservation) Evaluator v3.0
========================================

Evaluate the quality of Z-axis translation.
Use an LLM to determine whether the translated text
is appropriate for the persona × context × source text.

v3.0 Changes:
- z_mode preservation evaluation
- z_leak marker detection
- arc_phase appropriateness check

How to Use:
  # Specify the translation directly
  python zap_evaluator.py \
    --persona personas/レム_v3.yaml \
    --config requests/rem_test.yaml \
    --translated "I love you, Subaru-kun."

  # Compare multiple translations
  python zap_evaluator.py \
    --persona personas/レム_v3.yaml \
    --config requests/rem_test.yaml \
    --compare "DeepL: Rem loves Subaru." "Z-Axis: I love you, Subaru-kun."
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1")


# -----------------------------
# Schema v3.0
# -----------------------------

ZAP_RESULT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "overall_score": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "Overall Z-Axis preservation score"
        },
        "character_voice": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "preserved": {"type": "boolean"},
                "comment": {"type": "string", "maxLength": 200}
            },
            "required": ["score", "preserved", "comment"]
        },
        "emotional_intensity": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "preserved": {"type": "boolean"},
                "original_level": {"type": "string", "enum": ["low", "medium", "high"]},
                "translated_level": {"type": "string", "enum": ["low", "medium", "high"]},
                "comment": {"type": "string", "maxLength": 200}
            },
            "required": ["score", "preserved", "original_level", "translated_level", "comment"]
        },
        "listener_relationship": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "preserved": {"type": "boolean"},
                "original_type": {
                    "type": "string",
                    "enum": ["direct_address", "third_person", "self_reference", "indirect"]
                },
                "translated_type": {
                    "type": "string",
                    "enum": ["direct_address", "third_person", "self_reference", "indirect"]
                },
                "comment": {"type": "string", "maxLength": 200}
            },
            "required": ["score", "preserved", "original_type", "translated_type", "comment"]
        },
        "speech_pattern": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "preserved": {"type": "boolean"},
                "comment": {"type": "string", "maxLength": 200}
            },
            "required": ["score", "preserved", "comment"]
        },
        # v3.0: Z-Axis Fidelity
        "z_axis_fidelity": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "z_mode_appropriate": {
                    "type": "boolean",
                    "description": "Does the translation reflect the expected z_mode (collapse/rage/numb/plea/shame/leak/none)?"
                },
                "z_mode_detected": {
                    "type": "string",
                    "enum": ["collapse", "rage", "numb", "plea", "shame", "leak", "none"],
                    "description": "What z_mode does the translation exhibit?"
                },
                "z_leak_markers_found": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["stutter", "ellipsis", "repetition", "negation_first", "overwrite", "trailing", "self_negation", "none"]
                    },
                    "description": "Which z_leak markers are present in the translation?"
                },
                "z_leak_appropriate": {
                    "type": "boolean",
                    "description": "Are the z_leak markers appropriate for the emotional context?"
                },
                "arc_phase_appropriate": {
                    "type": "boolean",
                    "description": "Does the translation fit the expected arc phase (bottom/rise/break/recovery/stable)?"
                },
                "score": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0
                },
                "comment": {"type": "string", "maxLength": 200}
            },
            "required": [
                "z_mode_appropriate",
                "z_mode_detected",
                "z_leak_markers_found",
                "z_leak_appropriate",
                "arc_phase_appropriate",
                "score",
                "comment"
            ]
        },
        "critical_issues": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of critical issues that break character voice or emotional dynamics"
        },
        "summary": {
            "type": "string",
            "maxLength": 300,
            "description": "Brief summary of the evaluation"
        }
    },
    "required": [
        "overall_score",
        "character_voice",
        "emotional_intensity", 
        "listener_relationship",
        "speech_pattern",
        "z_axis_fidelity",
        "critical_issues",
        "summary"
    ]
}


# -----------------------------
# LLM Evaluation
# -----------------------------

def build_zap_prompt(
    persona_yaml: str,
    context: str,
    original_text: str,
    translated_text: str,
    target_lang: str,
    emotion_state: Optional[str] = None,
    expected_z_mode: Optional[str] = None,
    expected_z_leak: Optional[List[str]] = None,
    expected_arc_phase: Optional[str] = None,
) -> List[Dict[str, str]]:
    """ZAP評価用のプロンプトを構築（v3.0）"""
    
    emotion_hint = f"\n[EMOTION STATE] {emotion_state}" if emotion_state else ""
    
    # v3.0 hints
    z_hints = []
    if expected_z_mode:
        z_hints.append(f"[EXPECTED Z_MODE] {expected_z_mode}")
    if expected_z_leak:
        z_hints.append(f"[EXPECTED Z_LEAK] {', '.join(expected_z_leak)}")
    if expected_arc_phase:
        z_hints.append(f"[EXPECTED ARC_PHASE] {expected_arc_phase}")
    z_hints_str = "\n".join(z_hints)
    
    system = """You are an expert in character voice preservation and emotional nuance in translation.

Your task: Evaluate whether a translation preserves the CHARACTER'S VOICE and EMOTIONAL DYNAMICS, not just literal meaning.

## Evaluation Criteria

1. **Character Voice** (0.0-1.0)
   - Does the translation sound like something this character would actually say?
   - Is the character's unique speech pattern reflected?
   - Consider: first-person reference style, politeness level, word choice tendencies

2. **Emotional Intensity** (0.0-1.0)
   - Is the emotional strength preserved? (low/medium/high)
   - A passionate confession should remain passionate, not become clinical

3. **Listener Relationship** (0.0-1.0)
   - Is the addressee relationship preserved?
   - CRITICAL: Japanese self-reference by name (e.g., "レムは〜") in confessions is DIRECT ADDRESS to the listener, NOT third-person narration
   - Translating "レムは〜愛しています" as "Rem loves..." loses the intimacy; "I love you" preserves it

4. **Speech Pattern** (0.0-1.0)
   - Hesitation, confidence, negation patterns
   - Character-specific verbal tics or tendencies

5. **Z-Axis Fidelity** (v3.0) (0.0-1.0)
   - z_mode: Does the translation reflect the emotional breakdown type?
     - collapse: stuttering, broken sentences, repetition
     - rage: harsh vocabulary, fluent but aggressive
     - numb: flat, emotionless, short
     - plea: begging, repetitive requests
     - shame: self-negation, hesitation
     - leak: denial followed by truth slipping out (tsundere)
     - none: stable speech
   - z_leak markers: Are appropriate markers present?
     - stutter: "I— I..."
     - ellipsis: "..."
     - repetition: "nobody— nobody"
     - negation_first: "N-not that..."
     - overwrite: "I mean—"
     - trailing: "...I guess"
     - self_negation: "I'm worthless"
   - arc_phase: Does the tone fit the emotional arc position?
     - bottom: lowest point, despair
     - rise: building emotion
     - break: turning point
     - recovery: coming back
     - stable: neutral

## Critical Issues to Flag
- Third-person narration replacing direct confession
- Loss of intimacy/directness
- Emotional flattening
- Out-of-character word choices
- Wrong politeness register
- Missing z_leak markers when emotion is high
- Wrong z_mode (e.g., stable when should be collapse)

Output MUST be valid JSON matching the provided schema.
"""

    user = f"""[PERSONA]
{persona_yaml}

[CONTEXT]
{context}
{emotion_hint}
{z_hints_str}

[ORIGINAL TEXT]
{original_text}

[TRANSLATED TEXT ({target_lang})]
{translated_text}

Evaluate the Z-Axis preservation of this translation (v3.0).
Consider: Does this translation make the character "live" in the target language, with appropriate emotional breakdown patterns (z_mode) and surface markers (z_leak)?
"""
    
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user}
    ]


def evaluate_zap(
    client: OpenAI,
    persona_yaml: str,
    context: str,
    original_text: str,
    translated_text: str,
    target_lang: str = "en",
    emotion_state: Optional[str] = None,
    expected_z_mode: Optional[str] = None,
    expected_z_leak: Optional[List[str]] = None,
    expected_arc_phase: Optional[str] = None,
    model: str = DEFAULT_MODEL,
) -> Dict[str, Any]:
    """ZAP評価を実行（v3.0）"""
    
    messages = build_zap_prompt(
        persona_yaml=persona_yaml,
        context=context,
        original_text=original_text,
        translated_text=translated_text,
        target_lang=target_lang,
        emotion_state=emotion_state,
        expected_z_mode=expected_z_mode,
        expected_z_leak=expected_z_leak,
        expected_arc_phase=expected_arc_phase,
    )
    
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "zap_result_v3",
                "strict": True,
                "schema": ZAP_RESULT_SCHEMA,
            }
        },
        temperature=0.2,
        max_completion_tokens=1200,
    )
    
    result = json.loads(resp.choices[0].message.content)
    return result


# -----------------------------
# Config Loading
# -----------------------------

def load_yaml(path: str) -> Dict[str, Any]:
    """YAMLファイルを読み込む"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {p}")
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def load_persona(config: Dict[str, Any], config_dir: Path) -> str:
    """ペルソナYAMLを読み込んで文字列として返す"""
    if "persona_file" in config:
        persona_file = config["persona_file"]
        
        # 1. まずカレントディレクトリからの相対パスを試す
        persona_path = Path(persona_file)
        if persona_path.exists():
            return persona_path.read_text(encoding="utf-8")
        
        # 2. 次にconfigファイルからの相対パスを試す
        persona_path = config_dir / persona_file
        if persona_path.exists():
            return persona_path.read_text(encoding="utf-8")
        
        # 3. 見つからない
        raise FileNotFoundError(
            f"Persona file not found: {persona_file}\n"
            f"  Tried: {Path(persona_file).absolute()}\n"
            f"  Tried: {(config_dir / persona_file).absolute()}"
        )
    elif "persona" in config:
        return yaml.dump(config["persona"], allow_unicode=True, default_flow_style=False)
    else:
        raise ValueError("Config must have 'persona_file' or 'persona'")


def build_context_from_config(config: Dict[str, Any]) -> str:
    """configからコンテキスト文字列を構築"""
    parts = []
    if "scene" in config:
        parts.append(f"[Scene] {config['scene']}")
    if "relationship" in config:
        parts.append(f"[Relationship] {config['relationship']}")
    if "context_block" in config:
        parts.append(f"[Dialogue]\n{config['context_block']}")
    if "notes" in config:
        parts.append(f"[Notes]\n{config['notes']}")
    return "\n\n".join(parts)


# -----------------------------
# Report v3.0
# -----------------------------

def print_report(
    original_text: str,
    translated_text: str,
    result: Dict[str, Any],
    label: str = "",
) -> None:
    """評価結果を表示（v3.0）"""
    
    label_str = f" ({label})" if label else ""
    
    print("=" * 60)
    print(f"ZAP (Z-Axis Preservation) Evaluation v3.0{label_str}")
    print("=" * 60)
    print()
    
    print("【Original】")
    print(f"  {original_text}")
    print()
    
    print("【Translated】")
    print(f"  {translated_text}")
    print()
    
    overall = result["overall_score"]
    star = "★" if overall >= 0.8 else "☆" if overall >= 0.6 else "✗"
    print(f"【ZAP Score】")
    print(f"  {star} Overall: {overall:.2f}")
    
    cv = result["character_voice"]
    ei = result["emotional_intensity"]
    lr = result["listener_relationship"]
    sp = result["speech_pattern"]
    zf = result["z_axis_fidelity"]
    
    print(f"  ├─ Character Voice: {cv['score']:.2f} {'✓' if cv['preserved'] else '✗'}")
    print(f"  │    {cv['comment']}")
    print(f"  ├─ Emotional Intensity: {ei['score']:.2f} {'✓' if ei['preserved'] else '✗'}")
    print(f"  │    {ei['original_level']} → {ei['translated_level']}: {ei['comment']}")
    print(f"  ├─ Listener Relationship: {lr['score']:.2f} {'✓' if lr['preserved'] else '✗'}")
    print(f"  │    {lr['original_type']} → {lr['translated_type']}: {lr['comment']}")
    print(f"  ├─ Speech Pattern: {sp['score']:.2f} {'✓' if sp['preserved'] else '✗'}")
    print(f"  │    {sp['comment']}")
    
    # v3.0: Z-Axis Fidelity
    print(f"  └─ Z-Axis Fidelity: {zf['score']:.2f}")
    print(f"       z_mode: {zf['z_mode_detected']} {'✓' if zf['z_mode_appropriate'] else '✗'}")
    z_leak_str = ", ".join(zf['z_leak_markers_found']) if zf['z_leak_markers_found'] else "none"
    print(f"       z_leak: [{z_leak_str}] {'✓' if zf['z_leak_appropriate'] else '✗'}")
    print(f"       arc_phase: {'✓' if zf['arc_phase_appropriate'] else '✗'}")
    print(f"       {zf['comment']}")
    print()
    
    if result["critical_issues"]:
        print("【Critical Issues】")
        for issue in result["critical_issues"]:
            print(f"  ⚠️ {issue}")
        print()
    
    print("【Summary】")
    print(f"  {result['summary']}")
    print()


# -----------------------------
# Main
# -----------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="ZAP (Z-Axis Preservation) Evaluator v3.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", required=True, help="YAML config file (with persona, context, original)")
    parser.add_argument("--translated", "-t", help="Translated text to evaluate")
    parser.add_argument("--compare", nargs="+", help="Multiple translations to compare (format: 'Label: text')")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Model to use (default: {DEFAULT_MODEL})")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    
    # v3.0 options
    parser.add_argument("--z-mode", help="Expected z_mode (collapse/rage/numb/plea/shame/leak/none)")
    parser.add_argument("--z-leak", nargs="+", help="Expected z_leak markers")
    parser.add_argument("--arc-phase", help="Expected arc_phase (bottom/rise/break/recovery/stable)")
    
    args = parser.parse_args()
    
    # Load config
    config_path = Path(args.config)
    config = load_yaml(args.config)
    config_dir = config_path.parent
    
    # Load persona
    persona_yaml = load_persona(config, config_dir)
    
    # Build context
    context = build_context_from_config(config)
    
    # Get original text
    original_text = config.get("target_line", "").strip()
    if not original_text:
        print("Error: config must have 'target_line'", file=sys.stderr)
        return 1
    
    # Get target language
    target_lang = config.get("target_lang", "en")
    
    # Get emotion state (optional)
    emotion_state = config.get("emotion_state")
    
    # v3.0: Get expected z values from config or args
    expected_z_mode = args.z_mode or config.get("z_mode")
    expected_z_leak = args.z_leak or config.get("z_leak_hint")
    expected_arc_phase = args.arc_phase or config.get("arc_phase")
    
    # Build client
    client = OpenAI()
    
    # Collect translations to evaluate
    translations = []
    if args.translated:
        translations.append(("", args.translated))
    if args.compare:
        for item in args.compare:
            if ": " in item:
                label, text = item.split(": ", 1)
                translations.append((label.strip(), text.strip()))
            else:
                translations.append(("", item.strip()))
    
    if not translations:
        print("Error: provide --translated or --compare", file=sys.stderr)
        return 1
    
    # Evaluate each translation
    results = []
    for label, translated_text in translations:
        result = evaluate_zap(
            client=client,
            persona_yaml=persona_yaml,
            context=context,
            original_text=original_text,
            translated_text=translated_text,
            target_lang=target_lang,
            emotion_state=emotion_state,
            expected_z_mode=expected_z_mode,
            expected_z_leak=expected_z_leak,
            expected_arc_phase=expected_arc_phase,
            model=args.model,
        )
        results.append({
            "label": label,
            "translated": translated_text,
            "result": result,
        })
    
    # Output
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for item in results:
            print_report(
                original_text=original_text,
                translated_text=item["translated"],
                result=item["result"],
                label=item["label"],
            )
        
        # Comparison summary if multiple
        if len(results) > 1:
            print("=" * 60)
            print("【Comparison Summary】")
            print("=" * 60)
            sorted_results = sorted(results, key=lambda x: x["result"]["overall_score"], reverse=True)
            for i, item in enumerate(sorted_results, 1):
                label = item["label"] or "Translation"
                score = item["result"]["overall_score"]
                zf = item["result"]["z_axis_fidelity"]
                print(f"  {i}. {label}: {score:.2f} (z_mode={zf['z_mode_detected']}, z_leak={len(zf['z_leak_markers_found'])} markers)")
            print()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())