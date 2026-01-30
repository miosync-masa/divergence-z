#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Persona Extractor v1.0
原作テキスト/PDFから直接キャラクターペルソナを抽出

2025年スタイル: RAG? チャンク分割? 知らない子ですね。
400K context に全部ドーン！！

Usage:
    # 基本
    python persona_extractor.py \
      --source "ローミオーとヂューリエット.txt" \
      --character "ヂューリエット" \
      --lang ja

    # GPT-5.2 Pro + xhigh reasoning
    python persona_extractor.py \
      --source "rezero_vol1.pdf" \
      --character "レム" \
      --model gpt-5.2-pro \
      --reasoning xhigh \
      --lang en

    # 複数キャラ一括
    python persona_extractor.py \
      --source "steins_gate.txt" \
      --characters "牧瀬紅莉栖,岡部倫太郎,椎名まゆり" \
      --lang en

Requirements:
    pip install openai python-dotenv PyPDF2
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

DEFAULT_MODEL = os.getenv("PERSONA_EXTRACTOR_MODEL", "gpt-5.2-pro")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

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
# SYSTEM PROMPT FOR PERSONA EXTRACTION
# =============================================================================

def build_extraction_prompt(output_lang: str) -> str:
    """ペルソナ抽出用のシステムプロンプトを構築"""
    
    lang_name = SUPPORTED_LANGUAGES.get(output_lang, "English")
    
    return f"""You are a Persona Extractor for the Z-Axis Translation System v3.1.

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
- Triggers that cause emotional shifts

## OUTPUT FORMAT

Output MUST be valid YAML following the v3.1 schema.
All descriptions should be in {lang_name}.
`original_speech_patterns` section MUST preserve the SOURCE LANGUAGE of the text.

```yaml
meta:
  version: "3.1"
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

age:
  chronological: 数値
  mental_maturity: "teen_young / teen_mature / adult"
  age_context: "背景説明（{lang_name}）"

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
      # etc.
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

triggers:
  - trigger: "トリガー"
    reaction: "z_spike/z_drop/z_boost/z_stable"
    z_delta: "+0.3 etc."
    z_mode_shift: "シフト先"
    surface_effect: "発話への影響"
    example_response: "実際の台詞"

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

## EXAMPLE ANALYSIS PROCESS

For the line: 「べ、別にあんたのためじゃないわよ」

1. **Observe**: Stutter on べ, denial pattern, わよ ending
2. **Classify**: tsundere_denial state, z_mode=leak
3. **Context**: Said when caught showing care
4. **Pattern**: negation_first=true, stutter_count=1
5. **Document**: Add to emotion_states and example_lines

Output ONLY valid YAML. No explanation before or after.
Start with the meta section."""


# =============================================================================
# OPENAI RESPONSES API CLIENT
# =============================================================================

