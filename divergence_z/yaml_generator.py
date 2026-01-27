#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YAML Generator for Z-Axis Translation
ペルソナ + 原文 + シーンヒントから翻訳リクエストYAMLを自動生成

Usage:
    python yaml_generator.py \
      --persona personas/kurisu_v2.yaml \
      --line "別に...あんたのためじゃないから。" \
      --hint "独り言、岡部が他の女と話してて嫉妬"

    python yaml_generator.py \
      --persona personas/レム_v2.yaml \
      --line "レムは、スバルくんを、愛しています。" \
      --hint "白鯨戦前夜、スバルが自己否定、レムの告白"

    # 出力ファイル指定
    python yaml_generator.py \
      --persona personas/kurisu_v2.yaml \
      --line "まあ…別にいいんだけどさ…うん" \
      --hint "岡部に好きだろと言われた" \
      --output requests/kurisu_generated.yaml
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1")


# =============================================================================
# JSON Schema for Generated YAML
# =============================================================================

YAML_GENERATION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "scene": {
            "type": "string",
            "description": "Scene description in Japanese (場所、時間、雰囲気)",
            "maxLength": 100,
        },
        "relationship": {
            "type": "string",
            "description": "Relationship description: Speaker → Listener (role, emotion, situation)",
            "maxLength": 150,
        },
        "context_block": {
            "type": "string",
            "description": "Detailed context with [状況] and dialogue lines leading up to target",
            "maxLength": 1000,
        },
        "emotion_state": {
            "type": "string",
            "description": "Current emotional state of the speaker in Japanese",
            "maxLength": 50,
        },
        "z_axis_intensity": {
            "type": "string",
            "enum": ["low", "medium", "high"],
            "description": "Emotional intensity level",
        },
        "listener_type_hint": {
            "type": "string",
            "enum": ["other_specific", "other_general", "self", "absent"],
            "description": "Who is the utterance directed at",
        },
        "reasoning": {
            "type": "string",
            "description": "Brief explanation of why these values were chosen",
            "maxLength": 200,
        },
    },
    "required": [
        "scene",
        "relationship",
        "context_block",
        "emotion_state",
        "z_axis_intensity",
        "listener_type_hint",
        "reasoning",
    ],
}


# =============================================================================
# System Prompt
# =============================================================================

SYSTEM_PROMPT = """You are a YAML Generator for the Z-Axis Translation System.

Task: Given a character persona, a target line, and a scene hint, generate the full context needed for emotion-preserving translation.

## YOUR JOB
1. Analyze the persona's conflict axes, biases, and emotion states
2. Understand the target line's emotional content
3. Expand the scene hint into a rich context
4. Infer the relationship and listener type
5. Estimate the Z-axis intensity

## OUTPUT REQUIREMENTS

### scene
- Location, time, atmosphere
- Example: "ラボ、深夜、二人きり" or "白鯨戦前夜、緊迫した雰囲気"

### relationship
- Format: "Speaker → Listener（role, emotional state, situation）"
- If monologue/self-talk: "Speaker → 自分自身（独り言・自己説得）"
- Example: "紅莉栖 → 岡部（恋人未満・ツンデレ・照れ隠し）"
- Example: "紅莉栖 → 自分自身（独り言・自己説得・誰も聞いていない）"

### context_block
- Use [状況] tags for scene setting
- Include dialogue lines leading up to the target line
- Show the emotional buildup
- Format like a script with [CharacterName] lines

### emotion_state
- The speaker's internal emotional state in Japanese
- Match with persona's emotion_states if possible
- Examples: "照れ隠し", "愛情告白", "自己説得", "嫉妬", "動揺"

### z_axis_intensity
- low: Calm, controlled, surface-level emotion
- medium: Some emotional leakage, conflict visible
- high: Overflow, direct expression, critical moment

### listener_type_hint
- other_specific: Speaking TO a specific person present
- other_general: Speaking to general audience
- self: Monologue, self-talk, self-persuasion (NO ONE is listening)
- absent: Talking ABOUT someone not present

## CRITICAL RULES
1. If hint mentions "独り言", "一人で", "誰も聞いていない" → listener_type_hint = "self"
2. If hint mentions "嫉妬" or jealousy → likely high intensity
3. Match emotion_state with persona's defined states when possible
4. context_block should feel like a natural scene setup
5. Output in Japanese (except listener_type_hint)

Output MUST be valid JSON matching the schema. No explanation outside JSON."""


# =============================================================================
# Functions
# =============================================================================

def load_persona(persona_path: str) -> str:
    """Load persona YAML as string."""
    path = Path(persona_path)
    if not path.exists():
        raise FileNotFoundError(f"Persona file not found: {path}")
    return path.read_text(encoding="utf-8")


def generate_yaml_content(
    client: OpenAI,
    persona_yaml: str,
    target_line: str,
    scene_hint: str,
    target_lang: str = "en",
    model: str = DEFAULT_MODEL,
) -> Dict[str, Any]:
    """Generate YAML content using LLM."""
    
    user_prompt = f"""[PERSONA YAML]
{persona_yaml}

[TARGET LINE]
{target_line}

[SCENE HINT]
{scene_hint}

[TARGET LANGUAGE]
{target_lang}

Generate the complete context for Z-Axis translation."""

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "YAMLGeneration",
                "schema": YAML_GENERATION_SCHEMA,
                "strict": True,
            },
        },
    )
    
    result = json.loads(response.choices[0].message.content)
    return result


