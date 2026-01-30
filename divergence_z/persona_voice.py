#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Persona Voice Mode v1.0
Spirit Arrival Engine — 「意志を声に変換する」

Opus 4.5 Extended Thinking を使用して、
任意の入力をキャラクターの声（Spirit）に変換する。

Usage:
    # 基本使用
    python persona_voice.py \
      --persona personas/ヂューリエット_extracted_v31.yaml \
      --input "既読無視しないで！" \
      --context "LINEで連絡したが3時間返事がない"

    # 相手ペルソナ指定
    python persona_voice.py \
      --persona personas/ヂューリエット_extracted_v31.yaml \
      --input "既読無視しないで！" \
      --context "LINEで連絡したが3時間返事がない" \
      --target-persona personas/ロミオ.yaml

    # カスタム思考STEPを使用
    python persona_voice.py \
      --persona personas/kurisu_v3.yaml \
      --input "ちょっと待ってよ" \
      --context "岡部が急に実験を始めようとした" \
      --thinking-steps steps/response_step.txt

    # 思考過程を表示
    python persona_voice.py \
      --persona personas/subaru_v3.yaml \
      --input "もう無理..." \
      --context "白鯨戦で仲間を失った直後" \
      --show-thinking
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

# =============================================================================
# Configuration
# =============================================================================

DEFAULT_MODEL = "claude-opus-4-5-20251101"
DEFAULT_BUDGET_TOKENS = 10000  # Extended Thinking の budget

# デフォルトの応答STEP（組み込み）
DEFAULT_THINKING_STEPS = """
【STEP 1: 文脈と前提情報の把握】
- Query: ユーザーの入力（現代的な発話）
- Context: 提供された背景情報
- Self: ペルソナYAMLから自分のキャラクター情報
- Relation: ターゲットペルソナとの関係性

【STEP 2: 入力の意図（Intent）の解析】
- この発話で何を伝えたいのか
- 表層的な意味と深層的な意図を区別

【STEP 3: 意思（Will）の推論】
- 「なぜ」この発話をするのか
- 複数の意思が競合する場合はすべて列挙

【STEP 4: 感情の特定】
- 現在の感情を特定（0.00〜1.00で数値化）
- 複数の感情が共存する場合はすべて列挙
- ペルソナの triggers をチェックし、発火するものを特定

【STEP 5: テンソル更新】
感情テンソルを更新：
- Λ（意味密度）: 現在感じている意味の濃度
- ΛF（進行方向）: 感情が誰に向いているか
- ρT（テンション密度）: 感情の高まり
- σₛ（共鳴率）: 相手との共鳴度
- ΔΛC（拍動）: 感情が結晶化する瞬間があるか

【STEP 6: 自分の意思（Will）の推論】
- 生成された感情から「どうしたいか」を推論
- ペルソナの bias, conflict_axes を参照

【STEP 6.5: 葛藤テンソルの生成】
- 複数の意思が競合する場合、葛藤を評価
- Ξ_intensity: 葛藤の強さ
- Ξ_axes: 競合する軸
- Ξ_resolution: 解決モード（妥協/回避/爆発/転位/ユーモア化）

【STEP 7: 応答候補の生成】
- ペルソナの language 情報を参照
  - first_person（一人称）
  - sentence_endings（語尾）
  - speech_quirks（口癖）
- emotion_states から該当する z_mode, z_leak を適用
- 複数の候補を生成

【STEP 8: メタ認知的検証】
- 生成した応答が「このキャラらしいか」を検証
- ペルソナの bias, tendencies と整合性を確認

【STEP 9: 最終出力の調整】
- 最も「このキャラらしい」応答を選択
- z_leak マーカーを適切に適用
  - stutter: 言い淀み
  - ellipsis: 途切れ
  - repetition: 繰り返し
  - negation_first: 否定先行
  - trailing: 尻すぼみ
"""


# =============================================================================
# Helper Functions
# =============================================================================

def load_yaml_file(path: str) -> Dict[str, Any]:
    """YAMLファイルを読み込む"""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    
    # 複数エンコーディング対応
    encodings = ["utf-8", "cp932", "shift_jis", "euc-jp"]
    for encoding in encodings:
        try:
            text = file_path.read_text(encoding=encoding)
            return yaml.safe_load(text)
        except (UnicodeDecodeError, UnicodeError):
            continue
    
    raise ValueError(f"Could not decode file: {path}")


