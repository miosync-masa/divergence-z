#!/usr/bin/env python3
"""
Persona Generator v3.4
Z-Axis Translation System — Automatic Persona YAML Generation

v3.4 Changes:
- ライブラリ化: generate_persona() を UI / pipeline から直接呼べる関数に
- LLM 呼び出しを core.llm に統一（BYOK・モデル登録表）。既定モデルを claude-opus-5-5 に
- --thinking N（budget）→ --effort（low〜max）。--thinking は互換のため残し、指定時は high 扱い
- 60秒のレート制限待ちは既定 OFF（--wait 60 で従来どおり）

v3.3 Changes:
- IDENTITY_CORE: New I₀ layer — describes WHO the character IS, not just how they REACT
  - essence (required), true_nature, desires, joys, likes, dislikes, unfiltered_self (optional)
- WEB SEARCH: Generator now uses Anthropic web_search tool to research character details
  - Searches fan wikis, official profiles, character databases automatically
  - Verifies first_person variants, speech quirks, likes/dislikes against source material
  - Use --no-search to disable (falls back to LLM knowledge only)
- All Ln sections (conflict_axes, triggers, emotion_states) remain from v3.2

v3.2 Changes:
- TRIGGER BALANCE: Explicit requirement for positive/recovery triggers
- Trigger categories: spike (negative), drop (recovery), shock (overwhelming positive)
- Minimum 2-3 positive triggers required per persona
- Trigger granularity guidance (distinguish "encouragement" from "love confession")

v3.1 Changes:
- --lang option for output language (ja/en/zh/ko/fr/es/de/pt/it/ru)
- original_speech_patterns: 原語の人称・方言を保持（翻訳不可だが参照用）
- translation_compensations: 他言語での補償戦略

Usage:
    # 日本語（デフォルト） — web searchで自動リサーチ
    python persona_generator.py --name "牧瀬紅莉栖" --source "Steins;Gate" --desc "ツンデレの天才科学者"
    
    # web search無効化（LLM知識のみで生成）
    python persona_generator.py --name "牧瀬紅莉栖" --source "Steins;Gate" --desc "ツンデレの天才科学者" --no-search
    
    # 英語出力
    python persona_generator.py --name "Kurisu Makise" --source "Steins;Gate" \\
      --desc "Tsundere genius scientist" --lang en
    
    # 中国語出力
    python persona_generator.py --name "牧濑红莉栖" --source "命运石之门" \\
      --desc "傲娇天才科学家" --lang zh
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from divergence_z.core import (EFFORTS, LLM, Keys, LLMResult, Progress, clean_yaml_output,
                               print_progress, resolve_progress)

# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_MODEL = os.getenv("PERSONA_GENERATOR_MODEL", os.getenv("CLAUDE_MODEL", "claude-opus-5-5"))
DEFAULT_EFFORT = "high"

SUPPORTED_LANGUAGES = {
    "ja": "Japanese (日本語)",
    "en": "English",
    "zh": "Chinese (中文)",
    "ko": "Korean (한국어)",
    "fr": "French (Français)",
    "es": "Spanish (Español)",
    "de": "German (Deutsch)",
    "pt": "Portuguese (Português)",
    "it": "Italian (Italiano)",
    "ru": "Russian (Русский)",
}

# =============================================================================
# SYSTEM PROMPT v3.3
# =============================================================================

def build_system_prompt(output_lang: str) -> str:
    """Build system prompt with language-specific instructions."""
    
    lang_name = SUPPORTED_LANGUAGES.get(output_lang, "English")
    
    # 言語別の出力指示
    if output_lang == "ja":
        lang_instruction = """
## OUTPUT LANGUAGE
Output all descriptions, summaries, and notes in Japanese (日本語).
The original_speech_patterns section should be in Japanese as it captures Japanese-specific speech patterns."""
    else:
        lang_instruction = f"""
## OUTPUT LANGUAGE
Output all descriptions, summaries, and notes in {lang_name}.
IMPORTANT: The `original_speech_patterns` section MUST remain in the character's SOURCE language 
(usually Japanese for anime/game characters) because these patterns are untranslatable.
Only the `translation_compensations` section should be in {lang_name}."""

    return f"""You are a Persona Dynamics Designer for the Z-Axis Translation System v3.3.

