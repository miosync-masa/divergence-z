#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YAML Formatter v3.0 for Z-Axis Dialogue Translation
原作スクリプトを z_axis_dialogue.py 用のYAML形式に変換

v3.0 Changes:
- Support for _v3.yaml persona files
- z_mode hints in dialogue generation

Usage:
    python yaml_formatter.py \
      --script scripts/rem_subaru_zero.txt \
      --persona-a personas/レム_v3.yaml \
      --persona-b personas/スバル_v3.yaml \
      --hint "白鯨戦前夜、スバルが自己否定、レムの告白"

    # 出力ファイル指定
    python yaml_formatter.py \
      --script scripts/rem_subaru_zero.txt \
      --persona-a personas/レム_v3.yaml \
      --persona-b personas/スバル_v3.yaml \
      --hint "白鯨戦前夜" \
      --output requests/rem_subaru_dialogue.yaml

Script Format:
    キャラ名「セリフ」
    キャラ名「セリフ」
    
    Example:
    スバル「どれだけ頑張っても、誰も救えなかった。」
    レム「レムがいます。」
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1")


# =============================================================================
# Script Parser
# =============================================================================

def parse_script(script_text: str) -> List[Tuple[str, str]]:
    """
    スクリプトをパースして (キャラ名, セリフ) のリストを返す
    
    対応形式:
    - キャラ名「セリフ」
    - キャラ名『セリフ』
    - キャラ名: セリフ
    - キャラ名：セリフ
    """
    lines = []
    
    # パターン1: 「」『』で囲まれたセリフ
    pattern1 = re.compile(r'^([^「『:：\s]+)[「『](.+?)[」』]$')
    
    # パターン2: コロン区切り
    pattern2 = re.compile(r'^([^:：\s]+)[：:](.+)$')
    
    for line in script_text.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        
        # パターン1を試す
        match = pattern1.match(line)
        if match:
            speaker = match.group(1).strip()
            dialogue = match.group(2).strip()
            lines.append((speaker, dialogue))
            continue
        
        # パターン2を試す
        match = pattern2.match(line)
        if match:
            speaker = match.group(1).strip()
            dialogue = match.group(2).strip()
            lines.append((speaker, dialogue))
            continue
        
        # どちらにもマッチしない場合はスキップ（コメント行など）
        print(f"[SKIP] Cannot parse: {line[:50]}...")
    
    return lines


def extract_character_names(parsed_lines: List[Tuple[str, str]]) -> List[str]:
    """パースされた行からユニークなキャラ名を抽出"""
    names = []
    seen = set()
    for speaker, _ in parsed_lines:
        if speaker not in seen:
            names.append(speaker)
            seen.add(speaker)
    return names


