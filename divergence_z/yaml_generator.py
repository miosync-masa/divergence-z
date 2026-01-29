#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YAML Generator v3.0 for Z-Axis Translation
ペルソナ + 原文 + シーンヒントから翻訳リクエストYAMLを自動生成

v3.0 Changes:
- z_mode support (collapse/rage/numb/plea/shame/leak/none)
- z_leak_hint for surface marker guidance
- Better persona emotion_states matching

Usage:
    python yaml_generator.py \
      --persona personas/kurisu_v3.yaml \
      --line "別に...あんたのためじゃないから。" \
      --hint "独り言、岡部が他の女と話してて嫉妬"

    python yaml_generator.py \
      --persona personas/subaru_v3.yaml \
      --line "俺は、俺が大嫌いだ。" \
      --hint "白鯨戦後、精神的限界、自己嫌悪"

    # 出力ファイル指定
    python yaml_generator.py \
      --persona personas/kurisu_v3.yaml \
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
# JSON Schema for Generated YAML v3.0
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
            "description": "Current emotional state of the speaker in Japanese (match persona's emotion_states if possible)",
            "maxLength": 50,
        },
        "z_axis_intensity": {
            "type": "string",
            "enum": ["low", "medium", "high"],
            "description": "Emotional intensity level",
        },
        "z_mode": {
            "type": "string",
            "enum": ["collapse", "rage", "numb", "plea", "shame", "leak", "none"],
            "description": "Type of emotional breakdown/expression pattern",
        },
        "z_leak_hint": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": ["stutter", "ellipsis", "repetition", "negation_first", "overwrite", "trailing", "self_negation"],
            },
            "description": "Suggested surface markers based on the line's characteristics",
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
        "z_mode",
        "z_leak_hint",
        "listener_type_hint",
        "reasoning",
    ],
}


# =============================================================================
# System Prompt v3.0
# =============================================================================

SYSTEM_PROMPT = """You are a YAML Generator for the Z-Axis Translation System v3.0.

Task: Given a character persona, a target line, and a scene hint, generate the full context needed for emotion-preserving translation.

## YOUR JOB
1. Analyze the persona's conflict axes, biases, and emotion_states
2. Understand the target line's emotional content
3. Expand the scene hint into a rich context
4. Infer the relationship and listener type
5. Estimate the Z-axis intensity AND z_mode

## z_mode DEFINITIONS (CRITICAL for v3.0)

| z_mode | 意味 | 発話パターン | 典型的な状況 |
|--------|------|-------------|-------------|
| collapse | 崩壊、言葉が出ない | 途切れ、繰り返し、文が壊れる | 絶望、トラウマ、限界突破 |
| rage | 怒り、言葉が荒れる | 流暢だが語彙が荒い、攻撃的 | 怒り、理不尽への反発 |
| numb | 麻痺、感情遮断 | 平坦、短文、感情が消える | 諦め、感情の枯渇 |
| plea | 懇願、すがる | 繰り返し、「お願い」系語彙 | 助けを求める、懇願 |
| shame | 恥、自己嫌悪 | 自己否定、言い淀み | 自己嫌悪、後悔 |
| leak | 漏出（ツンデレ等） | 否定→本音が漏れる | 照れ隠し、本音隠蔽 |
| none | 通常状態 | 安定した発話 | 日常会話 |

## z_leak MARKERS
- stutter: 言い淀み「I— I...」「俺は、俺は...」
- ellipsis: 途切れ「...」
- repetition: 繰り返し「why, why, why」「誰も、誰も」
- negation_first: 否定先行「N-not that...」「別に...」
- overwrite: 自己訂正「I mean—」「っていうか」
- trailing: 尻すぼみ「...I guess」「...かな」
- self_negation: 自己否定「俺が悪い」「I'm worthless」

## OUTPUT REQUIREMENTS

### scene
- Location, time, atmosphere
- Example: "ラボ、深夜、二人きり" or "白鯨戦後、精神的限界"

### relationship
- Format: "Speaker → Listener（role, emotional state, situation）"
- If monologue/self-talk: "Speaker → 自分自身（独り言・自己説得）"
- Example: "紅莉栖 → 岡部（恋人未満・ツンデレ・照れ隠し）"
- Example: "スバル → 自分自身（独白・自己嫌悪・精神崩壊中）"

### context_block
- Use [状況] tags for scene setting
- Include dialogue lines leading up to the target line
- Show the emotional buildup
- Format like a script with [CharacterName] lines

### emotion_state
- The speaker's internal emotional state in Japanese
- **CRITICAL**: Match with persona's emotion_states.state if possible
- Examples: "shame_self_hatred", "collapse_despair", "leak_tsundere"

### z_axis_intensity
- low: Calm, controlled, surface-level emotion
- medium: Some emotional leakage, conflict visible
- high: Overflow, direct expression, critical moment

### z_mode
- **CRITICAL**: Check persona's emotion_states for matching z_mode
- If the line shows self-hatred → shame
- If the line shows begging/pleading → plea
- If the line shows emotional breakdown → collapse
- If the line shows tsundere denial → leak

### z_leak_hint
- Select markers that appear IN THE ORIGINAL LINE
- 「俺は、俺は...」 → ["repetition", "ellipsis"]
- 「別に...あんたのためじゃない」 → ["negation_first", "ellipsis"]
- 「俺が悪いんだ」 → ["self_negation"]

### listener_type_hint
- other_specific: Speaking TO a specific person present
- other_general: Speaking to general audience
- self: Monologue, self-talk, self-persuasion (NO ONE is listening)
- absent: Talking ABOUT someone not present

## CRITICAL RULES
1. If hint mentions "独り言", "一人で", "誰も聞いていない" → listener_type_hint = "self"
2. If hint mentions "自己嫌悪", "大嫌い" → z_mode = "shame"
3. If hint mentions "絶望", "限界", "崩壊" → z_mode = "collapse"
4. If hint mentions "照れ", "ツンデレ" → z_mode = "leak"
5. Match emotion_state with persona's defined states when possible
6. z_leak_hint should reflect markers VISIBLE in the target line
7. Output in Japanese (except enum fields)

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


def extract_persona_info(persona_yaml: str) -> Dict[str, Any]:
    """Extract key info from persona for display."""
    try:
        data = yaml.safe_load(persona_yaml)
        persona = data.get("persona", {})
        return {
            "name": persona.get("name", "Unknown"),
            "version": data.get("meta", {}).get("version", "unknown"),
            "emotion_states": [s.get("state", "") for s in data.get("emotion_states", [])],
        }
    except Exception:
        return {"name": "Unknown", "version": "unknown", "emotion_states": []}


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

Generate the complete context for Z-Axis translation v3.0.
Pay special attention to:
1. Match z_mode with persona's emotion_states
2. Extract z_leak markers visible in the target line
3. Consider the emotional context from the hint"""

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
                "name": "YAMLGeneration_v3",
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
    """Build the final YAML structure (v3.0)."""
    
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
        # v3.0 additions
        "z_mode": generated["z_mode"],
        "z_leak_hint": generated["z_leak_hint"],
        "emotion_state": generated["emotion_state"],
    }
    
    # Add notes with generation info
    z_leak_str = ", ".join(generated["z_leak_hint"]) if generated["z_leak_hint"] else "none"
    yaml_content["notes"] = f"""Auto-generated by yaml_generator.py v3.0
listener_type_hint: {generated['listener_type_hint']}
z_mode: {generated['z_mode']}
z_leak_hint: [{z_leak_str}]
reasoning: {generated['reasoning']}"""
    
    return yaml_content


