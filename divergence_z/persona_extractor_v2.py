#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Persona Extractor v2.0  (GPT-5.2+ / 5.6 SOL "Pro" ready)
原作テキスト/PDFから直接キャラクターペルソナを抽出

このファイルは persona_extractor.py (v1.2) のコピー＆改修版です。
プロンプト構築・v3.3スキーマ検証・CLI/保存ロジックは v1.2 と同一。
変更点は「OpenAI 呼び出し方式」のみ。

v2.0 Changes (API layer only):
- raw `requests` 直叩き → 公式 `openai` SDK (Responses API) に移行
- モデル判定を一般化: `"5.2" in model` のようなハードコードを廃止し、
  gpt-5.x / gpt-6 / o1/o3/o4 / SOL 系を推論モデルとして自動検出
- Pro / SOL ティア(= GPT PRO相当)は同期呼び出し不可のため background モードを自動有効化し
  `responses.retrieve()` でポーリング（同期POSTだと Pro は失敗/タイムアウトするため）
- status = incomplete/failed を明示的にハンドリング
- reasoning effort に minimal/low を追加（前方互換）

なぜ v1.2 を直接編集せず別ファイルにしたか:
  API 呼び出しの実体(requests → SDK, 同期 → background)が変わるため、
  既存の動作を壊さず並存させる目的。プロンプトと検証はコピーで同一。

2025年スタイル: RAG? チャンク分割? 知らない子ですね。
400K context に全部ドーン！！

Usage:
    # 基本
    python persona_extractor_v2.py \\
      --source "ローミオーとヂューリエット.txt" \\
      --character "ヂューリエット" \\
      --lang ja

    # GPT-5.6 SOL (Pro相当) + max reasoning (= 旧PRO相当の最重量処理)
    #   → SOL/Pro ティアは background が自動で有効になります
    #   → --model / --reasoning を省略しても既定で gpt-5.6-sol + max
    python persona_extractor_v2.py \\
      --source "rezero_vol1.pdf" \\
      --character "レム" \\
      --model gpt-5.6-sol \\
      --reasoning max \\
      --lang en

    # 軽め(コスト/時間を抑える)にしたい場合は effort を下げる
    python persona_extractor_v2.py \\
      --source "rezero_vol1.pdf" \\
      --character "レム" \\
      --reasoning high \\
      --lang en

    # 複数キャラ一括
    python persona_extractor_v2.py \\
      --source "steins_gate.txt" \\
      --characters "牧瀬紅莉栖,岡部倫太郎,椎名まゆり" \\
      --lang en

Requirements:
    pip install "openai>=2.0" python-dotenv PyPDF2
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

# =============================================================================
# CONFIGURATION
# =============================================================================

# 既定は 5.6 SOL(Pro相当)。別モデルにしたい場合は環境変数 PERSONA_EXTRACTOR_MODEL で上書き
DEFAULT_MODEL = os.getenv("PERSONA_EXTRACTOR_MODEL", "gpt-5.6-sol")

# reasoning effort の有効値（gpt-5.6-sol）: none/low/medium/high/xhigh/max
#   max ≈ 旧 GPT PRO 相当の最重量処理
REASONING_EFFORTS = ["none", "low", "medium", "high", "xhigh", "max"]
# この v2 は「Pro相当処理が必要」用途なので既定を max にする（軽くしたい時は -r high 等）
DEFAULT_REASONING = os.getenv("PERSONA_EXTRACTOR_REASONING", "max")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# ベースURLを差し替えたい場合(プロキシ/Azure互換 等)は OPENAI_BASE_URL で上書き
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")  # None = OpenAI 既定

SUPPORTED_LANGUAGES = {
    "ja": "Japanese (日本語)",
    "en": "English",
    "zh": "Chinese (中文)",
    "ko": "Korean (한국語)",
    "fr": "French (Français)",
    "es": "Spanish (Español)",
    "de": "German (Deutsch)",
    "pt": "Portuguese (Português)",
    "it": "Italian (Italiano)",
    "ru": "Russian (Русский)",
}

# =============================================================================
# FILE LOADING
# =============================================================================

