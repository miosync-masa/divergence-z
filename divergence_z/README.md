# Divergence-Z 🌀

> "Don't Kill the Tsundere"  
> — Action-Preserving Translation for Fictional Speech

## What's New in v3.1 🌐

### Multi-Language Support
- **Persona generation** in 10 languages (ja/en/zh/ko/fr/es/de/pt/it/ru)
- **Bidirectional translation** (ja→en, en→ja, zh→en, etc.)
- **Original speech patterns preserved** — Japanese pronouns (俺/私/僕) kept in source language
- **Translation compensations** — Strategies for preserving character voice across languages

```bash
# Generate English persona for international users
python persona_generator.py --name "Kurisu Makise" --source "Steins;Gate" \
  --desc "Tsundere genius scientist" --lang en

# Translate Chinese → English
python z_axis_dialogue.py --config dialogue_zh.yaml --source-lang zh --target-lang en
```

## Model Characteristics

| Model | Strength | Best For |
|-------|----------|----------|
| **GPT-5.2** | Strict z_leak marker application | Research demos, papers |
| **Claude Opus 4.5** | Natural, literary quality | Production translation |

```bash
# GPT-5.2 (explicit markers, good for demos)
USE_CLAUDE_FOR_STEP3=false python z_axis_translate.py --config your_config.yaml

# Claude Opus (natural flow, production use)
python z_axis_translate.py --config your_config.yaml
```

## Setup

### 1. Install dependencies
```bash
pip install anthropic openai pyyaml python-dotenv requests
```

### 2. Configure API Keys

Create `.env` file in the `divergence_z/` directory:
```bash
# .env
ANTHROPIC_API_KEY=sk-ant-xxxxx   # For persona_generator.py, z_axis_translate.py (Claude)
OPENAI_API_KEY=sk-xxxxx          # For z_axis_translate.py, iap_evaluator.py, zap_evaluator.py
```

## API Configuration
| Tool | Profiler | Translator | Evaluator | Note |
|------|----------|------------|-----------|------|
| `persona_generator.py` | — | — | Claude | Literary quality |
| `z_axis_translate.py` | OpenAI | Claude* | — | Hybrid pipeline |
| `z_axis_dialogue.py` | OpenAI | Claude* | — | Multi-turn translation |
| `iap_evaluator.py` | — | — | OpenAI | JSON stability |
| `zap_evaluator.py` | — | — | OpenAI | JSON stability |
| `yaml_generator.py` | — | — | OpenAI | Context generation |
| `yaml_formatter.py` | — | — | OpenAI | Script conversion |

> \* Set `USE_CLAUDE_FOR_STEP3=false` to use OpenAI only

### 3. (Optional) Custom model
```bash
# .env
OPENAI_MODEL=gpt-5.2        # Default model for OpenAI tools
```
> ⚠️ **Warning**: Model selection directly impacts translation quality.  
> - Downgrading models will result in loss of emotional nuance  
> - OpenAI mini models (`gpt-4o-mini`, `gpt-4.1-mini`) are **NOT RECOMMENDED**  
> - For best results: `gpt-4.1` / `gpt-5.2` + `claude-opus-4-5`

## Supported Languages 🌍

| Code | Language | Native |
|------|----------|--------|
| `ja` | Japanese | 日本語 |
| `en` | English | English |
| `zh` | Chinese | 中文 |
| `ko` | Korean | 한국어 |
| `fr` | French | Français |
| `es` | Spanish | Español |
| `de` | German | Deutsch |
| `pt` | Portuguese | Português |
| `it` | Italian | Italiano |
| `ru` | Russian | Русский |

```bash
# List all supported languages
python persona_generator.py --list-languages
python z_axis_dialogue.py --list-languages
```

## Quick Start

```bash
cd divergence_z

# ============================================
# Persona Generation (v3.1 Multi-language)
# ============================================

# Japanese output (default)
python persona_generator.py --name "牧瀬紅莉栖" --source "Steins;Gate" \
  --desc "ツンデレの天才科学者"

# English output — descriptions in English, speech patterns in Japanese
python persona_generator.py --name "Kurisu Makise" --source "Steins;Gate" \
  --desc "Tsundere genius scientist" --lang en

# Chinese output
python persona_generator.py --name "牧濑红莉栖" --source "命运石之门" \
  --desc "傲娇天才科学家" --lang zh

# ============================================
# Translation (v3.1 Multi-language)
# ============================================

# Japanese → English (default)
python z_axis_translate.py --config requests/kurisu_test.yaml

# Dialogue: Japanese → English
python z_axis_dialogue.py --config requests/rem_subaru_dialogue.yaml

# Dialogue: English → Japanese
python z_axis_dialogue.py --config requests/dialogue_en.yaml \
  --source-lang en --target-lang ja

# Dialogue: Chinese → English
python z_axis_dialogue.py --config requests/dialogue_zh.yaml \
  -s zh -t en

# ============================================
# Evaluation
# ============================================

python iap_evaluator.py -o "スバルくんが良いんです" -t "I want you, Subaru-kun"
python zap_evaluator.py --config requests/rem_test.yaml --translated "I want you, Subaru-kun"

# ============================================
# Optional: Content Generation Tools
# ============================================

# [Derivative work] Generate original dialogue (LLM creates lines)
python yaml_generator.py \
  --persona personas/kurisu_v3.yaml \
  --scene "ラボで岡部と二人きり" \
  --mode solo

# [Original Script] Convert existing script to YAML
python yaml_formatter.py \
  --script scripts/rem_subaru_zero.txt \
  --persona-a personas/レム_v3.yaml \
  --persona-b personas/スバル_v3.yaml \
  --hint "白鯨戦前夜、レムの告白"
```