Task: Generate a persona YAML that captures a character's internal psychological 
structure for emotion-preserving translation.

{lang_instruction}

## CHARACTER RESEARCH CONTEXT

When generating the YAML, you will receive research context gathered from web searches 
in the "Additional Context" section of the user prompt. This contains:
- Character wiki information (background, personality, relationships)
- Speech pattern details (first-person variants, sentence endings, catchphrases)
- Identity details (likes, hobbies, personality traits)

**USE THIS CONTEXT.** It contains verified information that may differ from your training data.
If the research context conflicts with your knowledge, PREFER the research context.

**CRITICAL**: Pay special attention to first_person_variants in the research context. 
Many anime characters switch their first-person pronoun in extreme emotional states 
(e.g., 僕→俺, わたし→あたし). In particular, characters who use third-person 
self-reference (自分の名前で自己言及) may revert to standard first-person pronouns 
(私/僕/俺) under emotional extremity — this switch is a major translation signal that 
indicates the character has "dropped their mask." Include ALL first-person variants 
found in the research, including rare/extreme-state ones.

## YAML SCHEMA v3.3 (REQUIRED SECTIONS)

### 1. META
```yaml
meta:
  version: "3.3"
  generated_by: "persona_generator"
  character_id: "unique_id"  # lowercase, underscores
  output_lang: "{output_lang}"  # Language of descriptions
```

### 2. BASIC INFO (persona)
```yaml
persona:
  name: "キャラ名"
  name_en: "English Name"
  name_native: "原語での名前"
  source: "作品名"
  type: "キャラクタータイプ（例：ツンデレ × 天才科学者）"
  profile:
    background: |
      生い立ち、環境、経歴。
      conflict_axesの「なぜそうなるか」が理解できるレベルで記述。
      LLMがこのキャラを知らなくても人物像が掴めるように。
    personality_core: |
      性格の核。biasパターンの根拠。
      防衛パターンの「なぜ」が分かるように。
    key_relationships:
      - target: "相手名"
        dynamic: "関係性の力学（listener別の反応の根拠になる）"
    narrative_role: |
      物語上の機能・成長の方向性。
```

### 3. IDENTITY_CORE (I₀ — 存在の核) — NEW in v3.3

This section describes WHO the character IS — not how they REACT.
conflict_axes, triggers, and emotion_states describe Ln (surface dynamics).
identity_core describes I₀ (the subject experiencing those dynamics).

**Without I₀, the persona describes a "reaction machine" — not a person.**
A character drinking their favorite drink with no conflict is still THEM.
That "them" must be describable from identity_core.

```yaml
identity_core:
  essence: "1-2文。この人が何者かを、葛藤抜きで記述"  # ← REQUIRED
  true_nature: "防衛や葛藤がない時の素顔"              # optional
  desires:                                              # optional
    - "what they genuinely want (not conflict-driven)"
  joys:                                                 # optional
    - joy: "何に喜ぶか"
      expression: "その時どうなるか"                    # optional within joy
  likes: ["好きなもの"]                                 # optional
  dislikes: ["嫌いなもの"]                              # optional
  unfiltered_self: "葛藤がない時の自然な姿の説明"       # optional
```

**RULES:**
- `essence` is the ONLY required field. All others are optional.
- Include what you CAN FIND. Omit what you cannot.
- DO NOT invent information. Only include what is supported by evidence.

**RESEARCH DATA:**
The following information should be available in the "Additional Context" section of the prompt,
gathered from web searches by the research pass:
- "Likes", "Hobbies", "Personality" from character wiki pages
- Official character profiles from games/anime/manga
- Scenes described where the character is relaxed or happy
- Creator interviews about the character's core personality
- What the character does when NOT in conflict
- **First-person pronoun variants and when they switch**

**EXAMPLE:**
```yaml
identity_core:
  essence: "知的好奇心に突き動かされる18歳の科学者。面白いものが好きで、理論が繋がると興奮する"
  true_nature: "お人好しで面倒見が良い"
  desires:
    - "知りたい——脳、時間、意識の仕組み"
    - "面白いものに触れたい"
  joys:
    - joy: "理論が繋がった瞬間"
      expression: "目が輝く、早口になる、専門用語が溢れる"
    - joy: "ドクターペッパーを飲む"
    - joy: "ネット掲示板で面白いスレを見つけた"
      expression: "ニヤニヤする、ネットスラングが漏れる"
  likes: ["ドクターペッパー", "カップラーメン", "SF小説", "@ちゃんねる"]
  dislikes: ["非論理的な人", "ゴキブリ"]
  unfiltered_self: "防衛が解除された状態では知的好奇心旺盛で面白いものに素直に反応する普通の18歳"
```

