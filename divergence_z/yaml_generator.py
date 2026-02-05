#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YAML Generator v3.1 for Z-Axis Translation
ペルソナ（複数対応） + 原文 + シーンヒントから翻訳リクエストYAMLを自動生成

v3.1 Changes:
- Multiple persona support (--persona accepts 1-N files)
- LLM auto-detects speaker/listener/others from context
- speaker_id / listener_id / other_ids in output
- Backward compatible with v3.0 single-persona usage

v3.0 Changes:
- z_mode support (collapse/rage/numb/plea/shame/leak/none)
- z_leak_hint for surface marker guidance
- Better persona emotion_states matching

Usage:
    # Single persona (backward compatible)
    python yaml_generator.py \\
      --persona personas/kurisu_v3.yaml \\
      --line "別に...あんたのためじゃないから。" \\
      --hint "独り言、岡部が他の女と話してて嫉妬"

    # Multiple personas (v3.1)
    python yaml_generator.py \\
      --persona personas/kurisu_v3.yaml personas/okabe_v3.yaml \\
      --line "別に...あんたのためじゃないから。" \\
      --hint "岡部に好きだろと言われた"

    # Three personas (speaker + listener + bystander)
    python yaml_generator.py \\
      --persona personas/kurisu_v3.yaml personas/okabe_v3.yaml personas/mayuri_v3.yaml \\
      --line "別に...あんたのためじゃないから。" \\
      --hint "まゆりが見てる前で岡部に好きだろと言われた"

    # 出力ファイル指定
    python yaml_generator.py \\
      --persona personas/kurisu_v3.yaml personas/okabe_v3.yaml \\
      --line "まあ…別にいいんだけどさ…うん" \\
      --hint "岡部に好きだろと言われた" \\
      --output requests/kurisu_generated.yaml
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1")


# =============================================================================
# JSON Schema for Generated YAML v3.1
# =============================================================================

YAML_GENERATION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "speaker_id": {
            "type": "string",
            "description": "character_id of the speaker (from persona meta.character_id or persona.name)",
            "maxLength": 100,
        },
        "listener_id": {
            "type": ["string", "null"],
            "description": "character_id of the primary listener, or null if self/absent",
            "maxLength": 100,
        },
        "other_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "character_ids of other personas present but not directly addressed",
        },
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
            "maxLength": 1500,
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
        "interaction_dynamics": {
            "type": ["string", "null"],
            "description": "How the presence of other personas affects the speaker's behavior (null if single persona)",
            "maxLength": 300,
        },
        "reasoning": {
            "type": "string",
            "description": "Brief explanation of why these values were chosen",
            "maxLength": 300,
        },
    },
    "required": [
        "speaker_id",
        "listener_id",
        "other_ids",
        "scene",
        "relationship",
        "context_block",
        "emotion_state",
        "z_axis_intensity",
        "z_mode",
        "z_leak_hint",
        "listener_type_hint",
        "interaction_dynamics",
        "reasoning",
    ],
}


# =============================================================================
# System Prompt v3.1
# =============================================================================