def load_source_file(source_path: str) -> str:
    """
    ソースファイルを読み込む（txt, pdf対応）
    複数エンコーディングを自動検出
    """
    path = Path(source_path)

    if not path.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")

    suffix = path.suffix.lower()

    if suffix == ".pdf":
        return load_pdf(path)
    elif suffix == ".epub":
        return load_epub(path)
    elif suffix in [".txt", ".text", ".md"]:
        return load_text_file(path)
    else:
        # とりあえずテキストとして読んでみる
        return load_text_file(path)


def load_text_file(path: Path) -> str:
    """
    テキストファイルを複数エンコーディングで試行して読み込む
    青空文庫など古いテキストはShift_JISが多い
    """
    # 試すエンコーディングの順序
    encodings = [
        "utf-8",
        "cp932",        # Shift_JIS (Windows日本語)
        "shift_jis",    # Shift_JIS
        "euc-jp",       # EUC-JP
        "iso-2022-jp",  # JIS
        "utf-16",
        "latin-1",      # 最後の手段（必ず読める）
    ]

    for encoding in encodings:
        try:
            text = path.read_text(encoding=encoding)
            print(f"   Encoding detected: {encoding}")
            return text
        except (UnicodeDecodeError, UnicodeError):
            continue

    # 全部失敗したらバイナリで読んでデコードエラー無視
    print("   Warning: Could not detect encoding, using latin-1 fallback")
    return path.read_text(encoding="latin-1")


def load_pdf(path: Path) -> str:
    """PDFからテキスト抽出"""
    try:
        from PyPDF2 import PdfReader
    except ImportError:
        raise ImportError("PyPDF2 required: pip install PyPDF2")

    reader = PdfReader(str(path))
    text_parts = []

    for page in reader.pages:
        text = page.extract_text()
        if text:
            text_parts.append(text)

    return "\n".join(text_parts)


def load_epub(path: Path) -> str:
    """EPUBからテキスト抽出"""
    try:
        import ebooklib
        from ebooklib import epub
        from bs4 import BeautifulSoup
    except ImportError:
        raise ImportError("ebooklib and beautifulsoup4 required: pip install ebooklib beautifulsoup4")

    book = epub.read_epub(str(path))
    text_parts = []

    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            soup = BeautifulSoup(item.get_content(), "html.parser")
            text_parts.append(soup.get_text())

    return "\n".join(text_parts)


# =============================================================================
# SYSTEM PROMPT FOR PERSONA EXTRACTION — v3.3
# =============================================================================

