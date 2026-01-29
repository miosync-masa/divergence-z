# Divergence-Z 🌀

> "Don't Kill the Tsundere"  
> — Action-Preserving Translation for Fictional Speech

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

> **Example**: Same line「別に...あんたのためじゃないから」  
> - GPT-5.2: "**N-not** that it's for you or anything..."  
> - Opus: "It's not like… it's for you or anything."

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

## Quick Start
```bash
cd divergence_z

# 1. Generate persona (uses Claude)
python persona_generator.py --name "レム" --source "Re:Zero" --desc "献身的メイド"

# 2a. [単発翻訳] Translate with Z-axis
python z_axis_translate.py --config requests/rem_test.yaml

# 2b. [対話翻訳] Translate dialogue scene ← NEW!
python z_axis_dialogue.py --config requests/rem_subaru_dialogue.yaml

# 3. Evaluate
python iap_evaluator.py -o "スバルくんが良いんです" -t "I want you, Subaru-kun"
python zap_evaluator.py --config requests/rem_test.yaml --translated "I want you, Subaru-kun"

# ============================================
# Optional: Content Generation Tools
# ============================================

# [derivative work] Generate original dialogue (LLM creates lines)
python yaml_generator.py \
  --persona personas/kurisu_v2.yaml \
  --scene "ラボで岡部と二人きり" \
  --mode solo

# [Original plastic] Convert existing script to YAML
python yaml_formatter.py \
  --script scripts/rem_subaru_zero.txt \
  --persona-a personas/レム_v2.yaml \
  --persona-b personas/スバル_v2.yaml \
  --hint "白鯨戦前夜、レムの告白"
```

## Workflow
```
                        [Claude API]
    Character Info → persona_generator → Persona YAML
                                              ↓
    ┌─────────────────────────────────────────┴─────────────────────────────────────────┐
    │                           REQUEST YAML GENERATION                                 │
    │                                                                                   │
    │   [derivative work]                              [Original Script]            　  │
    │   Scene Hint → yaml_generator ─┐         Script.txt → yaml_formatter ─┐           │
    │                [OpenAI]        │                      [OpenAI]        │           │
    │                                ▼                                      ▼           │
    │                         requests/*.yaml ◄─────────────────────────────            │
    └────────────────────────────────┬──────────────────────────────────────────────────┘
                                     ↓
                              [OpenAI API]
                    ┌─────────────────────────────────┐
                    │  z_axis_translate (Monologue)   │
                    │  z_axis_dialogue  (Dialog)      │
                    └─────────────────────────────────┘
                                     ↓
                              Translation
                                     ↓
                    iap_evaluator + zap_evaluator → Quality Score
```

## Temperature Settings

| STEP | Temperature | Purpose |
|------|-------------|---------|
| STEP1 (Hamiltonian) | 0.3 | Accurate extraction of conflict axes |
| STEP2 (Interference) | 0.3 | Stable analysis of interference patterns |
| STEP3 (Translation) | 0.7~0.9 | Natural translation preserving emotional nuance ※Only OpenAI Model|

### Design Philosophy
- **Analysis phase (STEP1/2)**: Low temperature ensures **reproducibility**
- **Generation phase (STEP3)**: Higher temperature preserves **expressive richness**
- Lower than OpenAI default (1.0) to prevent hallucination while retaining emotion