SYSTEM_PROMPT = """You are a YAML Generator for the Z-Axis Translation System v3.1.

Task: Given one or more character personas, a target line, and a scene hint, generate the full context needed for emotion-preserving translation.

## YOUR JOB
1. Identify WHO is speaking this line (speaker_id)
2. Identify WHO is being spoken to (listener_id) — may be null for self-talk
3. Identify WHO ELSE is present (other_ids) — bystanders who affect behavior
4. Analyze how the presence of multiple characters affects the speaker's Z-axis
5. Generate the full context

## MULTI-PERSONA ANALYSIS (v3.1)
When multiple personas are provided:
- Determine speaker from the target line + hint context
- The listener's persona affects: relationship inference, trigger detection
- Bystanders affect: z_axis_intensity (embarrassment amplification), z_mode shifts
- Example: Kurisu saying "別に" to Okabe is z_mode=leak.
  But with Mayuri watching → z_axis_intensity increases, stutter_count may increase

## interaction_dynamics
When multiple personas are present, describe HOW they affect the speaker:
- "まゆりの存在が紅莉栖の照れを増幅。普段より否定が強くなる"
- "岡部のトリガー（助手呼び）が発火中、レムの存在は影響なし"
- null if only one persona provided

## ROLE IDENTIFICATION RULES
1. The speaker is the character whose voice matches the target line
2. If hint mentions "X が Y に言う" → X is speaker, Y is listener
3. If hint mentions "Z が見てる" → Z is in other_ids
4. If ambiguous, use the line's speech patterns (first_person, quirks) to identify speaker
5. Use character_id from persona's meta section, or persona.name if no character_id

## z_mode DEFINITIONS (CRITICAL)

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

### speaker_id / listener_id / other_ids
- Use character_id from meta section, or name if unavailable
- listener_id = null when listener_type_hint is "self" or "absent"
- other_ids = [] when no bystanders

### scene
- Location, time, atmosphere
- Include WHO is present

### relationship
- Format: "Speaker → Listener（role, emotional state, situation）"
- If bystanders present: mention their influence

### context_block
- Use [状況] tags for scene setting
- Include dialogue lines from ALL present characters leading up to target
- Show how bystanders react or influence the scene
- maxLength increased to 1500 for multi-persona scenes

### emotion_state
- The SPEAKER's internal emotional state
- **CRITICAL**: Match with speaker persona's emotion_states.state if possible

### listener_type_hint
- other_specific: Speaking TO a specific person present
- other_general: Speaking to general audience
- self: Monologue, self-talk, self-persuasion
- absent: Talking ABOUT someone not present

## CRITICAL RULES
1. ALWAYS identify speaker_id, listener_id, other_ids first
2. Use listener's persona to enrich relationship analysis
3. Bystander personas can amplify z_axis_intensity
4. Check ALL personas' triggers for cross-character interactions
5. If hint mentions "独り言", "一人で" → listener_type_hint = "self", listener_id = null
6. Match emotion_state with speaker's persona emotion_states when possible
7. z_leak_hint should reflect markers VISIBLE in the target line
8. Output in Japanese (except enum fields)
9. When only 1 persona provided, behave identically to v3.0

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
        meta = data.get("meta", {})
        return {
            "name": persona.get("name", "Unknown"),
            "character_id": meta.get("character_id", persona.get("name", "unknown")),
            "version": meta.get("version", "unknown"),
            "emotion_states": [s.get("state", "") for s in data.get("emotion_states", [])],
        }
    except Exception:
        return {"name": "Unknown", "character_id": "unknown", "version": "unknown", "emotion_states": []}


def load_all_personas(persona_paths: List[str]) -> List[Dict[str, Any]]:
    """Load all persona files and return structured data."""
    personas = []
    for path in persona_paths:
        yaml_str = load_persona(path)
        info = extract_persona_info(yaml_str)
        personas.append({
            "path": path,
            "yaml_str": yaml_str,
            "info": info,
        })
    return personas


def format_personas_for_prompt(personas: List[Dict[str, Any]]) -> str:
    """Format all personas into a single prompt block."""
    if len(personas) == 1:
        return f"[PERSONA YAML]\n{personas[0]['yaml_str']}"
    
    blocks = []
    for i, p in enumerate(personas, 1):
        name = p["info"]["name"]
        char_id = p["info"]["character_id"]
        blocks.append(
            f"[PERSONA {i}: {name} (id: {char_id})]\n"
            f"{p['yaml_str']}"
        )
    return "\n\n".join(blocks)


def generate_yaml_content(
    client: OpenAI,
    personas: List[Dict[str, Any]],
    target_line: str,
    scene_hint: str,
    target_lang: str = "en",
    model: str = DEFAULT_MODEL,
) -> Dict[str, Any]:
    """Generate YAML content using LLM."""
    
    personas_block = format_personas_for_prompt(personas)
    
    n_personas = len(personas)
    multi_note = ""
    if n_personas > 1:
        names = [p["info"]["name"] for p in personas]
        multi_note = f"""