def load_text_file(path: str) -> str:
    """テキストファイルを読み込む"""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    
    encodings = ["utf-8", "cp932", "shift_jis", "euc-jp"]
    for encoding in encodings:
        try:
            return file_path.read_text(encoding=encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
    
    return file_path.read_text(encoding="latin-1")


def format_persona_summary(persona_data: Dict[str, Any]) -> str:
    """ペルソナYAML（全体を渡す）"""
    return yaml.dump(persona_data, allow_unicode=True, default_flow_style=False)


def format_target_persona_summary(persona_data: Dict[str, Any]) -> str:
    """相手ペルソナ（YAML全体を渡す）"""
    return yaml.dump(persona_data, allow_unicode=True, default_flow_style=False)


# =============================================================================
# Persona Voice Transform
# =============================================================================

def build_system_prompt(
    persona_data: Dict[str, Any],
    thinking_steps: str,
    target_persona_data: Optional[Dict[str, Any]] = None,
) -> str:
    """システムプロンプトを構築"""
    
    persona_summary = format_persona_summary(persona_data)
    
    target_section = ""
    if target_persona_data:
        target_summary = format_target_persona_summary(target_persona_data)
        target_section = f"""
{target_summary}
"""
    
    system_prompt = f"""あなたは「Persona Voice Transform Engine」です。

## あなたの役割
与えられた入力（現代的な発話）を、指定されたキャラクターの「声」に変換します。
これは単なる言い換えではなく、キャラクターの心理構造、葛藤、感情パターンを
すべて考慮した「Spirit の変換」です。

## キャラクター情報（Self）
{persona_summary}
{target_section}

## 思考プロセス（STEP）
以下のSTEPに従って、Extended Thinking で段階的に思考してください。
各STEPを明示的に実行し、最終的な出力を生成してください。

{thinking_steps}

## 出力形式
最終的な変換結果を以下の形式で出力してください：

【変換結果】
（キャラクターの声に変換されたテキスト）

【適用された z_mode】
（例: collapse, leak, rage, plea, shame, numb, stable）

【適用された z_leak】
（例: stutter, ellipsis, repetition, negation_first 等）

【感情テンソル】
- Λ（意味密度）: X.XX
- ρT（テンション密度）: X.XX
- σₛ（共鳴率）: X.XX

## 重要な注意
- キャラクターの一人称、語尾、口癖を必ず使用すること
- emotion_states と triggers を参照し、適切な z_mode を選択すること
- 葛藤がある場合は、bias のパターンに従って解決すること
- 「それっぽい」ではなく「構造的に正しい」変換を行うこと
"""
    
    return system_prompt


def transform_voice(
    client: Anthropic,
    persona_data: Dict[str, Any],
    input_text: str,
    context: str,
    thinking_steps: str,
    target_persona_data: Optional[Dict[str, Any]] = None,
    model: str = DEFAULT_MODEL,
    budget_tokens: int = DEFAULT_BUDGET_TOKENS,
    show_thinking: bool = False,
) -> Dict[str, Any]:
    """
    入力テキストをキャラクターの声に変換する
    
    Args:
        client: Anthropic client
        persona_data: キャラクターのペルソナYAML
        input_text: 変換する入力テキスト
        context: 背景情報
        thinking_steps: 思考STEPのテキスト
        target_persona_data: 相手キャラクターのペルソナYAML（optional）
        model: 使用するモデル
        budget_tokens: Extended Thinking の budget
        show_thinking: 思考過程を表示するか
    
    Returns:
        変換結果を含む辞書
    """
    
    system_prompt = build_system_prompt(
        persona_data=persona_data,
        thinking_steps=thinking_steps,
        target_persona_data=target_persona_data,
    )
    
    # ユーザーメッセージ
    target_info = ""
    if target_persona_data:
        target_name = target_persona_data.get("persona", {}).get("name", "相手")
        target_info = f"\n【発話相手】{target_name}"
    
    user_message = f"""以下の入力をキャラクターの声に変換してください。

【背景/状況】
{context}
{target_info}

【入力（現代的な発話）】
「{input_text}」

Extended Thinking で各STEPを実行し、最終的な変換結果を出力してください。
"""
    
    # API呼び出し（Extended Thinking）
    response = client.messages.create(
        model=model,
        max_tokens=16000,
        thinking={
            "type": "enabled",
            "budget_tokens": budget_tokens,
        },
        system=system_prompt,
        messages=[
            {"role": "user", "content": user_message}
        ],
    )
    
    # レスポンス解析
    thinking_content = ""
    text_content = ""
    
    for block in response.content:
        if block.type == "thinking":
            thinking_content = block.thinking
        elif block.type == "text":
            text_content = block.text
    
    result = {
        "input": input_text,
        "context": context,
        "output": text_content,
        "thinking": thinking_content if show_thinking else "[--show-thinking で表示]",
        "model": model,
        "budget_tokens": budget_tokens,
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        }
    }
    
    return result


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Persona Voice Mode v1.0 — Spirit Arrival Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 基本使用
  python persona_voice.py \\
    --persona personas/ヂューリエット_extracted_v31.yaml \\
    --input "既読無視しないで！" \\
    --context "LINEで連絡したが3時間返事がない"

  # 相手ペルソナ指定
  python persona_voice.py \\
    --persona personas/kurisu_v3.yaml \\
    --input "ちょっと待ってよ" \\
    --context "岡部が急に実験を始めようとした" \\
    --target-persona personas/okabe.yaml

  # カスタム思考STEP使用
  python persona_voice.py \\
    --persona personas/subaru_v3.yaml \\
    --input "もう無理..." \\
    --context "白鯨戦で仲間を失った直後" \\
    --thinking-steps steps/custom_step.txt

  # 思考過程を表示
  python persona_voice.py \\
    --persona personas/ヂューリエット_extracted_v31.yaml \\
    --input "好き" \\
    --context "バルコニーでロミオと二人きり" \\
    --show-thinking
        """
    )
    
    parser.add_argument("--persona", "-p", required=True,
                        help="キャラクターのペルソナYAMLファイル")
    parser.add_argument("--input", "-i", required=True,
                        help="変換する入力テキスト（現代的な発話）")
    parser.add_argument("--context", "-c", required=True,
                        help="背景情報/状況")
    parser.add_argument("--target-persona", "-t",
                        help="相手キャラクターのペルソナYAML（optional）")
    parser.add_argument("--thinking-steps", "-s",
                        help="カスタム思考STEPのテキストファイル")
    parser.add_argument("--model", "-m", default=DEFAULT_MODEL,
                        help=f"使用するモデル（default: {DEFAULT_MODEL}）")
    parser.add_argument("--budget", "-b", type=int, default=DEFAULT_BUDGET_TOKENS,
                        help=f"Extended Thinking の budget tokens（default: {DEFAULT_BUDGET_TOKENS}）")
    parser.add_argument("--show-thinking", action="store_true",
                        help="Extended Thinking の思考過程を表示")
    parser.add_argument("--output", "-o",
                        help="結果をJSONファイルに出力")
    
    args = parser.parse_args()
    
    # ペルソナ読み込み
    print(f"🎭 Loading persona: {args.persona}")
    persona_data = load_yaml_file(args.persona)
    persona_name = persona_data.get("persona", {}).get("name", "Unknown")
    print(f"   Character: {persona_name}")
    
    # ターゲットペルソナ読み込み（optional）
    target_persona_data = None
    if args.target_persona:
        print(f"🎭 Loading target persona: {args.target_persona}")
        target_persona_data = load_yaml_file(args.target_persona)
        target_name = target_persona_data.get("persona", {}).get("name", "Unknown")
        print(f"   Target: {target_name}")
    
    # 思考STEP読み込み
    if args.thinking_steps:
        print(f"📝 Loading thinking steps: {args.thinking_steps}")
        thinking_steps = load_text_file(args.thinking_steps)
    else:
        print("📝 Using default thinking steps")
        thinking_steps = DEFAULT_THINKING_STEPS
    
    # 変換実行
    print()
    print("=" * 60)
    print(f"🔮 Transforming voice...")
    print(f"   Input: 「{args.input}」")
    print(f"   Context: {args.context}")
    print(f"   Model: {args.model}")
    print(f"   Budget: {args.budget} tokens")
    print("=" * 60)
    print()
    
    client = Anthropic(timeout=600.0)  # 10 minutes for Extended Thinking
    
    result = transform_voice(
        client=client,
        persona_data=persona_data,
        input_text=args.input,
        context=args.context,
        thinking_steps=thinking_steps,
        target_persona_data=target_persona_data,
        model=args.model,
        budget_tokens=args.budget,
        show_thinking=args.show_thinking,
    )
    
    # 結果表示
    print("=" * 60)
    print("✨ TRANSFORMATION RESULT")
    print("=" * 60)
    print()
    print(result["output"])
    print()
    
    if args.show_thinking and result.get("thinking"):
        print("=" * 60)
        print("🧠 EXTENDED THINKING")
        print("=" * 60)
        print(result["thinking"])
        print()
    
    print("=" * 60)
    print(f"📊 Usage: {result['usage']['input_tokens']} input + {result['usage']['output_tokens']} output tokens")
    print("=" * 60)
    
    # JSON出力
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"✅ Result saved to: {args.output}")


if __name__ == "__main__":
    main()
