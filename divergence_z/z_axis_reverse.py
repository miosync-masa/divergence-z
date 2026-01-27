#!/usr/bin/env python3
"""
Z-Axis Reverse Analyzer
英語翻訳から感情構造・葛藤軸・Z強度を逆算する

Usage:
    python z_axis_reverse.py "No… I want you, Subaru-kun. If it isn't you, I can't accept it."
    python z_axis_reverse.py --file input.txt
"""

import argparse
import json
import os
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import yaml
from openai import OpenAI
from dotenv import load_dotenv

# =============================================================================
# CONFIGURATION
# =============================================================================
load_dotenv()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.2")

SYSTEM_PROMPT = """You are a Z-Axis Reverse Analyzer.

Task: Given an English translation (likely from Japanese), reverse-engineer the emotional structure, conflict axes, and Z-axis intensity that would have produced this output.

## ANALYSIS FRAMEWORK

### 1. SURFACE MARKERS (表層マーカー検出)
Identify linguistic cues:
- hesitation_markers: "...", "—", "um", "well"
- stutter_patterns: "I-I", "N-no"
- negation_first: Does it start with denial? ("No", "It's not like", "I don't")
- overwrite_patterns: Self-correction ("I mean", "that is", "actually")
- residual_markers: Trailing softness ("...I guess", "...maybe", "...yeah")
- tone: formal/casual, direct/indirect, soft/hard

### 2. Z-AXIS INTENSITY
- low: Calm, controlled, minimal markers
- medium: Some hesitation or emotional leakage
- high: Direct expression, strong markers, overflow detected

### 3. WAVE ANALYSIS
- wave_a: True intent (what the speaker really wants to convey)
- wave_b: Suppression (what the speaker is trying to hide/control)
- interference: constructive / mixed / destructive

### 4. CONFLICT AXES
Infer internal conflicts:
- Format: "A vs B"
- Estimate activation level (0.0-1.0)
- Identify which side is "winning"

### 5. PERSONA HINTS
Suggest character traits:
- expression_pattern
- default_mode
- weakness/trigger

### 6. ORIGINAL INTENT
- The "act" being performed (not just the meaning)
- The relationship dynamic implied
- What the listener is supposed to "receive"
- Ethical/emotional temperature

### 7. PROBABLE JAPANESE STRUCTURE
- Likely sentence patterns
- Probable first/second person pronouns
- Speech level (formal/casual)

## OUTPUT
Return as valid JSON only. No explanation outside JSON."""

# =============================================================================
# FUNCTIONS
# =============================================================================

def analyze_reverse(english_text: str, context: str = "", model: str = DEFAULT_MODEL) -> dict:
    """Reverse analyze English translation to extract Z-axis structure."""
    
    client = OpenAI()
    
    user_prompt = f"Analyze this English translation:\n\n\"{english_text}\""
    
    if context:
        user_prompt += f"\n\nContext: {context}"
    
    print(f"🔍 Reverse analyzing: \"{english_text[:50]}...\"")
    print(f"   Model: {model}")
    print()
    
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.3,
        response_format={"type": "json_object"}
    )
    
    result = json.loads(response.choices[0].message.content)
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Z-Axis Reverse Analyzer - Extract emotional structure from English translation"
    )
    parser.add_argument("text", nargs="?", help="English text to analyze")
    parser.add_argument("--file", help="File containing English text")
    parser.add_argument("--context", default="", help="Additional context about the scene")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Model to use")
    
    args = parser.parse_args()
    
    # Get input text
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            text = f.read().strip()
    elif args.text:
        text = args.text
    else:
        parser.error("Please provide text to analyze or use --file")
    
    # Analyze
    result = analyze_reverse(text, args.context, args.model)
    
    # Output
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