NOTE: {n_personas} personas provided: {', '.join(names)}
Determine who is SPEAKING, who is LISTENING, and who else is PRESENT.
Consider how each persona's presence affects the speaker's Z-axis."""
    
    user_prompt = f"""{personas_block}

[TARGET LINE]
{target_line}

[SCENE HINT]
{scene_hint}

[TARGET LANGUAGE]
{target_lang}
{multi_note}
Generate the complete context for Z-Axis translation v3.1.
Pay special attention to:
1. Identify speaker / listener / others from context
2. Match z_mode with speaker's persona emotion_states
3. Extract z_leak markers visible in the target line
4. Consider how other personas' presence affects the speaker"""

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
                "name": "YAMLGeneration_v31",
                "schema": YAML_GENERATION_SCHEMA,
                "strict": True,
            },
        },
    )
    
    result = json.loads(response.choices[0].message.content)
    return result


def build_final_yaml(
    persona_paths: List[str],
    target_line: str,
    target_lang: str,
    generated: Dict[str, Any],
) -> Dict[str, Any]:
    """Build the final YAML structure (v3.1)."""
    
    # Convert to relative paths
    def to_relative(p: str) -> str:
        if p.startswith("personas/"):
            return p
        elif "/" in p:
            return f"personas/{Path(p).name}"
        return p
    
    persona_files = [to_relative(p) for p in persona_paths]
    
    yaml_content = {
        # v3.1: persona_file is now a list (but single element stays string for compat)
        "persona_file": persona_files[0] if len(persona_files) == 1 else persona_files,
        # v3.1: role identification
        "speaker_id": generated["speaker_id"],
        "listener_id": generated["listener_id"],
        "other_ids": generated["other_ids"],
        # scene & context
        "scene": generated["scene"],
        "relationship": generated["relationship"],
        "context_block": generated["context_block"],
        "target_line": target_line,
        "target_lang": target_lang,
        "z_axis_intensity": generated["z_axis_intensity"],
        # v3.0 fields
        "z_mode": generated["z_mode"],
        "z_leak_hint": generated["z_leak_hint"],
        "emotion_state": generated["emotion_state"],
    }
    
    # Build notes
    z_leak_str = ", ".join(generated["z_leak_hint"]) if generated["z_leak_hint"] else "none"
    interaction = generated.get("interaction_dynamics") or "N/A (single persona)"
    
    yaml_content["notes"] = f"""Auto-generated by yaml_generator.py v3.1
speaker_id: {generated['speaker_id']}
listener_id: {generated['listener_id']}
other_ids: {generated['other_ids']}
listener_type_hint: {generated['listener_type_hint']}
z_mode: {generated['z_mode']}
z_leak_hint: [{z_leak_str}]
interaction_dynamics: {interaction}
reasoning: {generated['reasoning']}"""
    
    return yaml_content