def get_persona_name(persona_path: str) -> str:
    """ペルソナYAMLから名前を抽出"""
    try:
        with open(persona_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        # persona.name または character.name を探す
        if 'persona' in data and 'name' in data['persona']:
            return data['persona']['name']
        if 'character' in data and 'name' in data['character']:
            return data['character']['name']
        
        # ファイル名から推測（v3, v2 対応）
        stem = Path(persona_path).stem
        stem = stem.replace('_v3', '').replace('_v2', '').replace('_', '')
        return stem
    except Exception as e:
        print(f"[WARN] Cannot read persona name from {persona_path}: {e}")
        return Path(persona_path).stem


def get_persona_version(persona_path: str) -> str:
    """ペルソナYAMLからバージョンを抽出"""
    try:
        with open(persona_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        return data.get('meta', {}).get('version', '2.0')
    except Exception:
        return '2.0'


# =============================================================================
# Character Mapping
# =============================================================================

def map_characters_to_personas(
    script_names: List[str],
    persona_a_path: str,
    persona_b_path: str,
) -> Dict[str, str]:
    """
    スクリプトのキャラ名をペルソナA/Bにマッピング
    
    Returns:
        {"スバル": "B", "レム": "A"} のような辞書
    """
    persona_a_name = get_persona_name(persona_a_path)
    persona_b_name = get_persona_name(persona_b_path)
    
    mapping = {}
    
    for name in script_names:
        # 完全一致
        if name == persona_a_name:
            mapping[name] = "A"
        elif name == persona_b_name:
            mapping[name] = "B"
        # 部分一致（「牧瀬紅莉栖」と「紅莉栖」など）
        elif name in persona_a_name or persona_a_name in name:
            mapping[name] = "A"
        elif name in persona_b_name or persona_b_name in name:
            mapping[name] = "B"
        else:
            # マッチしない場合は警告
            print(f"[WARN] Cannot map '{name}' to any persona")
            print(f"       Persona A: {persona_a_name}")
            print(f"       Persona B: {persona_b_name}")
            # 登場順でアサイン（A→B）
            if "A" not in mapping.values():
                mapping[name] = "A"
            elif "B" not in mapping.values():
                mapping[name] = "B"
            else:
                print(f"[ERROR] More than 2 characters detected!")
    
    return mapping


# =============================================================================
# LLM: Scene & Relationship Generation
# =============================================================================

CONTEXT_GENERATION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "scene": {
            "type": "string",
            "description": "場所、時間、雰囲気を含むシーン描写（日本語）",
            "maxLength": 200,
        },
        "relationship_a_to_b": {
            "type": "string",
            "description": "AからBへの関係性（例: レム → スバル（片想い・献身））",
            "maxLength": 150,
        },
        "relationship_b_to_a": {
            "type": "string",
            "description": "BからAへの関係性（例: スバル → レム（信頼・でも自己否定中））",
            "maxLength": 150,
        },
        "z_axis_intensity": {
            "type": "string",
            "enum": ["low", "medium", "high"],
            "description": "全体的なZ軸強度",
        },
        "dominant_z_modes": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": ["collapse", "rage", "numb", "plea", "shame", "leak", "none"],
            },
            "description": "この対話で支配的なz_mode（v3.0）",
        },
        "reasoning": {
            "type": "string",
            "description": "推論の根拠（日本語）",
            "maxLength": 200,
        },
    },
    "required": ["scene", "relationship_a_to_b", "relationship_b_to_a", "z_axis_intensity", "dominant_z_modes", "reasoning"],
}


def generate_context(
    persona_a_yaml: str,
    persona_b_yaml: str,
    persona_a_name: str,
    persona_b_name: str,
    dialogue_preview: str,
    scene_hint: str,
    model: str = DEFAULT_MODEL,
) -> Dict[str, Any]:
    """LLMでscene, relationships, z_intensityを生成"""
    
    client = OpenAI()
    
    system_prompt = """You are a dialogue context analyzer for Z-Axis Translation v3.0.

Given:
- Two character personas (A and B)
- A preview of their dialogue
- A hint about the scene

Generate:
1. scene: Describe the setting (location, time, atmosphere) in Japanese
2. relationship_a_to_b: A's relationship to B with emotional context
   Format: "A名 → B名（関係性・感情状態）"
3. relationship_b_to_a: B's relationship to A with emotional context
   Format: "B名 → A名（関係性・感情状態）"
4. z_axis_intensity: Overall emotional intensity (low/medium/high)
5. dominant_z_modes: Which z_modes are most likely in this dialogue

## z_mode definitions:
- collapse: 崩壊、言葉が出ない（絶望、トラウマ）
- rage: 怒り、言葉が荒れる
- numb: 麻痺、感情遮断（諦め）
- plea: 懇願、すがる
- shame: 恥、自己嫌悪
- leak: 漏出（ツンデレ等）
- none: 通常状態

Focus on emotional dynamics, not just factual relationships.
Output must be valid JSON matching the schema."""

    user_prompt = f"""[Persona A: {persona_a_name}]
{persona_a_yaml[:1500]}

[Persona B: {persona_b_name}]
{persona_b_yaml[:1500]}

[Dialogue Preview]
{dialogue_preview}

[Scene Hint]
{scene_hint}

Generate scene, relationships, and z_mode analysis for this dialogue."""

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "context_generation_v3",
                "schema": CONTEXT_GENERATION_SCHEMA,
                "strict": True,
            },
        },
        temperature=0.3,
        max_completion_tokens=800,
    )
    
    return json.loads(response.choices[0].message.content)