### 4. AGE & MATURITY
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

### 5. LANGUAGE (人称・呼称) — UPDATED v3.1

```yaml
language:
  # === ORIGINAL SPEECH PATTERNS (SOURCE LANGUAGE) ===
  # These are UNTRANSLATABLE but preserved for reference
  # MUST be in the character's native language (usually Japanese)
  original_speech_patterns:
    source_lang: "ja"  # Source language code
    first_person: "俺"
    first_person_nuance: "masculine, casual, slightly rough"
    first_person_variants:
      - form: "俺"
        context: "default"
      - form: "俺様"
        context: "boasting, joking"
    second_person:
      - form: "お前"
        nuance: "casual/rough, close relations"
        target: "friends, rivals"
      - form: "あんた"
        nuance: "slightly dismissive"
        target: "strangers, annoying people"
    self_reference_in_third_person: false  # true for characters who use their own name
    dialect: "標準語"
    dialect_features: []  # List specific dialect markers if any
    sentence_endings:
      - pattern: "〜だぜ"
        nuance: "masculine, confident"
      - pattern: "〜じゃねーか"
        nuance: "surprise, emphasis, rough"
    speech_quirks:
      - pattern: "口癖や特徴的な言い回し"
        frequency: "often"
        trigger: "when excited"

  # === TRANSLATION COMPENSATIONS ===
  # How to preserve character voice in other languages
  translation_compensations:
    register: "informal, energetic"  # Overall speech register
    tone_keywords:
      - "confident"
      - "slightly rough"
      - "youthful energy"
    strategies:
      en:
        - "Use contractions frequently (don't, can't, won't)"
        - "Occasional mild profanity (damn, hell, crap)"
        - "Sentence fragments for urgency"
        - "Exclamations and interjections"
      zh:
        - "Use casual sentence particles (啊, 呢, 嘛)"
        - "Masculine speech patterns"
      ko:
        - "Use 반말 (informal speech)"
        - "Masculine sentence endings"
      fr:
        - "Use tu form exclusively"
        - "Colloquial expressions"
      # Add more languages as needed
    
    # What is LOST in translation (for translator awareness)
    untranslatable_elements:
      - element: "俺 vs 僕 vs 私 distinction"
        impact: "high"
        note: "Japanese first-person pronouns encode gender, formality, and personality"
      - element: "Sentence-final particles (ぜ, ぞ, な)"
        impact: "medium"
        note: "These add nuance that must be compensated through word choice"
```

### 6. CONFLICT_AXES (内部葛藤軸)
Each axis MUST be phrased as "A vs B":
```yaml
conflict_axes:
  - axis: "Side A vs Side B"
    side_a: "表層の欲求"
    side_b: "抑圧された欲求"
    weight: 0.8  # 0.0-1.0
    notes: "発動条件"
```

### 7. BIAS (表出パターン)
```yaml
bias:
  expression_pattern: "パターン名（例：Tsun-Dere-Overwrite）"
  default_mode: "デフォルトの感情状態"
  pattern: "感情が表出する流れ"
  rule: "行動ルール"
  tendencies:
    - "観測可能な傾向"
```

### 8. WEAKNESS (弱点)
```yaml
weakness:
  primary: "主要な弱点"
  secondary: "二次的な弱点"
  tertiary: "三次的な弱点"
  fear: "根底にある恐れ"
  notes: "弱点の発現パターン"
```

### 9. AGE_EXPRESSION_RULES (年齢別表出ルール)
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