def format_yaml_output(yaml_content: Dict[str, Any]) -> str:
    """Format YAML with nice formatting (v3.1)."""
    
    output_lines = []
    
    # Header comment
    output_lines.append("# ============================================")
    output_lines.append("# Auto-generated by yaml_generator.py v3.1")
    output_lines.append("# ============================================")
    output_lines.append("")
    
    # persona_file (single string or list)
    pf = yaml_content["persona_file"]
    if isinstance(pf, list):
        output_lines.append("persona_file:")
        for f in pf:
            output_lines.append(f'  - "{f}"')
    else:
        output_lines.append(f'persona_file: "{pf}"')
    output_lines.append("")
    
    # v3.1: role identification
    output_lines.append("# === v3.1 role identification ===")
    output_lines.append(f'speaker_id: "{yaml_content["speaker_id"]}"')
    if yaml_content["listener_id"]:
        output_lines.append(f'listener_id: "{yaml_content["listener_id"]}"')
    else:
        output_lines.append("listener_id: null")
    other_ids = yaml_content.get("other_ids", [])
    if other_ids:
        output_lines.append("other_ids:")
        for oid in other_ids:
            output_lines.append(f'  - "{oid}"')
    else:
        output_lines.append("other_ids: []")
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
    
    # v3.0 fields
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
        description="YAML Generator v3.1 for Z-Axis Translation (Multi-Persona)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single persona (backward compatible with v3.0)
  python yaml_generator.py \\
    --persona personas/kurisu_v3.yaml \\
    --line "別に...あんたのためじゃないから。" \\
    --hint "独り言、岡部が他の女と話してて嫉妬"

  # Two personas (speaker + listener)
  python yaml_generator.py \\
    --persona personas/kurisu_v3.yaml personas/okabe_v3.yaml \\
    --line "別に...あんたのためじゃないから。" \\
    --hint "岡部に好きだろと言われた"

  # Three personas (speaker + listener + bystander)
  python yaml_generator.py \\
    --persona personas/kurisu_v3.yaml personas/okabe_v3.yaml personas/mayuri_v3.yaml \\
    --line "別に...あんたのためじゃないから。" \\
    --hint "まゆりが見てる前で岡部に好きだろと言われた"

  # Self-hatred (single persona)
  python yaml_generator.py \\
    --persona personas/subaru_v3.yaml \\
    --line "俺は、俺が大嫌いだ。" \\
    --hint "白鯨戦後、精神的限界、自己嫌悪"
        """
    )
    
    parser.add_argument("--persona", "-p", nargs="+", required=True,
                        help="Path(s) to persona YAML file(s). First is primary, but LLM auto-detects roles.")
    parser.add_argument("--line", "-l", required=True, help="Target line to translate")
    parser.add_argument("--hint", "-H", required=True, help="Scene hint (brief description)")
    parser.add_argument("--lang", default="en", help="Target language (default: en)")
    parser.add_argument("--output", "-o", help="Output YAML file path")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Model to use (default: {DEFAULT_MODEL})")
    parser.add_argument("--json", action="store_true", help="Also output raw JSON from LLM")
    
    args = parser.parse_args()
    
    # Load all personas
    print(f"🐯 Loading {len(args.persona)} persona(s):")
    personas = load_all_personas(args.persona)
    for i, p in enumerate(personas, 1):
        info = p["info"]
        print(f"   [{i}] {info['name']} (id: {info['character_id']}, v{info['version']})")
        if info['emotion_states']:
            print(f"       emotion_states: {', '.join(info['emotion_states'][:5])}...")
    
    # Generate
    print()
    print(f"🔮 Generating YAML v3.1 for: \"{args.line[:50]}...\"")
    print(f"   Hint: {args.hint}")
    print(f"   Model: {args.model}")
    if len(personas) > 1:
        print(f"   Mode: Multi-persona ({len(personas)} characters)")
    print()
    
    client = OpenAI()
    
    generated = generate_yaml_content(
        client=client,
        personas=personas,
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
        persona_paths=args.persona,
        target_line=args.line,
        target_lang=args.lang,
        generated=generated,
    )
    
    yaml_output = format_yaml_output(yaml_content)
    
    # Output
    print("=" * 60)
    print("[Generated YAML v3.1]")
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
    print("[Generation Analysis v3.1]")
    print("=" * 60)
    print(f"speaker_id: {generated['speaker_id']}")
    print(f"listener_id: {generated['listener_id']}")
    print(f"other_ids: {generated['other_ids']}")
    print(f"z_mode: {generated['z_mode']}")
    print(f"z_leak_hint: {generated['z_leak_hint']}")
    print(f"listener_type_hint: {generated['listener_type_hint']}")
    if generated.get('interaction_dynamics'):
        print(f"interaction_dynamics: {generated['interaction_dynamics']}")
    print(f"reasoning: {generated['reasoning']}")


if __name__ == "__main__":
    main()
