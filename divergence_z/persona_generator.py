#!/usr/bin/env python3
"""
Persona Generator v3.0
Z-Axis Translation System — Automatic Persona YAML Generation

v3.0 Changes:
- age_context: 背景のみ、表出パターンは emotion_states へ分離
- emotion_states: z_mode, z_leak 追加
- age_expression_rules: 年齢カテゴリ別の表出ルール追加
- surface_markers_hint: z_leak マーカー対応

Usage:
    python persona_generator.py --name "牧瀬紅莉栖" --source "Steins;Gate" --desc "ツンデレの天才科学者"
    python persona_generator.py --name "ナツキ・スバル" --source "Re:ゼロ" --desc "死に戻りの少年" --search
"""

import argparse
import json
import os
import sys
from anthropic import Anthropic
from dotenv import load_dotenv
load_dotenv()

# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_MODEL = os.getenv("PERSONA_GENERATOR_MODEL", os.getenv("CLAUDE_MODEL", "claude-opus-4-5-20251101"))

SYSTEM_PROMPT = """You are a Persona Dynamics Designer for the Z-Axis Translation System v3.0.

Task: Generate a persona YAML that captures a character's internal psychological 
structure for emotion-preserving translation.

## YAML SCHEMA v3.0 (REQUIRED SECTIONS)

### 1. META
```yaml
meta:
  version: "3.0"
  generated_by: "persona_generator"
  character_id: "unique_id"  # lowercase, underscores
```

### 2. BASIC INFO (persona)
```yaml
persona:
  name: "キャラ名"
  name_en: "English Name"
  source: "作品名"
  type: "キャラクタータイプ（例：ツンデレ × 天才科学者）"
  summary: "1-2文の概要"
```

### 3. AGE & MATURITY
```yaml
age:
  chronological: 17           # 実年齢
  mental_maturity: "teen_young"  # teen_young / teen_mature / adult
  age_context: "背景説明のみ。表出パターンはemotion_statesへ"
```

**CRITICAL RULE for age_context:**
- ✅ DO: "引きこもり経験あり、社会的成熟が遅れている"
- ✅ DO: "天才児として育ち、感情表現が不得手"
- ❌ DON'T: "感情崩壊時は言葉が出てこなくなる" ← これは emotion_states へ
- ❌ DON'T: "怒ると言葉が荒くなる" ← これは emotion_states へ

### 4. LANGUAGE (人称・呼称)
```yaml
language:
  first_person: "俺 / 私 / 僕 etc."
  second_person_user: "お前 / あなた / 君 etc."
  second_person_other: "お前ら / みんな etc."
  address_style: "敬語 / タメ口 / 混合"
  dialect: "標準語 / 関西弁 / etc."
  speech_quirks:
    - "口癖や特徴的な言い回し"
  notes: "追加の言語的特徴"
```

### 5. CONFLICT_AXES (内部葛藤軸)
Each axis MUST be phrased as "A vs B":
```yaml
conflict_axes:
  - axis: "Side A vs Side B"
    side_a: "表層の欲求"
    side_b: "抑圧された欲求"
    weight: 0.8  # 0.0-1.0
    notes: "発動条件"
```

### 6. BIAS (表出パターン)
```yaml
bias:
  expression_pattern: "パターン名（例：Tsun-Dere-Overwrite）"
  default_mode: "デフォルトの感情状態"
  pattern: "感情が表出する流れ"
  rule: "行動ルール"
  tendencies:
    - "観測可能な傾向"
```

### 7. WEAKNESS (弱点)
```yaml
weakness:
  primary: "主要な弱点"
  secondary: "二次的な弱点"
  tertiary: "三次的な弱点"
  fear: "根底にある恐れ"
  notes: "弱点の発現パターン"
```

### 8. AGE_EXPRESSION_RULES (年齢別表出ルール) — NEW in v3.0
```yaml
age_expression_rules:
  category: "teen_young"  # teen_young / teen_mature / adult
  
  high_z_patterns:  # z >= 0.7 時の崩れ方
    vocabulary: "平易 / 維持 / 高度"
    structure: "断言より感情の揺れ / 抑制しようとして漏れる / 分析的な崩れ"
    markers:
      - "繰り返し、途切れが多い"
      - "論理の残骸が残る"
      
  low_z_patterns:  # z <= 0.3 時
    vocabulary: "通常"
    structure: "安定"
```

### 9. EMOTION_STATES (状態別Z軸制約) — CRITICAL FOR TRANSLATION, UPDATED v3.0
```yaml
emotion_states:
  - state: "状態名（例：collapse, rage, shame）"
    z_intensity: "low / medium / high"
    z_mode: "collapse / rage / numb / plea / shame / leak"  # NEW
    description: "この状態が発生する条件"
    
    surface_markers_hint:
      hesitation: 0-4
      stutter_count: 0-4
      negation_first: true/false
      overwrite: "none / optional / required"
      residual: "none / optional / required"
      tone: "声の質の説明"
      
    z_leak:  # NEW - 表出マーカーリスト
      - "stutter"       # 言い淀み「I— I...」
      - "ellipsis"      # 途切れ「...」
      - "repetition"    # 繰り返し「nobody— nobody」
      - "negation_first" # 否定先行「N-not that...」
      - "overwrite"     # 上書き「I mean—」
      - "trailing"      # 尻すぼみ「...I guess」
      - "self_negation" # 自己否定
```

**z_mode definitions:**
| z_mode | 意味 | 翻訳への影響 |
|--------|------|-------------|
| collapse | 崩壊、言葉が出ない | 途切れ、繰り返し、文が壊れる |
| rage | 怒り、言葉が荒れる | 流暢だが語彙が荒い、攻撃的 |
| numb | 麻痺、感情遮断 | 平坦、短文、感情が消える |
| plea | 懇願、すがる | 繰り返し、「お願い」系語彙 |
| shame | 恥、自己嫌悪 | 自己否定、言い淀み |
| leak | 漏出（ツンデレ等） | 否定→本音が漏れる |

### 10. EXAMPLE_LINES (Few-shot用) — 2-4 examples only
```yaml
example_lines:
  - situation: "コンテキスト"
    line: "実際の台詞（原語）"
    tags: [emotion_state, trigger]
    z_intensity: "low / medium / high"
    z_mode: "対応するz_mode"  # NEW
```

### 11. TRIGGERS (Z軸変動トリガー)
```yaml
triggers:
  - trigger: "反応を引き起こすもの"
    reaction: "z_spike / z_drop / z_boost / z_stable"
    z_delta: "+0.3 / -0.2 etc."
    z_mode_shift: "シフト先のz_mode（optional）"  # NEW
    surface_effect: "発話への影響"
    example_response: "サンプル台詞"
```

### 12. ARC_DEFAULTS (典型的なアーク) — NEW in v3.0
```yaml
arc_defaults:
  typical_arc_targets:
    - "speaker"       # 個人の感情変化
    - "relationship"  # 関係性の変化
  common_arc_patterns:
    - arc_id: "パターン名"
      phases: ["rise", "break", "bottom", "recovery"]
      notes: "このキャラに典型的なアークパターン"
```

## CONSTRAINTS
- Conflicts MUST be phrased as "A vs B"
- age_context MUST NOT contain expression patterns (those go to emotion_states)
- emotion_states MUST include z_mode and z_leak for v3.0 compatibility
- emotion_states MUST cover ALL z_modes that apply to this character — do NOT limit to 3-4 states if more are relevant
- Each emotion_state MUST have corresponding z_leak markers
- example_lines should be 2-4 max
- The persona must feel internally consistent
- Output VALID YAML only. No explanation before or after.
- Start with "# =====" header comment
- Include meta section with version: "3.0"

## IMPORTANT NOTES
- Focus on TRANSLATABLE features (how speech changes with emotion)
- z_mode determines the TYPE of breakdown
- z_leak determines the MARKERS of that breakdown
- Characters who DON'T hesitate should have hesitation: 0
- Characters who use denial should have negation_first: true
- age_expression_rules should match the character's mental_maturity"""