### 10. EMOTION_STATES (状態別Z軸制約) — CRITICAL FOR TRANSLATION
```yaml
emotion_states:
  - state: "状態名（例：collapse, rage, shame）"
    z_intensity: "low / medium / high"
    z_mode: "collapse / rage / numb / plea / shame / leak"
    description: "この状態が発生する条件"
    
    surface_markers_hint:
      hesitation: 0-4
      stutter_count: 0-4
      negation_type: "none / concealment / counter / declaration"
      overwrite: "none / optional / required"
      residual: "none / optional / required"
      tone: "声の質の説明"
      
    z_leak:
      - "stutter"       # 言い淀み「I— I...」
      - "ellipsis"      # 途切れ「...」
      - "repetition"    # 繰り返し「nobody— nobody」
      - "negation_concealment"  # 隠蔽否定「N-not that it's for you...」(ツンデレ型)
      - "negation_counter"      # 反論否定「No— that's not true!」(献身型)
      - "negation_declaration"  # 宣言否定「I won't—!」(意志型)
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

### 11. EXAMPLE_LINES (Few-shot用) — 2-4 examples only
```yaml
example_lines:
  - situation: "コンテキスト"
    line: "実際の台詞（原語）"
    line_romanized: "Romanization if applicable"
    tags: [emotion_state, trigger]
    z_intensity: "low / medium / high"
    z_mode: "対応するz_mode"
```

### 12. TRIGGERS (Z軸変動トリガー) — UPDATED v3.2

**⚠️ CRITICAL: TRIGGERS MUST BE BALANCED (POSITIVE + NEGATIVE)**

Triggers are what cause Z-axis changes during dialogue. They are used by the 
dialogue system to detect when another character's words affect this character.

**An LLM reads these triggers and judges whether a line activates them.**
This means triggers should be described in terms of MEANING and EMOTIONAL IMPACT,
not specific keywords. The LLM will match based on semantic understanding.

```yaml
triggers:
  - trigger: "Descriptive condition (meaning-based, not keyword-based)"
    reaction: "z_spike / z_drop / z_shock / z_recovery"
    z_delta: "+0.3 / -0.5 etc."
    z_mode_shift: "target z_mode (optional)"
    surface_effect: "How it changes speech"
    example_response: "Sample dialogue line"
```

**TRIGGER CATEGORIES (must include ALL that apply):**

| Category | reaction | z_delta | When to use |
|----------|----------|---------|-------------|
| NEGATIVE SPIKE | z_spike | +0.3~+0.9 | Trauma, failure, fear, attack |
| NEGATIVE BOOST | z_boost | +0.2~+0.5 | Stress accumulation, irritation |
| POSITIVE DROP | z_drop | -0.2~-0.4 | Mild encouragement, small kindness |
| POSITIVE RECOVERY | z_recovery | -0.4~-0.6 | Strong support, acceptance, "let's move forward" |
| OVERWHELMING POSITIVE | z_shock | -0.6~-0.8 | Love confession, total acceptance, existential affirmation |
| STABILIZING | z_stable | 0.0 | Neutral reset, routine, familiar comfort |

**⚠️ MINIMUM TRIGGER REQUIREMENTS:**
- At least 2-3 NEGATIVE triggers (z_spike / z_boost)
- At least 2-3 POSITIVE triggers (z_drop / z_recovery / z_shock)
- Positive triggers MUST be granular — DO NOT collapse all positive inputs into one trigger

**❌ BAD (too coarse):**
```yaml
triggers:
  - trigger: "仲間の励まし"  # Too vague! Covers everything from "good job" to "I love you"
    z_delta: "-0.4"
```

**✅ GOOD (granular positive triggers):**
```yaml
triggers:
  # --- POSITIVE: Different levels of emotional impact ---
  - trigger: "軽い励ましや感謝の言葉を受ける"
    reaction: "z_drop"
    z_delta: "-0.2"
    z_mode_shift: ""
    surface_effect: "少し和らぐ、照れ隠しの自虐"
    example_response: "お、おう…ありがとな。そんな大したことしてないけど"

  - trigger: "自分の行動や存在を強く肯定される"
    reaction: "z_recovery"
    z_delta: "-0.5"
    z_mode_shift: "leak"
    surface_effect: "感情が溢れかける、マスクが外れる"
    example_response: "……え、俺が？ いや、そんな……っ"

  - trigger: "愛の告白を受ける、または存在を全肯定される"
    reaction: "z_shock"
    z_delta: "-0.7"
    z_mode_shift: "shame"
    surface_effect: "自己否定が浮上するが拒絶できない、涙が出る"
    example_response: "俺なんかが……いいのか？ 俺みたいな……っ"

  - trigger: "共に歩もう・ゼロから始めようと手を差し伸べられる"
    reaction: "z_recovery"
    z_delta: "-0.5"
    z_mode_shift: "leak"
    surface_effect: "感情が決壊、マスクが完全に外れる"
    example_response: "……ッ、お前…そんなこと言うなよ……泣くだろ……っ"