def build_final_yaml(
    persona_path: str,
    target_line: str,
    target_lang: str,
    generated: Dict[str, Any],
) -> Dict[str, Any]:
    """Build the final YAML structure."""
    
    # Convert to relative path if possible
    persona_file = persona_path
    if persona_path.startswith("personas/"):
        persona_file = persona_path
    elif "/" in persona_path:
        persona_file = f"personas/{Path(persona_path).name}"
    
    yaml_content = {
        "persona_file": persona_file,
        "scene": generated["scene"],
        "relationship": generated["relationship"],
        "context_block": generated["context_block"],
        "target_line": target_line,
        "target_lang": target_lang,
        "z_axis_intensity": generated["z_axis_intensity"],
        "emotion_state": generated["emotion_state"],
    }
    
    # Add notes with generation info
    yaml_content["notes"] = f"""Auto-generated by yaml_generator.py
listener_type_hint: {generated['listener_type_hint']}
reasoning: {generated['reasoning']}"""
    
    return yaml_content


def format_yaml_output(yaml_content: Dict[str, Any]) -> str:
    """Format YAML with nice formatting."""
    
    # Custom formatting for better readability
    output_lines = []
    
    # Header comment
    output_lines.append("# ============================================")
    output_lines.append("# Auto-generated by yaml_generator.py")
    output_lines.append("# ============================================")
    output_lines.append("")
    
    # persona_file
    output_lines.append(f'persona_file: "{yaml_content["persona_file"]}"')
    output_lines.append("")
    
    # scene
    output_lines.append(f'scene: "{yaml_content["scene"]}"')
    
    # relationship
    output_lines.append(f'relationship: "{yaml_content["relationship"]}"')
    output_lines.append("")
    
    # context_block (multiline)
    output_lines.append("context_block: |")
    for line in yaml_content["context_block"].split("\n"):
        output_lines.append(f"  {line}")
    output_lines.append("")
    
    # target_line
    if "\n" in yaml_content["target_line"]:
        output_lines.append("target_line: |")
        for line in yaml_content["target_line"].split("\n"):
            output_lines.append(f"  {line}")
    else:
        output_lines.append(f'target_line: "{yaml_content["target_line"]}"')
    
    output_lines.append(f'target_lang: "{yaml_content["target_lang"]}"')
    output_lines.append(f'z_axis_intensity: "{yaml_content["z_axis_intensity"]}"')
    output_lines.append(f'emotion_state: "{yaml_content["emotion_state"]}"')
    output_lines.append("")
    
    # notes (multiline)
    output_lines.append("notes: |")
    for line in yaml_content["notes"].split("\n"):
        output_lines.append(f"  {line}")
    
    return "\n".join(output_lines)


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="YAML Generator for Z-Axis Translation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage
  python yaml_generator.py \\
    --persona personas/kurisu_v2.yaml \\
    --line "別に...あんたのためじゃないから。" \\
    --hint "独り言、岡部が他の女と話してて嫉妬"

  # With output file
  python yaml_generator.py \\
    --persona personas/レム_v2.yaml \\
    --line "レムは、スバルくんを、愛しています。" \\
    --hint "白鯨戦前夜、スバルが自己否定、レムの告白" \\
    --output requests/rem_generated.yaml
        """
    )
    
    parser.add_argument("--persona", "-p", required=True, help="Path to persona YAML file")
    parser.add_argument("--line", "-l", required=True, help="Target line to translate")
    parser.add_argument("--hint", "-H", required=True, help="Scene hint (brief description)")
    parser.add_argument("--lang", default="en", help="Target language (default: en)")
    parser.add_argument("--output", "-o", help="Output YAML file path")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Model to use (default: {DEFAULT_MODEL})")
    parser.add_argument("--json", action="store_true", help="Also output raw JSON from LLM")
    
    args = parser.parse_args()
    
    # Load persona
    print(f"🐯 Loading persona: {args.persona}")
    persona_yaml = load_persona(args.persona)
    
    # Generate
    print(f"🔮 Generating YAML for: \"{args.line[:30]}...\"")
    print(f"   Hint: {args.hint}")
    print(f"   Model: {args.model}")
    print()
    
    client = OpenAI()
    
    generated = generate_yaml_content(
        client=client,
        persona_yaml=persona_yaml,
        target_line=args.line,
        scene_hint=args.hint,
        target_lang=args.lang,
        model=args.model,
    )
    
    if args.json:
        print("=" * 60)
        print("[LLM Output (JSON)]")
        print("=" * 60)
        print(json.dumps(generated, ensure_ascii=False, indent=2))
        print()
    
    # Build final YAML
    yaml_content = build_final_yaml(
        persona_path=args.persona,
        target_line=args.line,
        target_lang=args.lang,
        generated=generated,
    )
    
    yaml_output = format_yaml_output(yaml_content)
    
    # Output
    print("=" * 60)
    print("[Generated YAML]")
    print("=" * 60)
    print(yaml_output)
    print()
    
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(yaml_output, encoding="utf-8")
        print(f"✅ Saved to: {args.output}")
    
    # Show reasoning
    print("=" * 60)
    print("[Generation Reasoning]")
    print("=" * 60)
    print(f"listener_type_hint: {generated['listener_type_hint']}")
    print(f"reasoning: {generated['reasoning']}")


if __name__ == "__main__":
    main()