# =============================================================================
# YAML Builder
# =============================================================================

def build_dialogue_yaml(
    persona_a_path: str,
    persona_b_path: str,
    parsed_lines: List[Tuple[str, str]],
    char_mapping: Dict[str, str],
    context: Dict[str, Any],
    target_lang: str,
) -> Dict[str, Any]:
    """最終的なYAML構造を構築"""
    
    # dialogue配列を構築
    dialogue = []
    for speaker, line in parsed_lines:
        speaker_id = char_mapping.get(speaker, "A")
        dialogue.append({
            "speaker": speaker_id,
            "line": line,
        })
    
    result = {
        "personas": {
            "A": persona_a_path,
            "B": persona_b_path,
        },
        "scene": context["scene"],
        "relationships": {
            "A_to_B": context["relationship_a_to_b"],
            "B_to_A": context["relationship_b_to_a"],
        },
        "target_lang": target_lang,
        "z_axis_intensity": context["z_axis_intensity"],
        "dialogue": dialogue,
    }
    
    # v3.0: dominant_z_modes を追加
    if "dominant_z_modes" in context:
        result["dominant_z_modes"] = context["dominant_z_modes"]
    
    return result


def format_yaml_output(data: Dict[str, Any]) -> str:
    """YAMLを整形して出力"""
    
    lines = []
    lines.append("# Generated by yaml_formatter.py v3.0")
    lines.append("# Z-Axis Dialogue Translation Request")
    lines.append("")
    
    # personas
    lines.append("personas:")
    lines.append(f'  A: "{data["personas"]["A"]}"')
    lines.append(f'  B: "{data["personas"]["B"]}"')
    lines.append("")
    
    # scene
    lines.append(f'scene: "{data["scene"]}"')
    lines.append("")
    
    # relationships
    lines.append("relationships:")
    lines.append(f'  A_to_B: "{data["relationships"]["A_to_B"]}"')
    lines.append(f'  B_to_A: "{data["relationships"]["B_to_A"]}"')
    lines.append("")
    
    # target_lang & z_axis_intensity
    lines.append(f'target_lang: "{data["target_lang"]}"')
    lines.append(f'z_axis_intensity: "{data["z_axis_intensity"]}"')
    
    # v3.0: dominant_z_modes
    if "dominant_z_modes" in data and data["dominant_z_modes"]:
        lines.append("")
        lines.append("# v3.0: Dominant z_modes in this dialogue")
        lines.append("dominant_z_modes:")
        for mode in data["dominant_z_modes"]:
            lines.append(f'  - "{mode}"')
    
    lines.append("")
    
    # dialogue
    lines.append("dialogue:")
    for turn in data["dialogue"]:
        lines.append(f'  - speaker: {turn["speaker"]}')
        # セリフ内のダブルクォートをエスケープ
        escaped_line = turn["line"].replace('"', '\\"')
        lines.append(f'    line: "{escaped_line}"')
    
    return "\n".join(lines)


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Convert script to Z-Axis Dialogue YAML v3.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--script", "-s", required=True, help="Script file path")
    parser.add_argument("--persona-a", "-a", required=True, help="Persona A YAML path")
    parser.add_argument("--persona-b", "-b", required=True, help="Persona B YAML path")
    parser.add_argument("--hint", required=True, help="Scene hint")
    parser.add_argument("--lang", default="en", help="Target language (default: en)")
    parser.add_argument("--output", "-o", help="Output YAML path")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Model to use")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, no LLM call")
    
    args = parser.parse_args()
    
    # Load script
    script_path = Path(args.script)
    if not script_path.exists():
        print(f"❌ Script file not found: {args.script}")
        return
    
    script_text = script_path.read_text(encoding="utf-8")
    
    # Parse script
    print("=" * 60)
    print("[Parsing Script]")
    print("=" * 60)
    parsed_lines = parse_script(script_text)
    print(f"Parsed {len(parsed_lines)} lines")
    
    # Extract character names
    char_names = extract_character_names(parsed_lines)
    print(f"Characters found: {char_names}")
    
    if len(char_names) > 2:
        print(f"⚠️  Warning: More than 2 characters detected. Only first 2 will be used.")
    
    # Map characters to personas
    print()
    print("=" * 60)
    print("[Character Mapping]")
    print("=" * 60)
    
    persona_a_name = get_persona_name(args.persona_a)
    persona_b_name = get_persona_name(args.persona_b)
    persona_a_ver = get_persona_version(args.persona_a)
    persona_b_ver = get_persona_version(args.persona_b)
    
    print(f"Persona A: {persona_a_name} (v{persona_a_ver}) ({args.persona_a})")
    print(f"Persona B: {persona_b_name} (v{persona_b_ver}) ({args.persona_b})")
    
    char_mapping = map_characters_to_personas(char_names, args.persona_a, args.persona_b)
    print(f"Mapping: {char_mapping}")
    
    # Preview
    print()
    print("=" * 60)
    print("[Dialogue Preview]")
    print("=" * 60)
    for i, (speaker, line) in enumerate(parsed_lines[:5]):
        speaker_id = char_mapping.get(speaker, "?")
        print(f"  [{speaker_id}] {speaker}: {line[:40]}...")
    if len(parsed_lines) > 5:
        print(f"  ... and {len(parsed_lines) - 5} more lines")
    
    if args.dry_run:
        print()
        print("🔍 Dry run - skipping LLM call")
        return
    
    # Load persona YAMLs
    with open(args.persona_a, 'r', encoding='utf-8') as f:
        persona_a_yaml = f.read()
    with open(args.persona_b, 'r', encoding='utf-8') as f:
        persona_b_yaml = f.read()
    
    # Create dialogue preview for LLM
    dialogue_preview = "\n".join([
        f"{speaker}: {line}" for speaker, line in parsed_lines[:10]
    ])
    
    # Generate context
    print()
    print("=" * 60)
    print("[Generating Context v3.0]")
    print("=" * 60)
    print(f"Hint: {args.hint}")
    print(f"Model: {args.model}")
    
    context = generate_context(
        persona_a_yaml=persona_a_yaml,
        persona_b_yaml=persona_b_yaml,
        persona_a_name=persona_a_name,
        persona_b_name=persona_b_name,
        dialogue_preview=dialogue_preview,
        scene_hint=args.hint,
        model=args.model,
    )
    
    print()
    print(f"Scene: {context['scene']}")
    print(f"A→B: {context['relationship_a_to_b']}")
    print(f"B→A: {context['relationship_b_to_a']}")
    print(f"Z-intensity: {context['z_axis_intensity']}")
    print(f"Dominant z_modes: {context.get('dominant_z_modes', [])}")
    print(f"Reasoning: {context['reasoning']}")
    
    # Build YAML
    yaml_data = build_dialogue_yaml(
        persona_a_path=args.persona_a,
        persona_b_path=args.persona_b,
        parsed_lines=parsed_lines,
        char_mapping=char_mapping,
        context=context,
        target_lang=args.lang,
    )
    
    yaml_output = format_yaml_output(yaml_data)
    
    # Output
    print()
    print("=" * 60)
    print("[Generated YAML v3.0]")
    print("=" * 60)
    print(yaml_output)
    
    # Save
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(yaml_output, encoding="utf-8")
        print()
        print(f"✅ Saved to: {args.output}")
    else:
        # Auto-save
        auto_path = Path("requests") / f"{script_path.stem}_dialogue.yaml"
        auto_path.parent.mkdir(parents=True, exist_ok=True)
        auto_path.write_text(yaml_output, encoding="utf-8")
        print()
        print(f"✅ Auto-saved to: {auto_path}")


if __name__ == "__main__":
    main()
