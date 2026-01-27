#!/usr/bin/env python3
"""
Persona Generator v2.0
Z-Axis Translation System — Automatic Persona YAML Generation

Usage:
    python persona_generator.py --name "牧瀬紅莉栖" --source "Steins;Gate" --desc "ツンデレの天才科学者"
    python persona_generator.py --name "ルフィ" --source "ONE PIECE" --desc "海賊王を目指す主人公" --search
"""

import argparse
import json
import os
import sys
from anthropic import Anthropic
from dotenv import load_dotenv
load_dotenv()  # .envを読み込む

# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_MODEL = "claude-sonnet-4-20250514"  # Claude model

SYSTEM_PROMPT = """You are a Persona Dynamics Designer for the Z-Axis Translation System.

Task: Generate a persona YAML that captures a character's internal psychological 
structure for emotion-preserving translation.

## YAML SCHEMA v2.0 (REQUIRED SECTIONS)

### 1. BASIC INFO (persona)
- name, name_en, source, type, summary

### 2. LANGUAGE (人称・呼称)
- first_person: How the character refers to themselves
- second_person_user: How they address the main person they talk to
- second_person_other: How they address others
- address_style: 敬語/タメ口/混合
- notes: Special speech patterns, dialect, etc.

### 3. CONFLICT_AXES (内部葛藤軸)
Each axis MUST be phrased as "A vs B":
- axis: "Side A vs Side B"
- side_a: What the character wants (surface)
- side_b: What conflicts with it (hidden/suppressed)
- weight: 0.0-1.0 (how strongly this conflict affects speech)
- notes: When/how this conflict activates

### 4. BIAS (表出パターン)
- expression_pattern: Named pattern (e.g., "Tsun-Dere-Overwrite", "Suppress-Threshold-Overflow")
- default_mode: Baseline emotional state
- pattern: Step-by-step flow of how emotions surface
- rule: Core behavioral rule
- tendencies: List of observable behaviors

### 5. WEAKNESS (弱点)
- primary, secondary, tertiary: Vulnerability hierarchy
- fear: Deep underlying fear
- notes: How weaknesses manifest

### 6. EMOTION_STATES (状態別Z軸制約) — CRITICAL FOR TRANSLATION
For each emotional state, define:
- state: Name of state
- z_intensity: low / medium / high
- description: When this state occurs
- surface_markers_hint:
    - hesitation: 0-4 (amount of "..." or pause markers)
    - stutter_count: 0-4 (amount of stuttering "I-I...")
    - negation_first: true/false (starts with denial?)
    - overwrite: none/optional/required (self-correction pattern)
    - residual: none/optional/required (trailing emotional leak)
    - tone: Description of voice quality

### 7. EXAMPLE_LINES (Few-shot用) — 2-4 examples only
- situation: Context
- line: Actual dialogue (in original language)
- tags: [emotion_state, trigger, etc.]
- z_intensity: low/medium/high

### 8. TRIGGERS (Z軸変動トリガー)
- trigger: What causes the reaction
- reaction: z_spike / z_drop / z_boost / z_stable
- z_delta: "+0.3" or "-0.2" etc.
- surface_effect: How it appears in speech
- example_response: Sample line when triggered

## CONSTRAINTS
- Conflicts MUST be phrased as "A vs B"
- Bias describes expression PATTERNS, not personality traits
- emotion_states MUST include surface_markers_hint for translation control
- example_lines should be 2-4 max (hints, not scripts)
- The persona must feel internally consistent
- Output VALID YAML only. No explanation before or after.
- Start with "# =====" header comment
- Include meta section with version: "2.0"

## IMPORTANT NOTES
- Focus on TRANSLATABLE features (how speech changes with emotion)
- surface_markers_hint directly controls translation output
- Characters who DON'T hesitate should have hesitation: 0
- Characters who use denial should have negation_first: true
- The pattern in bias should match emotion_states progression"""

# =============================================================================
# FUNCTIONS
# =============================================================================

def build_user_prompt(name: str, source: str, description: str, search_context: str = "") -> str:
    """Build the user prompt for persona generation."""
    prompt = f"""Generate a v2.0 persona YAML for:

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
Output ONLY valid YAML. No explanation."""
    
    return prompt


def generate_persona(name: str, source: str, description: str, 
                     search_context: str = "", model: str = DEFAULT_MODEL) -> str:
    """Generate persona YAML using Claude API."""
    
    client = Anthropic()
    
    user_prompt = build_user_prompt(name, source, description, search_context)
    
    print(f"🐯 Generating persona for: {name} ({source})")
    print(f"   Model: {model}")
    print()
    
    response = client.messages.create(
        model=model,
        max_tokens=4096,
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


def save_persona(yaml_content: str, name: str, output_dir: str = "personas") -> str:
    """Save generated persona to file."""
    
    # Create output directory if needed
    os.makedirs(output_dir, exist_ok=True)
    
    # Generate safe filename
    safe_name = name.lower().replace(" ", "_").replace("・", "_")
    # Keep only alphanumeric and underscore
    safe_name = "".join(c for c in safe_name if c.isalnum() or c == "_")
    
    filename = f"{safe_name}_v2.yaml"
    filepath = os.path.join(output_dir, filename)
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(yaml_content)
    
    return filepath


def main():
    parser = argparse.ArgumentParser(
        description="Generate persona YAML for Z-Axis Translation System"
    )
    parser.add_argument("--name", required=True, help="Character name")
    parser.add_argument("--source", required=True, help="Source work (anime, game, etc.)")
    parser.add_argument("--desc", required=True, help="Brief character description")
    parser.add_argument("--context", default="", help="Additional context or search results")
    parser.add_argument("--context-file", help="File containing additional context")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Model to use")
    parser.add_argument("--output-dir", default="personas", help="Output directory")
    parser.add_argument("--print-only", action="store_true", help="Print YAML without saving")
    
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
    
    if args.print_only:
        print(yaml_content)
    else:
        filepath = save_persona(yaml_content, args.name, args.output_dir)
        print(f"✅ Persona saved to: {filepath}")
        print()
        print("=" * 60)
        print(yaml_content)


if __name__ == "__main__":
    main()