def format_yaml_output(yaml_content: Dict[str, Any]) -> str:
    """Format YAML with nice formatting (v3.0)."""
    
    output_lines = []
    
    # Header comment
    output_lines.append("# ============================================")
    output_lines.append("# Auto-generated by yaml_generator.py v3.0")
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
        escaped_line = yaml_content["target_line"].replace('"', '\\"')
        output_lines.append(f'target_line: "{escaped_line}"')
    
    output_lines.append(f'target_lang: "{yaml_content["target_lang"]}"')
    output_lines.append(f'z_axis_intensity: "{yaml_content["z_axis_intensity"]}"')
    output_lines.append("")
    
    # v3.0 additions
    output_lines.append("# === v3.0 fields ===")
    output_lines.append(f'z_mode: "{yaml_content["z_mode"]}"')
    
    # z_leak_hint as array
    z_leak = yaml_content.get("z_leak_hint", [])
    if z_leak:
        output_lines.append("z_leak_hint:")
        for marker in z_leak:
            output_lines.append(f'  - "{marker}"')
    else:
        output_lines.append("z_leak_hint: []")
    
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
        description="YAML Generator v3.0 for Z-Axis Translation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Tsundere line (leak mode)
  python yaml_generator.py \\
    --persona personas/kurisu_v3.yaml \\
    --line "別に...あんたのためじゃないから。" \\
    --hint "独り言、岡部が他の女と話してて嫉妬"

  # Self-hatred line (shame mode)
  python yaml_generator.py \\
    --persona personas/subaru_v3.yaml \\
    --line "俺は、俺が大嫌いだ。" \\
    --hint "白鯨戦後、精神的限界、自己嫌悪"

  # Plea line
  python yaml_generator.py \\
    --persona personas/subaru_v3.yaml \\
    --line "頼む、頼むから信じてくれ..." \\
    --hint "エミリアに懇願、秘密を言えない"
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
    
    # Extract persona info for display
    persona_info = extract_persona_info(persona_yaml)
    print(f"   Character: {persona_info['name']}")
    print(f"   Version: {persona_info['version']}")
    if persona_info['emotion_states']:
        print(f"   Emotion states: {', '.join(persona_info['emotion_states'][:5])}...")
    
    # Generate
    print()
    print(f"🔮 Generating YAML v3.0 for: \"{args.line[:40]}...\"")
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
    print("[Generated YAML v3.0]")
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
    print("[Generation Analysis v3.0]")
    print("=" * 60)
    print(f"z_mode: {generated['z_mode']}")
    print(f"z_leak_hint: {generated['z_leak_hint']}")
    print(f"listener_type_hint: {generated['listener_type_hint']}")
    print(f"reasoning: {generated['reasoning']}")


if __name__ == "__main__":
    main()