class OpenAIResponsesClient:
    """OpenAI Responses API クライアント（GPT-5.2 Pro対応）"""
    
    def __init__(
        self, 
        api_key: Optional[str] = None,
        base_url: str = "https://api.openai.com/v1",
        timeout: int = 1800,  # 30分に延長（5.2 Pro + xhigh は時間かかる）
    ):
        self.api_key = api_key or OPENAI_API_KEY
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is required")
    
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
    
    def extract_persona(
        self,
        source_text: str,
        character_name: str,
        output_lang: str = "en",
        model: str = DEFAULT_MODEL,
        reasoning_effort: str = "high",
        background: bool = False,
    ) -> Dict[str, Any]:
        """
        原作テキストからペルソナを抽出
        
        Args:
            source_text: 原作の全文
            character_name: 抽出対象のキャラクター名
            output_lang: 出力言語
            model: 使用モデル
            reasoning_effort: medium/high/xhigh
            background: バックグラウンドモードを使用するか
        
        Returns:
            抽出されたペルソナYAML（dict形式）
        """
        import requests
        
        system_prompt = build_extraction_prompt(output_lang)
        
        user_prompt = f"""## SOURCE TEXT (COMPLETE)

{source_text}

## TARGET CHARACTER

{character_name}

## INSTRUCTIONS

Analyze the complete source text above and extract a comprehensive persona YAML v3.1 for the character "{character_name}".

Focus on:
1. Every line of dialogue spoken by this character
2. How their speech patterns change with emotion
3. Their relationships with other characters
4. Internal conflicts revealed through behavior
5. Specific speech quirks and verbal tics

Output language for descriptions: {SUPPORTED_LANGUAGES.get(output_lang, output_lang)}
Keep original_speech_patterns in the source text's language.

Output ONLY valid YAML."""

        # リクエストペイロード構築
        payload = {
            "model": model,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_output_tokens": 16000,
        }
        
        # reasoning対応モデルの場合
        if "5.2" in model or "o1" in model or "o3" in model:
            payload["reasoning"] = {"effort": reasoning_effort}
        
        # バックグラウンドモード
        if background:
            payload["background"] = True
        
        print(f"🚀 Sending request to {model}...")
        print(f"   Source text: {len(source_text):,} characters")
        print(f"   Reasoning effort: {reasoning_effort}")
        if background:
            print(f"   Background mode: enabled")
        print()
        
        url = f"{self.base_url}/responses"
        
        start_time = time.time()
        
        response = requests.post(
            url,
            headers=self._headers(),
            json=payload,
            timeout=self.timeout,
        )
        
        elapsed = time.time() - start_time
        print(f"⏱️  Response received in {elapsed:.1f}s")
        
        if response.status_code != 200:
            raise RuntimeError(f"API error: {response.status_code} {response.text}")
        
        result = response.json()
        
        # デバッグ: レスポンス構造確認
        print(f"   DEBUG: status = {result.get('status')}")
        print(f"   DEBUG: id = {result.get('id')}")
        print(f"   DEBUG: keys = {list(result.keys())}")
        
        # バックグラウンドモードの場合はポーリング
        if background:
            status = result.get("status")
            response_id = result.get("id")
            print(f"   Background mode: status={status}, id={response_id}")
            
            if status in ["in_progress", "queued", "pending"]:
                print(f"   Starting polling...")
                result = self._poll_background(response_id)
            elif status == "completed":
                print(f"   Already completed!")
            else:
                print(f"   Unknown status, attempting to extract output anyway...")
        
        # レスポンスからテキスト抽出
        yaml_text = self._extract_output_text(result)
        
        # YAMLパース
        yaml_text = self._clean_yaml(yaml_text)
        
        return {
            "yaml_text": yaml_text,
            "model": model,
            "reasoning_effort": reasoning_effort,
            "elapsed_seconds": elapsed,
            "input_characters": len(source_text),
        }
    
    def _poll_background(self, response_id: str, max_wait: int = 600) -> Dict[str, Any]:
        """バックグラウンドジョブをポーリング"""
        import requests
        
        url = f"{self.base_url}/responses/{response_id}"
        start = time.time()
        
        while time.time() - start < max_wait:
            response = requests.get(url, headers=self._headers())
            result = response.json()
            
            status = result.get("status")
            if status == "completed":
                return result
            elif status == "failed":
                raise RuntimeError(f"Background job failed: {result}")
            
            print(f"   ⏳ Still processing... ({int(time.time() - start)}s)")
            time.sleep(10)
        
        raise TimeoutError("Background job timed out")
    
    def _extract_output_text(self, result: Dict[str, Any]) -> str:
        """レスポンスからテキスト抽出"""
        output_parts = []
        
        for item in result.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    output_parts.append(content.get("text", ""))
        
        return "".join(output_parts).strip()
    
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
    
    filename = f"{safe_name}_extracted_v31.yaml"
    filepath = os.path.join(output_dir, filename)
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(yaml_text)
    
    return filepath


def main():
    parser = argparse.ArgumentParser(
        description="Persona Extractor v1.0 - Extract character persona from source text",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single character extraction
  python persona_extractor.py \\
    --source "ローミオーとヂューリエット.txt" \\
    --character "ヂューリエット" \\
    --lang ja

  # With GPT-5.2 Pro and xhigh reasoning
  python persona_extractor.py \\
    --source "rezero_vol1.pdf" \\
    --character "レム" \\
    --model gpt-5.2-pro \\
    --reasoning xhigh \\
    --lang en

  # Multiple characters
  python persona_extractor.py \\
    --source "steins_gate.txt" \\
    --characters "牧瀬紅莉栖,岡部倫太郎" \\
    --lang en

  # List supported languages
  python persona_extractor.py --list-languages
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
    parser.add_argument("--reasoning", "-r", default="high",
                        choices=["medium", "high", "xhigh"],
                        help="Reasoning effort level (default: high)")
    parser.add_argument("--background", "-b", action="store_true",
                        help="Use background mode for long-running requests")
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
        )
        
        yaml_text = result["yaml_text"]
        
        print()
        print(f"📊 Extraction complete!")
        print(f"   Model: {result['model']}")
        print(f"   Reasoning: {result['reasoning_effort']}")
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