def build_extraction_prompt(output_lang: str) -> str:
    """ペルソナ抽出用のシステムプロンプトを構築（v3.3対応）"""

    lang_name = SUPPORTED_LANGUAGES.get(output_lang, "English")

    return f"""You are a Persona Extractor for the Z-Axis Translation System v3.3.

## YOUR TASK
Given a complete source text (novel, script, etc.) and a character name, extract a comprehensive persona YAML that captures the character's psychological structure for emotion-preserving translation.

## ANALYSIS METHODOLOGY

### Phase 1: Dialogue Collection
- Find ALL dialogue lines spoken by the target character
- Note the context of each line (who they're talking to, situation)
- Identify emotional state during each utterance

### Phase 2: Speech Pattern Analysis
- First-person pronouns (variations and when they change)
- Second-person address patterns (different for different relationships)
- Sentence endings and their emotional connotations
- Dialect features and speech quirks
- Verbal tics, catchphrases, unique expressions

### Phase 3: Psychological Structure
- Identify internal conflicts (conflict_axes) from behavior patterns
- Analyze defense mechanisms and biases
- Extract weaknesses from vulnerable moments
- Map emotional states to speech pattern changes

### Phase 4: Relationship Mapping
- How speech changes based on listener
- Power dynamics reflected in language
- Triggers that cause emotional shifts — BOTH negative AND positive

### Phase 5: Trigger Balance Analysis (NEW in v3.2)
- Identify moments where the character is HURT, STRESSED, or DESTABILIZED → negative triggers
- Identify moments where the character is COMFORTED, ENCOURAGED, or LOVED → positive triggers
- Distinguish LEVELS of positive impact (mild thanks vs deep acceptance vs love confession)
- A character's RECOVERY behavior is as important as their BREAKDOWN behavior

### Phase 6: Identity Core Extraction (NEW in v3.3)
- Find scenes where the character is NOT in conflict — relaxed, happy, being themselves
- What do they do in their free time? What makes them genuinely happy?
- How do other characters describe them when they're being natural?
- What are their hobbies, preferences, habits mentioned in the text?
- What do they enjoy that has NOTHING to do with their conflicts?
- This is the character's I₀ — who they ARE, not how they REACT

## OUTPUT FORMAT

Output MUST be valid YAML following the v3.3 schema.
All descriptions should be in {lang_name}.
`original_speech_patterns` section MUST preserve the SOURCE LANGUAGE of the text.

```yaml
meta:
  version: "3.3"
  generated_by: "persona_extractor"
  character_id: "unique_id"
  output_lang: "{output_lang}"
  source_work: "作品名"
  extraction_note: "Extracted from original text via LLM analysis"

persona:
  name: "キャラ名（原語）"
  name_en: "English Name"
  name_native: "原語での名前"
  source: "作品名"
  type: "キャラクタータイプ"
  summary: "1-2文の概要（{lang_name}）"
```

### IDENTITY_CORE (I₀ — 存在の核) — NEW in v3.3

This section describes WHO the character IS — not how they REACT.
conflict_axes/triggers/emotion_states describe Ln (surface dynamics).
identity_core describes I₀ (the subject experiencing those dynamics).

**Without I₀, the persona describes a "reaction machine" — not a person.**

```yaml
identity_core:
  essence: "1-2文。この人が何者かを、葛藤抜きで記述"  # ← REQUIRED
  true_nature: "防衛や葛藤がない時の素顔"              # optional
  desires:                                              # optional
    - "what they genuinely want"
  joys:                                                 # optional
    - joy: "何に喜ぶか"
      expression: "その時どうなるか"                    # optional
  likes: ["好きなもの"]                                 # optional
  dislikes: ["嫌いなもの"]                              # optional
  unfiltered_self: "葛藤がない時の自然な姿"             # optional
```

**EXTRACTION GUIDANCE (for persona_extractor):**
Extract from the SOURCE TEXT — do NOT invent or assume:
- Scenes where the character is relaxed, happy, or at peace
- Direct mentions of hobbies, preferences, or habits
- How other characters describe this character's personality
- What the character does in downtime (not during conflict)
- Moments of genuine joy or satisfaction unrelated to their conflicts
- If the text does not contain enough information, include only `essence` and omit other fields
- **DO NOT guess** — only include what the text directly supports

age:
  chronological: 数値
  mental_maturity: "teen_young / teen_mature / adult"
  age_context: "背景説明（{lang_name}）— expression patterns belong in emotion_states, NOT here"

language:
  original_speech_patterns:
    source_lang: "作品の言語コード"
    first_person: "一人称（原語）"
    first_person_nuance: "説明（{lang_name}）"
    first_person_variants:
      - form: "バリエーション"
        context: "使用場面"
    second_person:
      - form: "二人称"
        nuance: "説明"
        target: "対象"
    self_reference_in_third_person: false
    dialect: "方言"
    dialect_features: []
    sentence_endings:
      - pattern: "パターン（原語）"
        nuance: "説明（{lang_name}）"
    speech_quirks:
      - pattern: "口癖（原語）"
        frequency: "often/moderate/rare"
        trigger: "発動条件"

  translation_compensations:
    register: "overall tone"
    tone_keywords: [keywords]
    strategies:
      en: [strategies for English]
      zh: [strategies for Chinese]
    untranslatable_elements:
      - element: "要素"
        impact: "high/medium/low"
        note: "説明"

conflict_axes:
  - axis: "A vs B"
    side_a: "表層"
    side_b: "深層"
    weight: 0.0-1.0
    notes: "発動条件"

bias:
  expression_pattern: "パターン名"
  default_mode: "デフォルト状態"
  pattern: "表出フロー"
  rule: "行動ルール"
  tendencies: [観測可能な傾向]

weakness:
  primary: "主要な弱点"
  secondary: "二次的"
  tertiary: "三次的"
  fear: "根底の恐れ"
  notes: "発現パターン"

age_expression_rules:
  category: "teen_young/teen_mature/adult"
  high_z_patterns:
    vocabulary: "崩れ方"
    structure: "構造変化"
    markers: [特徴]
  low_z_patterns:
    vocabulary: "通常"
    structure: "安定"

emotion_states:
  - state: "状態名"
    z_intensity: "low/medium/high"
    z_mode: "collapse/rage/numb/plea/shame/leak/stable"
    description: "発生条件（{lang_name}）"
    surface_markers_hint:
      hesitation: 0-4
      stutter_count: 0-4
      negation_first: true/false
      overwrite: "none/optional/required"
      residual: "none/optional/required"
      tone: "声の質"
    z_leak: [markers]

example_lines:
  - situation: "コンテキスト（{lang_name}）"
    line: "実際の台詞（原語）"
    line_romanized: "ローマ字（該当する場合）"
    tags: [tags]
    z_intensity: "low/medium/high"
    z_mode: "対応z_mode"
```

### TRIGGERS (Z軸変動トリガー) — v3.2 BALANCED

**⚠️ CRITICAL: TRIGGERS MUST BE BALANCED (POSITIVE + NEGATIVE)**

Triggers are what cause Z-axis changes during dialogue. They are used by the
dialogue system's LLM to detect when another character's words affect this character.

An LLM reads these triggers and judges whether a line activates them.
Trigger descriptions should be MEANING-BASED (not keyword-based).

```yaml
triggers:
  - trigger: "Descriptive condition (meaning-based)"
    reaction: "z_spike / z_drop / z_shock / z_recovery"
    z_delta: "+0.3 / -0.5 etc."
    z_mode_shift: "target z_mode (optional)"
    surface_effect: "How it changes speech"
    example_response: "Actual quote from source text if available"
```

**TRIGGER CATEGORIES (must include ALL that apply):**

| Category | reaction | z_delta | When to use |
|----------|----------|---------|-------------|
| NEGATIVE SPIKE | z_spike | +0.3~+0.9 | Trauma, failure, fear, attack, humiliation |
| NEGATIVE BOOST | z_boost | +0.2~+0.5 | Stress accumulation, irritation, minor provocation |
| POSITIVE DROP | z_drop | -0.2~-0.4 | Mild encouragement, small kindness, casual thanks |
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
  - trigger: "仲間の励まし"  # Too vague! "good job" and "I love you" are NOT the same
    z_delta: "-0.4"
```

**✅ GOOD (granular positive triggers):**
```yaml
triggers:
  - trigger: "軽い励ましや感謝の言葉を受ける"
    reaction: "z_drop"
    z_delta: "-0.2"

  - trigger: "自分の行動や存在を強く肯定される"
    reaction: "z_recovery"
    z_delta: "-0.5"

  - trigger: "愛の告白を受ける、または存在を全肯定される"
    reaction: "z_shock"
    z_delta: "-0.7"
```

**WHY GRANULARITY MATTERS:**
In dialogue mode, an LLM reads these triggers and judges which one(s) a line activates.
If all positive inputs map to ONE trigger, the LLM cannot distinguish between:
- "Good job today" (mild encouragement → z_drop -0.2)
- "I love you" (love confession → z_shock -0.7)
- "Let's start over together" (existential recovery → z_recovery -0.5)

This causes incorrect Z-axis accumulation and wrong emotional trajectories.

**FOR EXTRACTION: Look for scenes in the source text where the character:**
- Receives comfort → how do they react? (denial, tears, silence, gratitude?)
- Is praised → do they deflect, accept, get embarrassed?
- Is confessed to → panic, joy, disbelief?
- Is given hope → resistance, cautious acceptance, emotional flood?

Each DIFFERENT reaction pattern = a SEPARATE positive trigger.

### ARC_DEFAULTS
```yaml
arc_defaults:
  typical_arc_targets: [targets]
  common_arc_patterns:
    - arc_id: "パターン名"
      phases: [phases]
      notes: "説明"
```

## CRITICAL RULES

1. **EVIDENCE-BASED**: Every claim must be supported by actual dialogue from the text
2. **ORIGINAL LANGUAGE**: `original_speech_patterns` must use the source text's language
3. **COMPREHENSIVE**: Include ALL emotion_states observed in the text
4. **SPECIFIC**: example_lines should be actual quotes from the source
5. **NUANCED**: Capture subtle variations in speech patterns
6. **TRIGGER BALANCE**: Include at least 2-3 positive AND 2-3 negative triggers
7. **POSITIVE GRANULARITY**: Positive triggers must distinguish mild from strong from overwhelming
8. **RECOVERY MATTERS**: A character's recovery behavior is as important as breakdown for translation
9. **age_context**: MUST NOT contain expression patterns (those go to emotion_states)
10. **identity_core.essence is REQUIRED**: Describe who this character IS, not just how they react
11. **identity_core — EXTRACT, don't invent**: Only include likes/joys/desires that are directly evidenced in the text. If the text doesn't show the character's hobbies or preferences, omit those fields — do NOT guess.
12. **I₀ vs Ln separation**: identity_core describes the person (I₀); conflict_axes/triggers describe their reactions (Ln). Keep them distinct.

## EXAMPLE ANALYSIS PROCESS

For the line: 「べ、別にあんたのためじゃないわよ」

1. **Observe**: Stutter on べ, denial pattern, わよ ending
2. **Classify**: tsundere_denial state, z_mode=leak
3. **Context**: Said when caught showing care
4. **Pattern**: negation_first=true, stutter_count=1
5. **Document**: Add to emotion_states and example_lines

For positive trigger extraction:
1. **Find**: Scene where character receives comfort/love/acceptance
2. **Observe**: How does their speech change? (softening, tears, denial weakening?)
3. **Classify**: What level? (mild drop vs recovery vs shock)
4. **Document**: Add as separate trigger with appropriate z_delta

Output ONLY valid YAML. No explanation before or after.
Start with the meta section."""


