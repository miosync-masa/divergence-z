# Divergence-Z 🌀

> "Don't Kill the Tsundere"
> — Action-Preserving Translation for Fictional Speech

## Setup

### 1. Install dependencies
```bash
pip install anthropic openai pyyaml python-dotenv requests
```

### 2. Configure API Keys

Create `.env` file in the `divergence_z/` directory:
```bash
# .env
ANTHROPIC_API_KEY=sk-ant-xxxxx   # For persona_generator.py (Claude)
OPENAI_API_KEY=sk-xxxxx          # For z_axis_translate.py, iap_evaluator.py, zap_evaluator.py
```

| Tool | API |
|------|-----|
| `persona_generator.py` | **Anthropic Claude** |
| `z_axis_translate.py` | OpenAI |
| `iap_evaluator.py` | OpenAI |
| `zap_evaluator.py` | OpenAI |

### 3. (Optional) Custom model
```bash
# .env
OPENAI_MODEL=gpt-4.1        # Default model for OpenAI tools
```

## Quick Start
```bash
cd divergence_z

# 1. Generate persona (uses Claude)
python persona_generator.py --name "レム" --source "Re:Zero" --desc "献身的メイド"

# 2. Translate with Z-axis (uses OpenAI)
python z_axis_translate.py --config requests/rem_test.yaml

# 3. Evaluate (uses OpenAI)
python iap_evaluator.py -o "スバルくんが良いんです" -t "I want you, Subaru-kun"
python zap_evaluator.py --config requests/rem_test.yaml --translated "I want you, Subaru-kun"
```

## Workflow
```
                    [Claude API]
Character Info → persona_generator → Persona YAML
                                          ↓
                                    [OpenAI API]
Context + Line → z_axis_translate → Translation
                                          ↓
                    iap_evaluator + zap_evaluator → Quality Score
```