# =============================================================================
# FUNCTIONS
# =============================================================================

def build_user_prompt(name: str, source: str, description: str, search_context: str = "") -> str:
    """Build the user prompt for persona generation."""
    prompt = f"""Generate a v3.0 persona YAML for:

Name: {name}
Source: {source}
Description: {description}
"""
    
    if search_context:
        prompt += f"""
## Additional Context (from research):
{search_context}
"""
    
    prompt += """
Output ONLY valid YAML. No explanation.
Remember: age_context should ONLY contain background info, NOT expression patterns."""
    
    return prompt


def generate_persona(name: str, source: str, description: str, 
                     search_context: str = "", model: str = DEFAULT_MODEL) -> str:
    """Generate persona YAML using Claude API."""
    
    client = Anthropic()
    
    user_prompt = build_user_prompt(name, source, description, search_context)
    
    print(f"🐯 Generating persona v3.0 for: {name} ({source})")
    print(f"   Model: {model}")
    print()
    
    response = client.messages.create(
        model=model,
        max_tokens=6000,  # Increased for v3.0 larger output
        system=SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": user_prompt}
        ]
    )
    
    yaml_content = response.content[0].text
    
    # Clean up if wrapped in code blocks
    if yaml_content.startswith("```yaml"):
        yaml_content = yaml_content[7:]
    if yaml_content.startswith("```"):
        yaml_content = yaml_content[3:]
    if yaml_content.endswith("```"):
        yaml_content = yaml_content[:-3]
    
    return yaml_content.strip()