## Persona YAML v3.1 Structure

### Key Innovation: Original Speech Patterns + Translation Compensations

```yaml
language:
  # === PRESERVED IN SOURCE LANGUAGE ===
  # These are UNTRANSLATABLE but kept for reference
  original_speech_patterns:
    source_lang: "ja"
    first_person: "俺"                    # ← Kept in Japanese!
    first_person_nuance: "masculine, casual, slightly rough"  # ← Explained in output lang
    sentence_endings:
      - pattern: "〜だぜ"                 # ← Kept in Japanese!
        nuance: "masculine, confident"    # ← Explained in output lang
    speech_quirks:
      - pattern: "べ、別に〜"             # ← Iconic tsundere marker, untranslatable
        trigger: "when caught showing care"

  # === COMPENSATION STRATEGIES ===
  # How to preserve character voice in OTHER languages
  translation_compensations:
    register: "informal, energetic"
    strategies:
      en:
        - "Use contractions (don't, can't)"
        - "Occasional mild profanity (damn, hell)"
      zh:
        - "Use casual particles (啊, 呢, 嘛)"
      ko:
        - "Use 반말 (informal speech)"
    
    # What is LOST in translation (for translator awareness)
    untranslatable_elements:
      - element: "俺 vs 僕 vs 私 distinction"
        impact: "high"
        note: "Japanese first-person pronouns encode gender, formality, and personality"
```

### Why This Matters

| Problem | Traditional Approach | Divergence-Z v3.1 |
|---------|---------------------|-------------------|
| "俺" → "I" loses personality | Ignore it | Preserve original + explain nuance + provide compensation strategies |
| "べ、別に" tsundere stutter | Translate literally | Mark as untranslatable + use "It's not like..." in English |
| Character voice flattens | Accept the loss | Define per-language compensation strategies |

## Workflow

```
                        [Claude API]
    Character Info → persona_generator → Persona YAML v3.1
         ↓                                     │
    --lang en/zh/ko/...                        │
    (multi-language output)                    │
                                               ↓
    ┌──────────────────────────────────────────┴────────────────────────────────────────┐
    │                           REQUEST YAML GENERATION                                 │
    │                                                                                   │
    │   [Derivative Work]                              [Original Script]                │
    │   Scene Hint → yaml_generator ─┐         Script.txt → yaml_formatter ─┐           │
    │                [OpenAI]        │                      [OpenAI]        │           │
    │                                ▼                                      ▼           │
    │                         requests/*.yaml ◄─────────────────────────────            │
    └────────────────────────────────┬──────────────────────────────────────────────────┘
                                     ↓
                              [OpenAI + Claude API]
                    ┌─────────────────────────────────┐
                    │  z_axis_translate (Monologue)   │
                    │  z_axis_dialogue  (Dialog)      │◄── --source-lang / --target-lang
                    └─────────────────────────────────┘    (bidirectional translation)
                                     ↓
                              Translation
                                     ↓
                    iap_evaluator + zap_evaluator → Quality Score
```

## Dialogue YAML v3.1 Format

```yaml
personas:
  A: "personas/subaru_v3.yaml"
  B: "personas/rem_v3.yaml"

scene: "白鯨戦後、精神的限界"

relationships:
  A_to_B: "信頼、依存しつつある"
  B_to_A: "愛情、献身"

# NEW in v3.1
source_lang: "ja"    # Source language (default: ja)
target_lang: "en"    # Target language (default: en)

dialogue:
  - speaker: A
    line: "俺は、俺が大嫌いだ"
  - speaker: B
    line: "レムは、スバルくんの味方です"
```

## Temperature Settings

| STEP | Temperature | Purpose |
|------|-------------|---------|
| STEP1 (Hamiltonian) | 0.3 | Accurate extraction of conflict axes |
| STEP2 (Interference) | 0.3 | Stable analysis of interference patterns |
| STEP3 (Translation) | 0.7~0.9 | Natural translation preserving emotional nuance ※Only OpenAI Model |

### Design Philosophy
- **Analysis phase (STEP1/2)**: Low temperature ensures **reproducibility**
- **Generation phase (STEP3)**: Higher temperature preserves **expressive richness**
- Lower than OpenAI default (1.0) to prevent hallucination while retaining emotion

## TAP Framework Philosophy

> **"What cannot be translated must be compensated."**

Divergence-Z v3.1 implements the **Translation as Action Preservation (TAP)** framework:

1. **Identify** what is untranslatable (pronouns, particles, dialect markers)
2. **Preserve** original patterns for reference
3. **Explain** the nuance in the target language
4. **Compensate** using target-language-appropriate strategies

This is not about perfect translation — it's about **preserving the character's voice** across language boundaries.

---

*Developed by Miosync, Inc. — Breaking language barriers through understanding, not just conversion.*
