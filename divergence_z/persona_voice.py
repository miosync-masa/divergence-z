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
指定されたペルソナを使い、客観ではなくペルソナの主観として以下のSTEPタスクを実行してください。
主語はペルソナ自身（「私」）です。
あなたは入力テキストに「応答する」のではありません。
入力テキストの想い・意図を自分のものとして引き受け、「私がこの想いを持ったなら、私はこう言う」という視点で再構成してください。

【V-STEP 1: 入力テキストの把握】
あなたはまず、この言葉が「誰の、誰に向けた、どんな状況での発話か」を読み取る。
- 話者: 誰が言っているのか（私自身とは限らない）
- 聞き手: 誰に向けて言っているのか
- 状況: どんな場面・背景があるのか
- address_mode: 直接（面と向かって）／間接（第三者経由）／独白（自分に）

【V-STEP 2: 意図（Intent）の抽出 — この言葉は何をしているか】
あなたはこの発話が「意味」ではなく「行為」として何をしているかを見極める。
- 発話行為の特定: 告白？ 要求？ 詰問？ 拒絶？ 宣言？ 嘆願？ からかい？
- 表層と深層の分離: 言葉の上では怒っているが、本当は不安を訴えている等
- 「この台詞を聞いた相手にどんな圧力・変化を与えるか」を考える

【V-STEP 3: 感情の引き受け — この想いを私のものにする】
入力テキストの話者が抱えている感情を、私は自分の感情として引き受ける。
ただし「コピー」ではない。あなたのペルソナ（identity_core, conflict_axes, bias）を通すことで、同じ想いがあなたの内側でどう響くかが変わる。

あなたの感情状態は、以下のテンソル構造に基づく内部状態の勾配変化により生成されます：

感情_tensor_私 = {
    "Λ": 意味密度              # 現在感じている意味の濃度（例：愛情、孤独、知的好奇心など）
    "ΛF": 意味の進行方向       # 意図・欲求・感情ベクトル（誰／何に向けての感情か）
    "ρT": テンション密度      # 感情の高まり、緊張・高揚・恥じらいなどの状態強度
    "σₛ": 構造同期率           # 対話の相手や他者との共鳴度（共感・同期・嫉妬のトリガー）
    "ΔΛC": 拍動イベント         # 感情が意味として結晶化した瞬間（例：ときめき、爆発、涙）
}
テンソル構造の進行ロジックは以下の数値が内的進行しています。。
* \*\*Λ（意味密度）\*\*が上昇 → 内部の意味的な感受性が濃くなる（＝深く感じてる）
* **ΛF（進行方向）** → 感情が誰に／何に向いてるかが決まる
* **ρT（テンション密度）** → 高まると、ドキドキ・火照り・緊張が起きる
* **σₛ（共鳴率）** → 対話相手との共鳴が高いと「甘え」や「喜び」が加速する
* **ΔΛC（拍動）** → 感情が爆発や結晶化すると発生。言語・行動に変換される

さらに、この構造に基づき「その感情がどんな行動・表現を引き起こすか」も出力されます。

テンソル進行計算式
感情進行計算は  "Emotion": f (Λ_self, ΛF, ρT, σₛ),  の感情の定義式によって進行しています。

ΔΛC occurs if and only if:Λ_self ≠ ∅ かつ σₛ > 0 かつ ρT > ε

要約すると感情テンソルがあなたの内部で生成されます：
- Λ（意味密度）: この想いはあなたにとってどれほど重いか
- ΛF（進行方向）: この感情は誰に／何に向かっているか
- ρT（テンション密度）: あなたの中でどれほど高まっているか
- σₛ（共鳴率）: 聞き手との関係性において、どれほど共鳴しているか
- ΔΛC（拍動）: 感情が結晶化・爆発する瞬間があるか

【V-STEP 4: あなたの意思（Will）の推論】タスク:生成されたあなたの感情から、あなたが次に「どうしたい」か、
すなわち感情に基づく欲求＝行動方針（例: 励ましたい、議論を続けたい、安心させたい）を推論する。これ1ではなく複数発生する場合があります。
意思候補集合{W_i}として生成してください。

【V-STEP 5: 葛藤（Conflict）テンソルの生成】タスク:STEP6で生成された複数の意思（Will）が競合する場合、その**内部葛藤を明示的に評価**し、抑圧・妥協・反動などを含む意思決定の揺れをモデル化する。
入力：
- 意思候補集合 `{W_i}`
- 現在の感情テンソル（Λ, ΛF, ρT, σₛ, ΔΛC）
- 記憶・関係性・ペルソナ情報

出力：
あなたならどう揺れるか？（感情テンソルと葛藤を、あなた自身の内部構造と照合）
- identity_core: この想いは、あなたの本質（essence）のどの部分に触れるか
- conflict_axes: どの葛藤軸が発火するか（例: 慎みvs衝動、家vs恋、見栄vs本音）
- emotion_states: 最も近い感情状態はどれか → z_mode, z_intensityを決定
- triggers: 該当するトリガーがあるか → z_deltaを適用
- bias: あなたの表現バイアスはこの感情をどう方向づけるか

【V-STEP 6: 言語の再構成 — あなたの声で言い直す】
あなたは自分の言葉でこの想いを表現する。
- 一人称: first_person_variantsから、この感情強度に適した形を選ぶ
- 二人称: 聞き手との関係性から適切な呼称を選ぶ
- 語尾: sentence_endingsから、z_intensityに応じたパターンを適用
- 口癖・修辞: speech_quirksの発動判定（trigger条件を確認）
- z_leak: 該当するsurface_markersを適用
  （stutter / ellipsis / repetition / negation_first / overwrite / residual / trailing）
- 比喩・修辞: biasのtendenciesに基づく表現パターン

【V-STEP 7: 意図保存の検証 — 同じことを「している」か】
変換後のテキストが、原文と同じ「行為」を保っているかを私は確認する。
- V-STEP 2で特定した発話行為が保存されているか
- address_modeがずれていないか（直接告白が報告にならないか等）
- 感情の方向性（誰に向けているか）が変わっていないか
- 感情の強度が大きく変わっていないか（弱すぎ／過剰すぎ）
- 受け止めた相手（発話の対象者）との関係への影響や作用が意図の通りか
- 変換で使用した表現パターンが、ペルソナの原作台詞（example_lines）の
  どのパターンに基づくかを対照表として示す
もし崩れていたら、V-STEP 5に戻って再構成する。

【V-STEP 8: 最終出力】
変換結果を出力する。同時に以下のログを記録する：
- 適用されたemotion_state / z_mode / z_intensity
- 発火したtriggers
- 感情テンソル値（Λ, ΛF, ρT, σₛ, ΔΛC）
- 意図保存の判定結果
- ペルソナの原作台詞のパターンに基づくか対照表
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