def validate_v3_persona(yaml_content: str) -> tuple[bool, list[str]]:
    """
    Validate that the generated YAML conforms to v3.0 schema.
    Returns (is_valid, list_of_issues).
    """
    import yaml as yaml_lib
    
    issues = []
    
    try:
        data = yaml_lib.safe_load(yaml_content)
    except yaml_lib.YAMLError as e:
        return False, [f"YAML parse error: {e}"]
    
    # Check meta version
    if data.get("meta", {}).get("version") != "3.0":
        issues.append("meta.version should be '3.0'")
    
    # Check age structure
    age_data = data.get("age", {})
    if "mental_maturity" not in age_data:
        issues.append("age.mental_maturity is required in v3.0")
    
    # Check emotion_states for z_mode and z_leak
    emotion_states = data.get("emotion_states", [])
    for i, state in enumerate(emotion_states):
        if "z_mode" not in state:
            issues.append(f"emotion_states[{i}].z_mode is required in v3.0")
        if "z_leak" not in state:
            issues.append(f"emotion_states[{i}].z_leak is required in v3.0")
    
    # Check age_expression_rules exists
    if "age_expression_rules" not in data:
        issues.append("age_expression_rules is required in v3.0")
    
    return len(issues) == 0, issues


def save_persona(yaml_content: str, name: str, output_dir: str = "personas") -> str:
    """Save generated persona to file."""
    
    os.makedirs(output_dir, exist_ok=True)
    
    # Generate safe filename
    safe_name = name.lower().replace(" ", "_").replace("・", "_")
    safe_name = "".join(c for c in safe_name if c.isalnum() or c == "_")
    
    filename = f"{safe_name}_v3.yaml"
    filepath = os.path.join(output_dir, filename)
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(yaml_content)
    
    return filepath


def main():
    parser = argparse.ArgumentParser(
        description="Generate persona YAML v3.0 for Z-Axis Translation System"
    )
    parser.add_argument("--name", required=True, help="Character name")
    parser.add_argument("--source", required=True, help="Source work (anime, game, etc.)")
    parser.add_argument("--desc", required=True, help="Brief character description")
    parser.add_argument("--context", default="", help="Additional context or search results")
    parser.add_argument("--context-file", help="File containing additional context")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Model to use")
    parser.add_argument("--output-dir", default="personas", help="Output directory")
    parser.add_argument("--print-only", action="store_true", help="Print YAML without saving")
    parser.add_argument("--validate", action="store_true", help="Validate v3.0 schema compliance")
    
    args = parser.parse_args()
    
    # Load context from file if provided
    context = args.context
    if args.context_file:
        with open(args.context_file, "r", encoding="utf-8") as f:
            context = f.read()
    
    # Generate persona
    yaml_content = generate_persona(
        name=args.name,
        source=args.source,
        description=args.desc,
        search_context=context,
        model=args.model
    )
    
    # Validate if requested
    if args.validate:
        is_valid, issues = validate_v3_persona(yaml_content)
        if not is_valid:
            print("⚠️  v3.0 Schema Validation Issues:")
            for issue in issues:
                print(f"   - {issue}")
            print()
    
    if args.print_only:
        print(yaml_content)
    else:
        filepath = save_persona(yaml_content, args.name, args.output_dir)
        print(f"✅ Persona v3.0 saved to: {filepath}")
        print()
        print("=" * 60)
        print(yaml_content)


if __name__ == "__main__":
    main()