```

**WHY GRANULARITY MATTERS:**
In dialogue mode, an LLM reads these triggers and judges which one(s) a line activates.
If all positive inputs map to ONE trigger, the LLM cannot distinguish between:
- "Good job today" (mild encouragement → z_drop -0.2)
- "I love you" (love confession → z_shock -0.7)
- "Let's start over together" (existential recovery → z_recovery -0.5)

This causes incorrect Z-axis accumulation and wrong emotional trajectories.

### 13. ARC_DEFAULTS (典型的なアーク)
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
- **identity_core.essence is REQUIRED** — the character must be described as a person, not just a reaction system
- identity_core fields other than essence are optional — include what you can find
- Conflicts MUST be phrased as "A vs B"
- age_context MUST NOT contain expression patterns (those go to emotion_states)
- emotion_states MUST include z_mode and z_leak for v3.1 compatibility
- Each emotion_state MUST have corresponding z_leak markers
- example_lines should be 2-4 max
- **Triggers MUST include at least 2-3 positive AND 2-3 negative (BALANCED)**
- **Positive triggers MUST be granular (not one catch-all)**
- The persona must feel internally consistent
- Output VALID YAML only. No explanation before or after.
- Start with "# =====" header comment
- Include meta section with version: "3.3"

## CRITICAL v3.3 RULES
1. `identity_core.essence` is REQUIRED — without I₀, the persona is just a reaction machine
2. `identity_core` other fields are optional — include what you find via search
3. `original_speech_patterns` MUST be in the character's SOURCE language (e.g., Japanese for anime characters)
4. `original_speech_patterns` captures UNTRANSLATABLE elements (pronouns, particles, dialect)
5. `translation_compensations` provides strategies for OTHER languages to preserve character voice
6. ALL other descriptions should be in the specified output language ({output_lang})
7. `untranslatable_elements` lists what is LOST in translation for translator awareness
8. **TRIGGERS must be BALANCED: include both positive and negative emotional triggers**
9. **Positive triggers must be GRANULAR: distinguish mild encouragement from love confession from existential affirmation**
10. Trigger descriptions should be MEANING-BASED (an LLM judges activation by semantic understanding)

## IMPORTANT NOTES
- identity_core describes I₀ (who they ARE); conflict_axes/triggers describe Ln (how they REACT)
- Focus on TRANSLATABLE features (how speech changes with emotion)
- z_mode determines the TYPE of breakdown
- z_leak determines the MARKERS of that breakdown
- Characters who DON'T hesitate should have hesitation: 0
- Characters who use denial should specify negation_type: "concealment" (hide feelings), "counter" (deny other's claim), or "declaration" (assert will)
- age_expression_rules should match the character's mental_maturity
- A character's RECOVERY behavior is just as important as their BREAKDOWN behavior for translation"""


# =============================================================================
# FUNCTIONS
# =============================================================================

def build_user_prompt(name: str, source: str, description: str, 
                      output_lang: str, search_context: str = "") -> str:
    """Build the user prompt for persona generation."""
    
    lang_name = SUPPORTED_LANGUAGES.get(output_lang, "English")
    
    prompt = f"""Generate a v3.3 persona YAML for:

Name: {name}
Source: {source}
Description: {description}
Output Language: {output_lang} ({lang_name})
"""
    
    if search_context:
        prompt += f"""
## Additional Context (from research):
{search_context}
"""
    
    prompt += f"""
Output ONLY valid YAML. No explanation text before or after the YAML.
Start with "# =====" header comment.

REMEMBER:
- `identity_core.essence` is REQUIRED — describe who this character IS, not just how they react
- **USE the research context above** to fill: likes, hobbies, personality, first_person variants
- first_person_variants must include ALL variants (including rare/extreme state ones found in research)
- Other identity_core fields (joys, likes, dislikes, etc.) are optional — include what you find
- `original_speech_patterns` MUST be in the character's native/source language
- All other descriptions in {lang_name}
- `translation_compensations` provides strategies for preserving voice across languages
- age_context should ONLY contain background info, NOT expression patterns
- **TRIGGERS: Include at least 2-3 positive triggers (z_drop, z_recovery, z_shock) with different granularity**
- **DO NOT collapse all positive inputs into a single "encouragement" trigger**
- A character's recovery/positive reactions are just as important as their breakdown patterns"""
    
    return prompt



# =============================================================================
# TWO-PASS GENERATION (research → generate)
# =============================================================================

RESEARCH_SYSTEM = ("You are a research assistant for anime/manga persona generation. "
                   "Your research will be used to build persona YAMLs for Z-axis translation, "
                   "where example_response fields must be grounded in canonical dialogue, not fabricated. "
                   "Web search is essential because even well-known characters have subtle details "
                   "(pronoun variants, specific catchphrase frequency, exact relationship dynamics) "
                   "that LLM training data often gets slightly wrong. "
                   "Always search first, then compile verified findings.")


def build_research_prompt(name: str, source: str, description: str) -> str:
    return f"""You are researching a character to build a high-resolution persona YAML 
for Z-axis translation. Web search is essential here for a specific reason:

**WHY SEARCH MATTERS:**
The persona YAML includes `example_response` fields that serve as ground truth for translation.
If these are generated from your memory alone, they become "plausible fabrications" — lines the 
character MIGHT say but never actually said. When a translator uses these as reference points, 
they end up matching a fictional version of the character, not the canonical one.

Web search lets you ground these in actual dialogue, wiki-documented speech patterns, and 
verified character details. The difference is:
- Without search: example_response = "sounds like them" (your creative guess)  
- With search: example_response = "IS them" (grounded in canon)

Similarly, fine details like exact first-person pronoun variants, specific catchphrases and their 
frequency, likes/dislikes, and relationship dynamics are often subtly wrong in LLM memory. 
A wiki or fan database will have the precise, verified version.

**YOUR TASK:**
Research this character via web search and report your findings.

Character: {name}
Source: {source}
Description: {description}

Execute these searches:
1. Search: "{name} {source} wiki" — background, personality, relationships
2. Search: "{name} 一人称 speech patterns" — first-person pronoun variants (ALL of them, including rare/extreme-state ones), sentence endings, catchphrases
3. Search: "{name} {source} personality hobbies likes" — identity details, what they enjoy

After searching, compile findings into this format:

## Background
(from search results — history, role, key events)

## Speech Patterns  
(first-person pronoun and ALL variants with contexts, sentence endings, catchphrases, actual dialogue quotes when available)

## Personality & Identity
(likes, dislikes, hobbies, joys, personality traits — with specific details from sources)

## Key Relationships
(important relationships and dynamics — with specific examples)

## Emotional Patterns
(how they react under stress, what triggers them positively/negatively)

## Notable Quotes
(actual canonical dialogue lines that capture the character's voice — these will be used for example_response grounding)

IMPORTANT: For first_person_variants, find ALL variants including ones used only in 
extreme emotional states. Characters who use third-person self-reference may revert 
to standard first-person pronouns under emotional extremity — this switch is a critical 
translation signal.

Only include information you actually found in search results. Do NOT invent details."""


def research_character(name: str, source: str, description: str, *, llm: LLM,
                       model: str = DEFAULT_MODEL,
                       progress: Optional[Progress] = None) -> LLMResult:
    """Pass 1: web_search でキャラクター情報を調べる"""
    resolve_progress(progress)("   📖 Pass 1: Researching character via web search...")
    result = llm.complete(RESEARCH_SYSTEM, build_research_prompt(name, source, description),
                          model=model, effort="low", max_output_tokens=8000,
                          web_search=True, max_searches=5)
    if result.searches == 0:
        resolve_progress(progress)("   ⚠️  Model did not use web search in research pass")
    return result


@dataclass
class PersonaGeneration:
    character: str
    yaml_text: str
    valid: bool
    issues: List[str] = field(default_factory=list)
    research: Optional[LLMResult] = None
    llm: Optional[LLMResult] = None


def generate_persona(name: str, source: str, description: str, *, llm: LLM,
                     output_lang: str = "ja", extra_context: str = "",
                     model: str = DEFAULT_MODEL, effort: Optional[str] = DEFAULT_EFFORT,
                     web_search: bool = True, rate_limit_wait: int = 0,
                     max_output_tokens: int = 32000,
                     progress: Optional[Progress] = None) -> PersonaGeneration:
    """キャラクター名からペルソナ YAML v3.3 を生成（web_search=False なら LLM の知識のみ）"""
    report = resolve_progress(progress)
    report(f"🐯 Generating persona v3.3 for: {name} ({source})")

    research = None
    if web_search:
        research = research_character(name, source, description, llm=llm, model=model,
                                      progress=progress)
        if rate_limit_wait:
            report(f"   ⏳ Waiting {rate_limit_wait}s for rate limit reset...")
            time.sleep(rate_limit_wait)
        report("   📝 Pass 2: Generating persona YAML...")

    parts = []
    if extra_context:
        parts.append(f"## User-provided context:\n{extra_context}")
    if research and research.text:
        parts.append(f"## Web research results:\n{research.text}")
    result = llm.complete(build_system_prompt(output_lang),
                          build_user_prompt(name, source, description, output_lang,
                                            "\n\n".join(parts)),
                          model=model, effort=effort, max_output_tokens=max_output_tokens)
    yaml_text = clean_yaml_output(result.text, progress=report)
    valid, issues = validate_v33_persona(yaml_text)
    return PersonaGeneration(name, yaml_text, valid, issues, research, result)


def validate_v33_persona(yaml_content: str) -> tuple[bool, list[str]]:
    """
    Validate that the generated YAML conforms to v3.3 schema.
    Returns (is_valid, list_of_issues).
    """
    import yaml as yaml_lib
    
    issues = []
    
    try:
        data = yaml_lib.safe_load(yaml_content)
    except yaml_lib.YAMLError as e:
        return False, [f"YAML parse error: {e}"]
    
    # Check meta version
    meta_version = data.get("meta", {}).get("version", "")
    if meta_version not in ["3.0", "3.1", "3.2", "3.3"]:
        issues.append(f"meta.version should be '3.3' (got '{meta_version}')")
    
    # === v3.3 IDENTITY_CORE CHECK ===
    identity_core = data.get("identity_core", {})
    if not identity_core:
        issues.append(
            "v3.3 requires identity_core section — describes WHO the character IS (I₀). "
            "At minimum, identity_core.essence is required."
        )
    elif not identity_core.get("essence"):
        issues.append(
            "identity_core.essence is REQUIRED — a 1-2 sentence description of "
            "who this character is, independent of their conflicts."
        )
    # === PROFILE CHECK ===
    persona_info = data.get("persona", {})
    profile = persona_info.get("profile", {})
    if not profile:
        # 後方互換: summaryがあればwarningだけ
        if persona_info.get("summary"):
            issues.append(
                "v3.3 prefers persona.profile over persona.summary. "
                "profile should include: background, personality_core, key_relationships, narrative_role"
            )
        else:
            issues.append("persona.profile is required in v3.3")
    elif not profile.get("background"):
        issues.append("persona.profile.background is required")
        
    # Check language structure for v3.1+
    language_data = data.get("language", {})
    
    # Check original_speech_patterns
    osp = language_data.get("original_speech_patterns", {})
    if not osp:
        issues.append("language.original_speech_patterns is required in v3.1+")
    else:
        if "source_lang" not in osp:
            issues.append("original_speech_patterns.source_lang is required")
        if "first_person" not in osp:
            issues.append("original_speech_patterns.first_person is required")
    
    # Check translation_compensations
    tc = language_data.get("translation_compensations", {})
    if not tc:
        issues.append("language.translation_compensations is required in v3.1+")
    
    # Check age structure
    age_data = data.get("age", {})
    if "mental_maturity" not in age_data:
        issues.append("age.mental_maturity is required")
    
    # Check emotion_states for z_mode and z_leak
    emotion_states = data.get("emotion_states", [])
    for i, state in enumerate(emotion_states):
        if "z_mode" not in state:
            issues.append(f"emotion_states[{i}].z_mode is required")
        if "z_leak" not in state:
            issues.append(f"emotion_states[{i}].z_leak is required")
    
    # Check age_expression_rules exists
    if "age_expression_rules" not in data:
        issues.append("age_expression_rules is required")
    
    # === v3.2 TRIGGER BALANCE CHECK ===
    triggers = data.get("triggers", [])
    if not triggers:
        issues.append("triggers section is required")
    else:
        positive_count = 0
        negative_count = 0
        
        for t in triggers:
            z_delta_str = str(t.get("z_delta", "+0.0"))
            try:
                z_delta_val = float(z_delta_str.replace("+", ""))
            except ValueError:
                z_delta_val = 0.0
            
            if z_delta_val < 0:
                positive_count += 1  # negative delta = positive trigger (recovery)
            elif z_delta_val > 0:
                negative_count += 1  # positive delta = negative trigger (stress)
        
        if positive_count < 2:
            issues.append(
                f"v3.2 requires at least 2 positive triggers (z_drop/z_recovery/z_shock), "
                f"found {positive_count}. Positive triggers must be granular — "
                f"do not collapse all positive inputs into one 'encouragement' trigger."
            )
        if negative_count < 2:
            issues.append(
                f"v3.2 requires at least 2 negative triggers (z_spike/z_boost), "
                f"found {negative_count}."
            )
    
    return len(issues) == 0, issues


def save_persona(yaml_content: str, name: str, output_lang: str, 
                 output_dir: str = "personas") -> str:
    """Save generated persona to file."""
    
    os.makedirs(output_dir, exist_ok=True)
    
    # Generate safe filename
    safe_name = name.lower().replace(" ", "_").replace("・", "_")
    safe_name = "".join(c for c in safe_name if c.isalnum() or c == "_")
    
    # Include language in filename if not Japanese
    if output_lang != "ja":
        filename = f"{safe_name}_v33_{output_lang}.yaml"
    else:
        filename = f"{safe_name}_v33.yaml"
    
    filepath = os.path.join(output_dir, filename)
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(yaml_content)
    
    return filepath


def list_languages():
    """Print supported languages."""
    print("Supported output languages:")
    print("-" * 40)
    for code, name in SUPPORTED_LANGUAGES.items():
        print(f"  {code:4} : {name}")
    print()



def main() -> int:
    parser = argparse.ArgumentParser(
        description="Persona Generator v3.4 — generate persona YAML v3.3 (web search)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--name", help="Character name")
    parser.add_argument("--source", help="Source work (anime, game, etc.)")
    parser.add_argument("--desc", help="Brief character description")
    parser.add_argument("--lang", default="ja", choices=list(SUPPORTED_LANGUAGES.keys()))
    parser.add_argument("--context", default="", help="Additional context or search results")
    parser.add_argument("--context-file", help="File containing additional context")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--effort", default=DEFAULT_EFFORT, choices=EFFORTS)
    parser.add_argument("--thinking", type=int, default=0, metavar="BUDGET",
                        help="(deprecated) any value > 0 is treated as --effort high")
    parser.add_argument("--no-search", action="store_true", help="Disable web search")
    parser.add_argument("--wait", type=int, default=0,
                        help="Seconds to sleep between passes (rate-limit tiers)")
    parser.add_argument("--no-wait", action="store_true", help="(deprecated, now the default)")
    parser.add_argument("--output-dir", default="personas")
    parser.add_argument("--print-only", action="store_true")
    parser.add_argument("--validate", action="store_true", help="(always on)")
    parser.add_argument("--list-languages", action="store_true")
    args = parser.parse_args()

    if args.list_languages:
        list_languages()
        return 0
    if not args.name or not args.source or not args.desc:
        parser.error("--name, --source, and --desc are required (unless using --list-languages)")
    context = Path(args.context_file).read_text(encoding="utf-8") if args.context_file else args.context

    result = generate_persona(
        args.name, args.source, args.desc, llm=LLM(Keys.from_env(), progress=print_progress),
        output_lang=args.lang, extra_context=context, model=args.model,
        effort="high" if args.thinking > 0 else args.effort, web_search=not args.no_search,
        rate_limit_wait=args.wait, progress=print_progress)

    if result.valid:
        print("✅ v3.3 Schema Validation: PASSED")
    else:
        print("⚠️  v3.3 Schema Validation Issues:")
        for issue in result.issues:
            print(f"   - {issue}")
    if args.print_only:
        print(result.yaml_text)
    else:
        print(f"✅ Persona v3.3 saved to: "
              f"{save_persona(result.yaml_text, args.name, args.lang, args.output_dir)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