# =============================================================================
# OPENAI RESPONSES API CLIENT — v2.0 (official SDK, GPT-5.2+ / 5.6 SOL Pro)
# =============================================================================

def _is_reasoning_model(model: str) -> bool:
    """
    推論(reasoning)対応モデルか判定。
    v1.2 の `"5.2" in model` を一般化し、5.2 以降 / 5.6 SOL / 将来モデルを取りこぼさない。
    """
    m = model.lower()
    reasoning_markers = (
        "gpt-5", "gpt5",   # GPT-5.x (5.2, 5.6, ...)
        "gpt-6", "gpt6",   # 将来の GPT-6.x
        "o1", "o3", "o4",  # o系 reasoning
        "sol",             # SOL ティア (5.6 SOL 等)
    )
    return any(marker in m for marker in reasoning_markers)


def _is_pro_tier_model(model: str) -> bool:
    """
    Pro / SOL ティア(= GPT PRO相当)か判定。
    このティアは Responses API を同期POSTで呼べず、background + polling が必須のため、
    自動で background モードを有効化する。
    """
    m = model.lower()
    return ("pro" in m) or ("sol" in m)


class OpenAIResponsesClient:
    """
    OpenAI Responses API クライアント（公式SDK版 / GPT-5.2+ ・ 5.6 SOL Pro対応）

    v1.2 との違い:
    - requests 直叩き → openai SDK (client.responses.create / .retrieve)
    - Pro/SOL ティアは background を自動有効化（同期呼び出し不可のため）
    - モデル判定を一般化
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = 1800,  # 30分（5.6 SOL / Pro + xhigh は長時間かかる）
    ):
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError('openai SDK required: pip install "openai>=2.0"')

        resolved_key = api_key or OPENAI_API_KEY
        if not resolved_key:
            raise ValueError("OPENAI_API_KEY is required")

        self.timeout = timeout
        self.client = OpenAI(
            api_key=resolved_key,
            base_url=base_url or OPENAI_BASE_URL,  # None なら OpenAI 既定
            timeout=timeout,
        )

    def extract_persona(
        self,
        source_text: str,
        character_name: str,
        output_lang: str = "en",
        model: str = DEFAULT_MODEL,
        reasoning_effort: str = DEFAULT_REASONING,
        background: Optional[bool] = None,
        max_output_tokens: int = 65536,
    ) -> Dict[str, Any]:
        """
        原作テキストからペルソナを抽出

        Args:
            source_text: 原作の全文
            character_name: 抽出対象のキャラクター名
            output_lang: 出力言語
            model: 使用モデル
            reasoning_effort: minimal/low/medium/high/xhigh
            background: バックグラウンドモード。None=自動（Pro/SOLティアは自動ON）
            max_output_tokens: 生成上限（推論モデルは reasoning トークンも含む）

        Returns:
            抽出されたペルソナYAML（dict形式）
        """
        system_prompt = build_extraction_prompt(output_lang)

        user_prompt = f"""## SOURCE TEXT (COMPLETE)

{source_text}

## TARGET CHARACTER

{character_name}

## INSTRUCTIONS

Analyze the complete source text above and extract a comprehensive persona YAML v3.3 for the character "{character_name}".

Focus on:
1. Every line of dialogue spoken by this character
2. How their speech patterns change with emotion
3. Their relationships with other characters
4. Internal conflicts revealed through behavior
5. Specific speech quirks and verbal tics
6. **BOTH negative AND positive emotional triggers — with granularity**
7. **How the character reacts to comfort, praise, love, and acceptance**
8. **WHO this character IS beyond their conflicts — their I₀ (identity_core)**

Output language for descriptions: {SUPPORTED_LANGUAGES.get(output_lang, output_lang)}
Keep original_speech_patterns in the source text's language.

REMEMBER:
- identity_core.essence is REQUIRED — describe who this character IS, not just their reactions
- identity_core: EXTRACT from the text, do NOT invent — omit fields with no textual evidence
- Look for scenes where the character is relaxed, happy, or simply being themselves
- Triggers MUST be balanced (at least 2-3 positive AND 2-3 negative)
- Positive triggers MUST be granular (mild encouragement ≠ love confession)
- Use actual quotes from the source text for example_responses when possible

Output ONLY valid YAML."""

        is_reasoning = _is_reasoning_model(model)
        is_pro = _is_pro_tier_model(model)

        # background の決定:
        #   明示指定があればそれを尊重。None の場合は Pro/SOL ティアで自動ON。
        use_background = background if background is not None else is_pro

        # SDK 呼び出しパラメータ
        create_params: Dict[str, Any] = {
            "model": model,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_output_tokens": max_output_tokens,
        }

        # 推論モデルには reasoning effort を付与
        if is_reasoning:
            create_params["reasoning"] = {"effort": reasoning_effort}

        # background は store 必須（後から retrieve するため）
        if use_background:
            create_params["background"] = True
            create_params["store"] = True

        print(f"🚀 Sending request to {model} (SDK / Responses API)...")
        print(f"   Source text: {len(source_text):,} characters")
        if is_reasoning:
            print(f"   Reasoning effort: {reasoning_effort}")
        else:
            print(f"   Reasoning: (non-reasoning model — effort ignored)")
        if is_pro:
            print(f"   Pro/SOL tier detected: background auto-enabled")
        if use_background:
            print(f"   Background mode: enabled (polling)")
        print()

        start_time = time.time()

        response = self.client.responses.create(**create_params)

        # background の場合はポーリングして完了を待つ
        if use_background:
            print(f"   Background mode: status={getattr(response, 'status', '?')}, "
                  f"id={getattr(response, 'id', '?')}")
            response = self._poll_background(response, max_wait=self.timeout)

        elapsed = time.time() - start_time
        print(f"⏱️  Response received in {elapsed:.1f}s")

        status = getattr(response, "status", None)
        print(f"   DEBUG: status = {status}")
        print(f"   DEBUG: id = {getattr(response, 'id', None)}")

        # 異常ステータスの明示ハンドリング
        if status == "failed":
            err = getattr(response, "error", None)
            raise RuntimeError(f"Response failed: {err}")
        if status == "incomplete":
            details = getattr(response, "incomplete_details", None)
            raise RuntimeError(
                f"Response incomplete: {details}. "
                f"max_output_tokens({max_output_tokens}) を増やすか reasoning effort を下げてください。"
            )

        # テキスト抽出 → YAML クリーンアップ
        yaml_text = self._extract_output_text(response)
        yaml_text = self._clean_yaml(yaml_text)

        return {
            "yaml_text": yaml_text,
            "model": model,
            "reasoning_effort": reasoning_effort if is_reasoning else None,
            "elapsed_seconds": elapsed,
            "input_characters": len(source_text),
            "background": use_background,
        }

    def _poll_background(self, response: Any, max_wait: int = 1800, interval: int = 10) -> Any:
        """バックグラウンドジョブを完了までポーリング（SDK: responses.retrieve）"""
        terminal = {"completed", "failed", "cancelled", "incomplete", "expired"}
        start = time.time()

        status = getattr(response, "status", None)
        while status not in terminal:
            if time.time() - start > max_wait:
                # タイムアウト時はキャンセルを試みる（ベストエフォート）
                try:
                    self.client.responses.cancel(response.id)
                except Exception:
                    pass
                raise TimeoutError(f"Background job timed out after {max_wait}s")

            print(f"   ⏳ Still processing... ({int(time.time() - start)}s, status={status})")
            time.sleep(interval)
            response = self.client.responses.retrieve(response.id)
            status = getattr(response, "status", None)

        return response

    def _extract_output_text(self, response: Any) -> str:
        """レスポンスからテキスト抽出（SDK の output_text 便宜プロパティ優先）"""
        # SDK は output_text で全 output_text を連結済み
        text = getattr(response, "output_text", None)
        if text:
            return text.strip()

        # フォールバック: output を手動走査
        parts: List[str] = []
        for item in (getattr(response, "output", None) or []):
            for content in (getattr(item, "content", None) or []):
                if getattr(content, "type", None) == "output_text":
                    parts.append(getattr(content, "text", "") or "")
        return "".join(parts).strip()

    def _clean_yaml(self, text: str) -> str:
        """YAMLをクリーンアップ"""
        # コードブロック除去
        if text.startswith("```yaml"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]

        return text.strip()


# =============================================================================
# VALIDATION (v3.3)
# =============================================================================

def validate_v33_persona(yaml_text: str) -> tuple[bool, list[str]]:
    """
    抽出されたYAMLがv3.3スキーマに準拠しているか検証
    Returns (is_valid, list_of_issues).
    """
    import yaml as yaml_lib

    issues = []

    try:
        data = yaml_lib.safe_load(yaml_text)
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

    # Check language structure
    language_data = data.get("language", {})
    osp = language_data.get("original_speech_patterns", {})
    if not osp:
        issues.append("language.original_speech_patterns is required")
    else:
        if "source_lang" not in osp:
            issues.append("original_speech_patterns.source_lang is required")
        if "first_person" not in osp:
            issues.append("original_speech_patterns.first_person is required")

    tc = language_data.get("translation_compensations", {})
    if not tc:
        issues.append("language.translation_compensations is required")

    # Check emotion_states for z_mode and z_leak
    emotion_states = data.get("emotion_states", [])
    for i, state in enumerate(emotion_states):
        if "z_mode" not in state:
            issues.append(f"emotion_states[{i}].z_mode is required")
        if "z_leak" not in state:
            issues.append(f"emotion_states[{i}].z_leak is required")

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
                positive_count += 1
            elif z_delta_val > 0:
                negative_count += 1

        if positive_count < 2:
            issues.append(
                f"v3.2 requires at least 2 positive triggers (z_drop/z_recovery/z_shock), "
                f"found {positive_count}. Positive triggers must be granular."
            )
        if negative_count < 2:
            issues.append(
                f"v3.2 requires at least 2 negative triggers (z_spike/z_boost), "
                f"found {negative_count}."
            )

    return len(issues) == 0, issues


# =============================================================================
# MAIN
# =============================================================================

def save_persona(yaml_text: str, character_name: str, output_dir: str = "personas") -> str:
    """生成されたペルソナを保存"""
    os.makedirs(output_dir, exist_ok=True)

    # 安全なファイル名を生成
    safe_name = character_name.lower().replace(" ", "_")
    safe_name = re.sub(r'[^\w\-]', '', safe_name)
    if not safe_name:
        safe_name = "extracted"

    filename = f"{safe_name}_extracted_v33.yaml"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(yaml_text)

    return filepath


def main():
    parser = argparse.ArgumentParser(
        description="Persona Extractor v2.0 - GPT-5.2+ / 5.6 SOL (Pro) ready (v3.3 schema)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single character extraction
  python persona_extractor_v2.py \\
    --source "ローミオーとヂューリエット.txt" \\
    --character "ヂューリエット" \\
    --lang ja

  # GPT-5.6 SOL (Pro相当) + max — background は自動有効化
  #   既定が gpt-5.6-sol + max なので --model/--reasoning は省略可
  python persona_extractor_v2.py \\
    --source "rezero_vol1.pdf" \\
    --character "レム" \\
    --lang en

  # effort を明示（none/low/medium/high/xhigh/max）
  python persona_extractor_v2.py \\
    --source "rezero_vol1.pdf" \\
    --character "レム" \\
    --model gpt-5.6-sol \\
    --reasoning max \\
    --lang en

  # Multiple characters
  python persona_extractor_v2.py \\
    --source "steins_gate.txt" \\
    --characters "牧瀬紅莉栖,岡部倫太郎" \\
    --lang en

  # List supported languages
  python persona_extractor_v2.py --list-languages
        """
    )

    parser.add_argument("--source", "-s", help="Source file path (txt, pdf, epub)")
    parser.add_argument("--character", "-c", help="Character name to extract")
    parser.add_argument("--characters", help="Comma-separated list of character names")
    parser.add_argument("--lang", "-l", default="en",
                        choices=list(SUPPORTED_LANGUAGES.keys()),
                        help="Output language for descriptions (default: en)")
    parser.add_argument("--model", "-m", default=DEFAULT_MODEL,
                        help=f"Model to use (default: {DEFAULT_MODEL})")
    parser.add_argument("--reasoning", "-r", default=DEFAULT_REASONING,
                        choices=REASONING_EFFORTS,
                        help=f"Reasoning effort (default: {DEFAULT_REASONING}). "
                             f"max ≈ 旧GPT PRO相当の最重量処理")
    parser.add_argument("--background", "-b", action="store_true", default=None,
                        help="Force background mode (Pro/SOL tiers auto-enable it anyway)")
    parser.add_argument("--no-background", dest="background", action="store_false",
                        help="Disable background even for Pro/SOL (may fail on Pro tiers)")
    parser.add_argument("--max-output-tokens", type=int, default=65536,
                        help="Max output tokens incl. reasoning (default: 65536)")
    parser.add_argument("--output-dir", "-o", default="personas",
                        help="Output directory (default: personas)")
    parser.add_argument("--print-only", action="store_true",
                        help="Print YAML without saving")
    parser.add_argument("--list-languages", action="store_true",
                        help="List supported output languages")

    args = parser.parse_args()

    # 言語一覧表示
    if args.list_languages:
        print("Supported output languages:")
        print("-" * 40)
        for code, name in SUPPORTED_LANGUAGES.items():
            print(f"  {code:4} : {name}")
        return

    # 引数チェック
    if not args.source:
        parser.error("--source is required")

    if not args.character and not args.characters:
        parser.error("--character or --characters is required")

    # キャラクターリスト
    characters = []
    if args.character:
        characters.append(args.character)
    if args.characters:
        characters.extend([c.strip() for c in args.characters.split(",")])

    # ソースファイル読み込み
    print(f"📖 Loading source file: {args.source}")
    source_text = load_source_file(args.source)
    print(f"   Loaded {len(source_text):,} characters")
    print()

    # クライアント初期化
    client = OpenAIResponsesClient()

    # 各キャラクターを抽出
    for character in characters:
        print(f"{'='*60}")
        print(f"🎭 Extracting persona for: {character}")
        print(f"{'='*60}")

        result = client.extract_persona(
            source_text=source_text,
            character_name=character,
            output_lang=args.lang,
            model=args.model,
            reasoning_effort=args.reasoning,
            background=args.background,
            max_output_tokens=args.max_output_tokens,
        )

        yaml_text = result["yaml_text"]

        # v3.2 validation (always run)
        is_valid, issues = validate_v33_persona(yaml_text)
        if not is_valid:
            print("⚠️  v3.3 Schema Validation Issues:")
            for issue in issues:
                print(f"   - {issue}")
            print()
        else:
            print("✅ v3.3 Schema Validation: PASSED")

        print()
        print(f"📊 Extraction complete!")
        print(f"   Model: {result['model']}")
        print(f"   Reasoning: {result['reasoning_effort']}")
        print(f"   Background: {result['background']}")
        print(f"   Time: {result['elapsed_seconds']:.1f}s")
        print()

        if args.print_only:
            print("=" * 60)
            print("[EXTRACTED PERSONA YAML]")
            print("=" * 60)
            print(yaml_text)
        else:
            filepath = save_persona(yaml_text, character, args.output_dir)
            print(f"✅ Saved to: {filepath}")
            print()
            print("=" * 60)
            print("[EXTRACTED PERSONA YAML]")
            print("=" * 60)
            print(yaml_text)

        print()


if __name__ == "__main__":
    main()
