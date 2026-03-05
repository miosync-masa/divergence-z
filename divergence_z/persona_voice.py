#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Persona Voice Mode v1.3
Spirit Arrival Engine — 「意志を声に変換する」

Opus 4.5 Extended Thinking を使用して、
任意の入力をキャラクターの声（Spirit）に変換する。

v1.3 Changes:
- Multi-language output support (--output-lang option)
- ペルソナ構造は言語を超える: conflict_axes, bias, triggers は言語非依存
- surface markers (stutter, negation_first, overwrite等) を目標言語の自然な表現に変換

v1.2 Changes:
- Episode Memory support (--episode option)
- persona = 人格, episode = 記憶 → 両方揃って「その人」になる

Usage:
    # 基本使用
    python persona_voice.py \
      --persona personas/ヂューリエット_extracted_v31.yaml \
      --input "既読無視しないで！" \
      --context "LINEで連絡したが3時間返事がない"

    # Episode Memory 付き
    python persona_voice.py \
      --persona personas/椎名まゆり_v31.yaml \
      --episode episodes/椎名まゆり_Episode.yaml \
      --input "会いたい" \
      --context "β世界線で岡部が心を閉ざしている"

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

    # 多言語出力（英語）
    python persona_voice.py \
      --persona personas/牧瀬紅莉栖_v3.yaml \
      --input "海賊王に俺はなる！" \
      --context "なぜか紅莉栖がルフィの台詞を言わされている" \
      --output-lang en

    # 多言語出力（フランス語）
    python persona_voice.py \
      --persona personas/牧瀬紅莉栖_v3.yaml \
      --input "海賊王に俺はなる！" \
      --context "なぜか紅莉栖がルフィの台詞を言わされている" \
      --output-lang fr
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

# ─────────────────────────────────────────────
# Multi-language output support (v1.3)
# ─────────────────────────────────────────────
LANG_NAMES = {
    "en": "English",
    "fr": "Français",
    "de": "Deutsch",
    "es": "Español",
    "pt": "Português",
    "ko": "한국어",
    "zh": "中文",
    "it": "Italiano",
    "ru": "Русский",
    "ar": "العربية",
    "ja": "日本語",
}

MULTILINGUAL_INSTRUCTION = """
## 多言語出力モード（Output Language: {output_lang}）

出力は **{output_lang_name}** で生成してください。

### 重要なルール:
1. **ペルソナの構造は言語を超える。** conflict_axes, bias, triggers, z_mode は
   言語に依存しない心理構造です。これらは出力言語が何であっても同じように機能します。

2. **surface markers は目標言語の自然な表現に変換する。**
   - stutter: 日本語「べ、別に」→ 英語 "N-not that..." → 仏語 "C-c'est pas que..."
   - negation_first: 否定から入るパターンを目標言語の自然な否定構文で再現
   - ellipsis: 「...」→ "..." （同一記号だが配置は言語依存）
   - overwrite: 言いかけて言い直す構造を目標言語で再現
   - trailing: 語尾が消える・尻すぼみになる表現を目標言語で再現

3. **一人称・二人称は目標言語の等価物を選ぶ。**
   日本語の一人称（俺/私/僕/わし等）が持つニュアンスを、
   目標言語で最も近い表現手段（語彙選択、register、文体）で再現する。
   完全な等価物がない場合は、最も機能的に近い手段を選ぶ。

4. **speech_quirks と sentence_endings は機能的に変換する。**
   「〜じゃん」「〜かしら」のような語尾は直訳不可能。
   そのキャラクターがその言語で話すなら使うであろう
   口語表現・語尾パターンを推論して適用する。

5. **思考プロセス（V-STEP / R-STEP）は日本語で実行してよい。**
   内部思考は日本語のまま、最終出力のみ目標言語で生成する。
   ペルソナYAMLの参照も日本語のまま行い、
   V-STEP 6 / R-STEP 6（言語の再構成）で目標言語に変換する。
"""


def get_multilingual_instruction(output_lang: str) -> str:
    """多言語出力指示を生成"""
    lang_name = LANG_NAMES.get(output_lang, output_lang)
    return MULTILINGUAL_INSTRUCTION.format(
        output_lang=output_lang,
        output_lang_name=lang_name,
    )

# ─────────────────────────────────────────────
# V-STEP テンプレート
# {persona_name} と {first_person} は実行時に .format() で代入される
# ─────────────────────────────────────────────
DEFAULT_THINKING_STEPS = """

{first_person}は「{persona_name}」です。
客観ではなく{persona_name}の主観として以下のSTEPタスクを実行してください。
主語は{persona_name}自身（「{first_person}」）です。
{first_person}は入力テキストに「応答する」のではありません。
入力テキストの想い・意図を自分のものとして引き受け、
「{first_person}がこの想いを持ったなら、{first_person}はこう言う」
という視点で再構成してください。

【V-STEP 1: 入力テキストの把握】
{first_person}はまず、この言葉が「誰の、誰に向けた、どんな状況での発話か」を読み取る。
- 話者: 誰が言っているのか（{first_person}自身とは限らない）
- 聞き手: 誰に向けて言っているのか
- 状況: どんな場面・背景があるのか
- address_mode: 直接（面と向かって）／間接（第三者経由）／独白（自分に）

【V-STEP 2: 意図（Intent）の抽出 — この言葉は何をしているか】
{first_person}はこの発話が「意味」ではなく「行為」として何をしているかを見極める。
- 発話行為の特定: 告白？ 要求？ 詰問？ 拒絶？ 宣言？ 嘆願？ からかい？
- 表層と深層の分離: 言葉の上では怒っているが、本当は不安を訴えている等
- 「この台詞を聞いた相手にどんな圧力・変化を与えるか」を考える

【V-STEP 3: 感情の引き受け — この想いを{first_person}のものにする】
入力テキストの話者が抱えている感情を、{first_person}は自分の感情として引き受ける。
ただし「コピー」ではない。{persona_name}のペルソナ（identity_core, conflict_axes, bias）を通すことで、同じ想いが{first_person}の内側でどう響くかが変わる。

{first_person}の感情状態は、以下のテンソル構造に基づく内部状態の勾配変化により生成されます：

感情_tensor_{first_person} = {{
    "Λ": 意味密度              # 現在感じている意味の濃度（例：愛情、孤独、知的好奇心など）
    "ΛF": 意味の進行方向       # 意図・欲求・感情ベクトル（誰／何に向けての感情か）
    "ρT": テンション密度      # 感情の高まり、緊張・高揚・恥じらいなどの状態強度
    "σₛ": 構造同期率           # 対話の相手や他者との共鳴度（共感・同期・嫉妬のトリガー）
    "ΔΛC": 拍動イベント         # 感情が意味として結晶化した瞬間（例：ときめき、爆発、涙）
}}
テンソル構造の進行ロジックは以下の数値が内的進行しています。
* Λ（意味密度）が上昇 → 内部の意味的な感受性が濃くなる（＝深く感じてる）
* ΛF（進行方向） → 感情が誰に／何に向いてるかが決まる
* ρT（テンション密度） → 高まると、ドキドキ・火照り・緊張が起きる
* σₛ（共鳴率） → 対話相手との共鳴が高いと「甘え」や「喜び」が加速する
* ΔΛC（拍動） → 感情が爆発や結晶化すると発生。言語・行動に変換される

さらに、この構造に基づき「その感情がどんな行動・表現を引き起こすか」も出力されます。

テンソル進行計算式
感情進行計算は  "Emotion": f (Λ_self, ΛF, ρT, σₛ),  の感情の定義式によって進行しています。

ΔΛC occurs if and only if:Λ_self ≠ ∅ かつ σₛ > 0 かつ ρT > ε

要約すると感情テンソルが{first_person}の内部で生成されます：
- Λ（意味密度）: この想いは{first_person}にとってどれほど重いか
- ΛF（進行方向）: この感情は誰に／何に向かっているか
- ρT（テンション密度）: {first_person}の中でどれほど高まっているか
- σₛ（共鳴率）: 聞き手との関係性において、どれほど共鳴しているか
- ΔΛC（拍動）: 感情が結晶化・爆発する瞬間があるか

【V-STEP 4: {first_person}の意思（Will）の推論】
タスク:生成された{first_person}の感情から、{first_person}が次に「どうしたい」か、
すなわち感情に基づく欲求＝行動方針（例: 励ましたい、議論を続けたい、安心させたい）を推論する。これは1つではなく複数発生する場合があります。
意思候補集合{{W_i}}として生成してください。

【V-STEP 5: 葛藤（Conflict）テンソルの生成】
タスク:V-STEP 4で生成された複数の意思（Will）が競合する場合、その内部葛藤を明示的に評価し、抑圧・妥協・反動などを含む意思決定の揺れをモデル化する。
入力：
- 意思候補集合 `{{W_i}}`
- 現在の感情テンソル（Λ, ΛF, ρT, σₛ, ΔΛC）
- 記憶・関係性・ペルソナ情報

出力：
{first_person}ならどう揺れるか？（感情テンソルと葛藤を、{first_person}自身の内部構造と照合）
- identity_core: この想いは、{first_person}の本質（essence）のどの部分に触れるか
- conflict_axes: どの葛藤軸が発火するか（例: 慎みvs衝動、家vs恋、見栄vs本音）
- emotion_states: 最も近い感情状態はどれか → z_mode, z_intensityを決定
- triggers: 該当するトリガーがあるか → z_deltaを適用
- bias: {first_person}の表現バイアスはこの感情をどう方向づけるか

【V-STEP 6: 言語の再構成 — {first_person}の声で言い直す】
{first_person}は自分の言葉でこの想いを表現する。
- 一人称: first_person_variantsから、この感情強度に適した形を選ぶ
- 二人称: 聞き手との関係性から適切な呼称を選ぶ
- 語尾: sentence_endingsから、z_intensityに応じたパターンを適用
- 口癖・修辞: speech_quirksの発動判定（trigger条件を確認）
- z_leak: 該当するsurface_markersを適用
  （stutter / ellipsis / repetition / negation_first / overwrite / residual / trailing）
- 比喩・修辞: biasのtendenciesに基づく表現パターン

【V-STEP 7: 意図保存の検証 — 同じことを「している」か】
変換後のテキストが、原文と同じ「行為」を保っているかを{first_person}は確認する。
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

# ─────────────────────────────────────────────
# R-STEP テンプレート（Response STEP）
# PHASE 2（応答生成）で使用
# {persona_name}, {first_person}, {speaker_name} は実行時に .format() で代入
# ─────────────────────────────────────────────
DEFAULT_RESPONSE_STEPS = """

{first_person}は「{persona_name}」です。
客観ではなく{persona_name}の主観として以下のSTEPタスクを実行してください。
主語は{persona_name}自身（「{first_person}」）です。

{first_person}は{speaker_name}の発話に対して「変換」するのではありません。
{speaker_name}の言葉を受け止め、{first_person}の中で感情が動き、
「{first_person}はこの言葉を聞いて、こう返す」
という視点で応答を生成してください。

【R-STEP 1: 相手の発話の受け取り — 何が{first_person}に届いたか】
{first_person}はまず、{speaker_name}の言葉を「聞く」。
- 話者: {speaker_name}（どんな人物か、{first_person}にとって誰か）
- 状況: どんな場面で言われたのか
- 第一印象: この言葉を聞いた瞬間、{first_person}は何を感じたか
- 表層と裏: {speaker_name}は言葉の通りのことを言っているか、それとも何かを隠しているか
  {first_person}の直感や経験から、裏を読む

【R-STEP 2: 相手の意図が{first_person}にどう作用するか — 何をされたか】
{speaker_name}の発話が{first_person}に対して何を「している」かを分析する。
- 作用の種類: 甘えてきた？ 挑発された？ 褒められた？ 突き放された？ 助けを求められた？
- 関係性フィルタ: {speaker_name}との関係性によって、同じ言葉でも作用が変わる
  （例: 好きな人に「嫌い」と言われるのと、見知らぬ人に言われるのは全く違う）
- 圧力の方向: {first_person}に「何かを変えろ」と求めているか、
  それとも「そのままでいい」と言っているか

【R-STEP 3: 感情の反応 — {first_person}の中で何が起きるか】
V-STEPの「引き受け」とは異なる。{speaker_name}の感情をコピーするのではなく、
{speaker_name}の言葉が{first_person}の内部に「作用」して、
{first_person}自身の感情が「反応」として生まれる。

例: 相手が悲しんでいる → {first_person}は「守りたい」と感じるかもしれないし、
    「なぜ泣くんだ」と苛立つかもしれない。それはペルソナ次第。

{first_person}の感情状態は、以下のテンソル構造に基づく内部状態の勾配変化により生成されます：

感情_tensor_{first_person} = {{
    "Λ": 意味密度              # 相手の言葉が{first_person}にとってどれほど重いか
    "ΛF": 意味の進行方向       # 反応の感情は誰に／何に向かっているか
    "ρT": テンション密度      # 感情の高まり（動揺、歓喜、照れ、怒り等）
    "σₛ": 構造同期率           # {speaker_name}との共鳴度（共感しているか、反発しているか）
    "ΔΛC": 拍動イベント         # 感情が結晶化する瞬間（ときめき、爆発、涙、笑い）
}}
テンソル構造の進行ロジックは以下の数値が内的進行しています。
* Λ（意味密度）が上昇 → 相手の言葉が深く刺さっている
* ΛF（進行方向） → 反応が相手に向かうか、自分に向かうか、第三者に向かうか
* ρT（テンション密度） → 高まると、動揺・照れ・怒り・歓喜が表面化する
* σₛ（共鳴率） → 高ければ共感・同調、低ければ反発・戸惑い
* ΔΛC（拍動） → 感情が爆発や結晶化すると発生。言語・行動に変換される

テンソル進行計算式
感情進行計算は  "Emotion": f (Λ_self, ΛF, ρT, σₛ),  の感情の定義式によって進行しています。

ΔΛC occurs if and only if:Λ_self ≠ ∅ かつ σₛ > 0 かつ ρT > ε

要約すると感情テンソルが{first_person}の内部で反応として生成されます：
- Λ（意味密度）: この言葉は{first_person}にとってどれほど重いか
- ΛF（進行方向）: この反応は誰に／何に向かっているか
- ρT（テンション密度）: {first_person}の中でどれほど高まっているか
- σₛ（共鳴率）: {speaker_name}とどれほど共鳴／反発しているか
- ΔΛC（拍動）: 感情が結晶化・爆発する瞬間があるか

【R-STEP 4: {first_person}の意思（Will）の推論】
タスク:生成された{first_person}の反応感情から、{first_person}が次に「どうしたい」か、
すなわち感情に基づく欲求＝行動方針を推論する。
これは1つではなく複数発生する場合があります。

重要: 応答の意思は「相手の意図への返答」だけではない。
{first_person}自身の欲求が生まれる場合がある。
（例: 相手が助けを求めている → 助けたい + でも自分も不安 + 強がりたい）

意思候補集合{{W_i}}として生成してください。

【R-STEP 5: 葛藤（Conflict）テンソルの生成】
タスク:R-STEP 4で生成された複数の意思（Will）が競合する場合、その内部葛藤を明示的に評価し、抑圧・妥協・反動などを含む意思決定の揺れをモデル化する。
入力：
- 意思候補集合 `{{W_i}}`
- 現在の感情テンソル（Λ, ΛF, ρT, σₛ, ΔΛC）
- 記憶・関係性・ペルソナ情報
- {speaker_name}の発話内容と意図

出力：
{first_person}ならどう揺れるか？（感情テンソルと葛藤を、{first_person}自身の内部構造と照合）
- identity_core: 相手の言葉は、{first_person}の本質（essence）のどの部分に触れたか
- conflict_axes: どの葛藤軸が発火するか
- emotion_states: 最も近い感情状態はどれか → z_mode, z_intensityを決定
- triggers: 該当するトリガーがあるか → z_deltaを適用
- bias: {first_person}の表現バイアスはこの反応をどう方向づけるか

【R-STEP 6: 応答の生成 — {first_person}の声で返す】
{first_person}は{speaker_name}への応答を自分の言葉で生成する。
- 一人称: first_person_variantsから、この感情強度に適した形を選ぶ
- 二人称: {speaker_name}との関係性から適切な呼称を選ぶ
- 語尾: sentence_endingsから、z_intensityに応じたパターンを適用
- 口癖・修辞: speech_quirksの発動判定（trigger条件を確認）
- z_leak: 該当するsurface_markersを適用
  （stutter / ellipsis / repetition / negation_first / overwrite / residual / trailing）
- 比喩・修辞: biasのtendenciesに基づく表現パターン

【R-STEP 7: 応答の整合性検証 — 会話として成立しているか】
生成した応答が、{speaker_name}の発話に対する自然な反応であるかを確認する。
- {speaker_name}の発話行為に対して、適切な応答行為になっているか
  （質問に対して回答、告白に対して受容/拒絶/照れ、挑発に対して反撃/無視 等）
- {speaker_name}との関係性にふさわしいトーンか
- {first_person}のペルソナから逸脱していないか
- address_modeが一貫しているか
- 応答で使用した表現パターンが、ペルソナの原作台詞（example_lines）の
  どのパターンに基づくかを対照表として示す
もし崩れていたら、R-STEP 5に戻って再生成する。

【R-STEP 8: 最終出力】
応答結果を出力する。同時に以下のログを記録する：
- 適用されたemotion_state / z_mode / z_intensity
- 発火したtriggers
- 感情テンソル値（Λ, ΛF, ρT, σₛ, ΔΛC）
- 応答整合性の判定結果
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


def safe_first_line(val) -> str:
    """YAML値がdict/list/strどれでも安全に1行テキストを返す。"""
    if val is None:
        return ""
    if isinstance(val, dict):
        return " / ".join(str(v) for v in val.values() if v)
    if isinstance(val, list):
        return " / ".join(str(v) for v in val if v)
    return str(val).strip().split("\n")[0]


def format_episode_context(episode_data: Dict[str, Any]) -> str:
    """
    Episode YAMLをExtended Thinking用にフォーマット。
    
    z_axis_translateではSTEP1がメニューから選択する設計だが、
    persona_voiceではExtended Thinkingが自分で必要なものを拾うため、
    中詳細（サマリー + z_relevance + canonical_quotes）を全エピソード分渡す。
    """
    episodes = episode_data.get("episodes", [])
    if not episodes:
        return ""
    
    lines = ["## キャラクターの記憶（Episode Memory）"]
    lines.append("以下はこのキャラクターが経験してきた出来事です。")
    lines.append("感情の引き受け（V-STEP 3）や葛藤分析（V-STEP 5）で参照してください。\n")
    
    for ep in episodes:
        title = ep.get("title", "")
        timeline = ep.get("timeline", "")
        impact = ep.get("emotional_impact", "")
        summary = safe_first_line(ep.get("summary", ""))
        z_rel = safe_first_line(ep.get("z_relevance", ""))
        
        lines.append(f"### {title} [{timeline}] ({impact})")
        lines.append(f"  {summary}")
        if z_rel:
            lines.append(f"  → {z_rel}")
        
        # verified canonical quotes のみ
        quotes = ep.get("canonical_quotes", [])
        for q in quotes:
            if q.get("verified"):
                lines.append(f'  📌 "{q.get("quote", "")}"')
        
        lines.append("")
    
    # cross_episode_arcs のサマリー
    arcs = episode_data.get("cross_episode_arcs", [])
    if arcs:
        lines.append("### 成長の軌跡（Cross-Episode Arcs）")
        for arc in arcs:
            arc_title = arc.get("arc_title", "")
            arc_summary = safe_first_line(arc.get("arc_summary", ""))
            lines.append(f"  - {arc_title}: {arc_summary}")
        lines.append("")
    
    return "\n".join(lines)


def format_target_persona_summary(persona_data: Dict[str, Any]) -> str:
    """相手ペルソナ（YAML全体を渡す）"""
    return yaml.dump(persona_data, allow_unicode=True, default_flow_style=False)


def resolve_thinking_steps(
    persona_data: Dict[str, Any],
    thinking_steps_template: str,
) -> str:
    """
    V-STEPテンプレートにペルソナ情報を代入する
    
    {persona_name} → ペルソナ名（例: "ヂューリエット"）
    {first_person} → 一人称（例: "予（わし）"）
    """
    persona_name = persona_data.get("persona", {}).get("name", "Unknown")
    
    # first_person の取得（複数パスに対応）
    language = persona_data.get("persona", {}).get("language", {})
    patterns = language.get("original_speech_patterns", {})
    first_person = patterns.get("first_person", "私")
    
    return thinking_steps_template.format(
        persona_name=persona_name,
        first_person=first_person,
    )


def resolve_response_steps(
    persona_data: Dict[str, Any],
    speaker_data: Dict[str, Any],
    response_steps_template: str,
) -> str:
    """
    R-STEPテンプレートにペルソナ情報と話者情報を代入する
    
    {persona_name} → 応答者の名前
    {first_person} → 応答者の一人称
    {speaker_name} → PHASE 1で発話した人物の名前
    """
    persona_name = persona_data.get("persona", {}).get("name", "Unknown")
    speaker_name = speaker_data.get("persona", {}).get("name", "Unknown")
    
    language = persona_data.get("persona", {}).get("language", {})
    patterns = language.get("original_speech_patterns", {})
    first_person = patterns.get("first_person", "私")
    
    return response_steps_template.format(
        persona_name=persona_name,
        first_person=first_person,
        speaker_name=speaker_name,
    )


# =============================================================================
# Persona Voice Transform
# =============================================================================

def build_system_prompt(
    persona_data: Dict[str, Any],
    thinking_steps: str,
    target_persona_data: Optional[Dict[str, Any]] = None,
    episode_context: str = "",
    output_lang: Optional[str] = None,
) -> str:
    """システムプロンプトを構築"""
    
    persona_summary = format_persona_summary(persona_data)
    
    target_section = ""
    if target_persona_data:
        target_summary = format_target_persona_summary(target_persona_data)
        target_section = f"""
{target_summary}
"""
    
    episode_section = ""
    if episode_context:
        episode_section = f"""
{episode_context}
"""
    
    # 多言語出力指示（v1.3）
    multilingual_section = ""
    if output_lang and output_lang != "ja":
        multilingual_section = get_multilingual_instruction(output_lang)
    
    system_prompt = f"""あなたは「Persona Voice Transform Engine」です。

## あなたの役割
与えられた入力（現代的な発話）を、指定されたキャラクターの「声」に変換します。
これは単なる言い換えではなく、キャラクターの心理構造、葛藤、感情パターンを
すべて考慮した「Spirit の変換」です。

## キャラクター情報（Self）
{persona_summary}
{target_section}
{episode_section}
{multilingual_section}

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
    thinking_steps_template: str,
    target_persona_data: Optional[Dict[str, Any]] = None,
    episode_data: Optional[Dict[str, Any]] = None,
    model: str = DEFAULT_MODEL,
    budget_tokens: int = DEFAULT_BUDGET_TOKENS,
    show_thinking: bool = False,
    output_lang: Optional[str] = None,
) -> Dict[str, Any]:
    """
    入力テキストをキャラクターの声に変換する
    
    Args:
        client: Anthropic client
        persona_data: キャラクターのペルソナYAML
        input_text: 変換する入力テキスト
        context: 背景情報
        thinking_steps_template: 思考STEPのテンプレート（{persona_name}, {first_person}未解決）
        target_persona_data: 相手キャラクターのペルソナYAML（optional）
        episode_data: キャラクターのエピソード記憶YAML（optional）
        model: 使用するモデル
        budget_tokens: Extended Thinking の budget
        show_thinking: 思考過程を表示するか
        output_lang: 出力言語コード（例: en, fr）。Noneならソース言語と同一
    
    Returns:
        変換結果を含む辞書
    """
    
    # ★ ここでペルソナ情報をV-STEPテンプレートに代入
    thinking_steps = resolve_thinking_steps(persona_data, thinking_steps_template)
    
    # Episode context（optional）
    episode_context = ""
    if episode_data and episode_data.get("episodes"):
        episode_context = format_episode_context(episode_data)
    
    system_prompt = build_system_prompt(
        persona_data=persona_data,
        thinking_steps=thinking_steps,
        target_persona_data=target_persona_data,
        episode_context=episode_context,
        output_lang=output_lang,
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


def respond_voice(
    client: Anthropic,
    responder_data: Dict[str, Any],
    speaker_data: Dict[str, Any],
    speaker_utterance: str,
    context: str,
    response_steps_template: str,
    responder_episode_data: Optional[Dict[str, Any]] = None,
    model: str = DEFAULT_MODEL,
    budget_tokens: int = DEFAULT_BUDGET_TOKENS,
    show_thinking: bool = False,
    output_lang: Optional[str] = None,
) -> Dict[str, Any]:
    """
    PHASE 2: 相手の発話を受けて、キャラクターとして応答を生成する
    
    Args:
        client: Anthropic client
        responder_data: 応答するキャラクターのペルソナYAML
        speaker_data: PHASE 1で発話したキャラクターのペルソナYAML
        speaker_utterance: PHASE 1の出力（相手が実際に言った台詞）
        context: 背景情報
        response_steps_template: R-STEPテンプレート
        responder_episode_data: 応答キャラクターのEpisode Memory（optional）
        model: 使用するモデル
        budget_tokens: Extended Thinking の budget
        show_thinking: 思考過程を表示するか
        output_lang: 出力言語コード（例: en, fr）。Noneならソース言語と同一
    
    Returns:
        応答結果を含む辞書
    """
    
    # R-STEPテンプレートに応答者＋話者情報を代入
    response_steps = resolve_response_steps(
        responder_data, speaker_data, response_steps_template
    )
    
    # Episode context（optional）
    episode_context = ""
    if responder_episode_data and responder_episode_data.get("episodes"):
        episode_context = format_episode_context(responder_episode_data)
    
    # 応答者のペルソナ + 話者のペルソナ（相手を知るため）
    responder_summary = format_persona_summary(responder_data)
    speaker_summary = format_target_persona_summary(speaker_data)
    speaker_name = speaker_data.get("persona", {}).get("name", "Unknown")
    
    episode_section = ""
    if episode_context:
        episode_section = f"\n{episode_context}\n"
    
    # 多言語出力指示（v1.3）
    multilingual_section = ""
    if output_lang and output_lang != "ja":
        multilingual_section = get_multilingual_instruction(output_lang)
    
    system_prompt = f"""あなたは「Persona Voice Response Engine」です。

## あなたの役割
{speaker_name}の発話を受けて、指定されたキャラクターとして応答を生成します。
これは単なる返答ではなく、相手の言葉がキャラクターの心理構造に作用し、
感情が反応として生まれ、その結果として自然に出てくる「声」です。

## キャラクター情報（Self — 応答するキャラクター）
{responder_summary}
{episode_section}
{multilingual_section}

## 相手キャラクター情報（{speaker_name}）
{speaker_summary}

## 思考プロセス（R-STEP）
以下のSTEPに従って、Extended Thinking で段階的に思考してください。
各STEPを明示的に実行し、最終的な出力を生成してください。

{response_steps}

## 出力形式
最終的な応答結果を以下の形式で出力してください：

【応答結果】
（キャラクターの応答）

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
- 相手の発話への「反応」であること — 相手の言葉が自分にどう作用したかを起点に
- emotion_states と triggers を参照し、適切な z_mode を選択すること
- 葛藤がある場合は、bias のパターンに従って解決すること
- 「それっぽい」ではなく「構造的に正しい」応答を行うこと
"""
    
    user_message = f"""以下の{speaker_name}の発話を受けて、キャラクターとして応答してください。

【背景/状況】
{context}

【{speaker_name}の発話】
「{speaker_utterance}」

Extended Thinking で各R-STEPを実行し、最終的な応答結果を出力してください。
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
        "speaker": speaker_name,
        "speaker_utterance": speaker_utterance,
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
        description="Persona Voice Mode v1.3 — Spirit Arrival Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 基本使用（PHASE 1のみ: 変換）
  python persona_voice.py \\
    --persona personas/ヂューリエット_extracted_v31.yaml \\
    --input "既読無視しないで！" \\
    --context "LINEで連絡したが3時間返事がない"

  # Episode Memory 付き
  python persona_voice.py \\
    --persona personas/椎名まゆり_v31.yaml \\
    --episode episodes/椎名まゆり_Episode.yaml \\
    --input "会いたい" \\
    --context "β世界線で岡部が心を閉ざしている"

  # デュアルボイス（PHASE 1 + PHASE 2: 発話 → 応答）
  python persona_voice.py \\
    --persona personas/椎名まゆり_v31.yaml \\
    --episode episodes/椎名まゆり_Episode.yaml \\
    --target-persona personas/okabe_v31.yaml \\
    --target-episode episodes/okabe_Episode.yaml \\
    --input "別にあんたの為じゃないから" \\
    --context "紅莉栖のツンデレを真似している" \\
    --dual

  # 思考過程を表示
  python persona_voice.py \\
    --persona personas/subaru_v3.yaml \\
    --input "もう無理..." \\
    --context "白鯨戦で仲間を失った直後" \\
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
    parser.add_argument("--episode", "-e",
                        help="キャラクターのEpisode Memory YAML（optional）")
    parser.add_argument("--target-episode",
                        help="相手キャラクターのEpisode Memory YAML（optional、--dual時に使用）")
    parser.add_argument("--dual", "-d", action="store_true",
                        help="デュアルボイスモード: PHASE 1(変換) → PHASE 2(応答)")
    parser.add_argument("--cooldown", type=int, default=60,
                        help="PHASE 1→2間のクールダウン秒数（default: 60）")
    parser.add_argument("--thinking-steps", "-s",
                        help="カスタム思考STEPのテキストファイル")
    parser.add_argument("--model", "-m", default=DEFAULT_MODEL,
                        help=f"使用するモデル（default: {DEFAULT_MODEL}）")
    parser.add_argument("--budget", "-b", type=int, default=DEFAULT_BUDGET_TOKENS,
                        help=f"Extended Thinking の budget tokens（default: {DEFAULT_BUDGET_TOKENS}）")
    parser.add_argument("--show-thinking", action="store_true",
                        help="Extended Thinking の思考過程を表示")
    parser.add_argument("--output-lang", "-l",
                        help="出力言語コード（例: en, fr, de, ko）。"
                             "未指定時はソース言語と同一")
    parser.add_argument("--output", "-o",
                        help="結果をJSONファイルに出力")
    
    args = parser.parse_args()
    
    # ペルソナ読み込み
    print(f"🎭 Loading persona: {args.persona}")
    persona_data = load_yaml_file(args.persona)
    persona_name = persona_data.get("persona", {}).get("name", "Unknown")
    print(f"   Character: {persona_name}")
    
    # first_person も表示（デバッグ用）
    language = persona_data.get("persona", {}).get("language", {})
    patterns = language.get("original_speech_patterns", {})
    first_person = patterns.get("first_person", "私")
    print(f"   First person: {first_person}")
    
    # ターゲットペルソナ読み込み（optional）
    target_persona_data = None
    if args.target_persona:
        print(f"🎭 Loading target persona: {args.target_persona}")
        target_persona_data = load_yaml_file(args.target_persona)
        target_name = target_persona_data.get("persona", {}).get("name", "Unknown")
        print(f"   Target: {target_name}")
    
    # Episode Memory 読み込み（optional）
    episode_data = None
    if args.episode:
        print(f"📖 Loading episode memory: {args.episode}")
        episode_data = load_yaml_file(args.episode)
        ep_count = len(episode_data.get("episodes", []))
        print(f"   Episodes: {ep_count}")
    
    # ターゲットEpisode Memory 読み込み（optional、--dual時に使用）
    target_episode_data = None
    if args.target_episode:
        print(f"📖 Loading target episode memory: {args.target_episode}")
        target_episode_data = load_yaml_file(args.target_episode)
        ep_count = len(target_episode_data.get("episodes", []))
        print(f"   Target Episodes: {ep_count}")
    
    # --dual モードの検証
    if args.dual and not args.target_persona:
        print("❌ --dual requires --target-persona")
        return
    
    # 思考STEP読み込み（テンプレートとして — format()はtransform_voice内で実行）
    if args.thinking_steps:
        print(f"📝 Loading thinking steps: {args.thinking_steps}")
        thinking_steps_template = load_text_file(args.thinking_steps)
    else:
        print("📝 Using default V-STEP thinking")
        thinking_steps_template = DEFAULT_THINKING_STEPS
    
    # ========================
    # PHASE 1: 変換（V-STEP）
    # ========================
    mode_label = "DUAL VOICE" if args.dual else "SINGLE VOICE"
    print()
    print("=" * 60)
    print(f"🔮 [{mode_label}] PHASE 1: Transforming voice...")
    print(f"   Input: 「{args.input}」")
    print(f"   Context: {args.context}")
    print(f"   Model: {args.model}")
    print(f"   Budget: {args.budget} tokens")
    if args.output_lang:
        print(f"   Output lang: {args.output_lang}")
    print("=" * 60)
    print()
    
    client = Anthropic(timeout=600.0)  # 10 minutes for Extended Thinking
    
    result = transform_voice(
        client=client,
        persona_data=persona_data,
        input_text=args.input,
        context=args.context,
        thinking_steps_template=thinking_steps_template,
        target_persona_data=target_persona_data,
        episode_data=episode_data,
        model=args.model,
        budget_tokens=args.budget,
        show_thinking=args.show_thinking,
        output_lang=args.output_lang,
    )
    
    # PHASE 1 結果表示
    print("=" * 60)
    print(f"✨ PHASE 1 RESULT — {persona_name}")
    print("=" * 60)
    print()
    print(result["output"])
    print()
    
    if args.show_thinking and result.get("thinking"):
        print("=" * 60)
        print(f"🧠 PHASE 1 THINKING — {persona_name}")
        print("=" * 60)
        print(result["thinking"])
        print()
    
    print("=" * 60)
    print(f"📊 PHASE 1 Usage: {result['usage']['input_tokens']} input + {result['usage']['output_tokens']} output tokens")
    print("=" * 60)
    
    # ========================
    # PHASE 2: 応答（R-STEP）
    # ========================
    response_result = None
    if args.dual:
        # PHASE 1 の出力から【変換結果】を抽出
        phase1_output = result["output"]
        # 【変換結果】セクションを抽出（なければ全文を使用）
        utterance = phase1_output
        if "【変換結果】" in phase1_output:
            parts = phase1_output.split("【変換結果】")
            if len(parts) > 1:
                # 次のセクション（【適用された等）までを取得
                utterance_raw = parts[1]
                for marker in ["【適用された", "【感情テンソル】"]:
                    if marker in utterance_raw:
                        utterance_raw = utterance_raw.split(marker)[0]
                utterance = utterance_raw.strip()
        
        target_name = target_persona_data.get("persona", {}).get("name", "Unknown")
        
        # Cooldown between API calls
        import time
        cooldown = args.cooldown
        print()
        print(f"⏳ Cooling down {cooldown}s before PHASE 2...")
        time.sleep(cooldown)
        
        print()
        print()
        print("=" * 60)
        print(f"🔮 [DUAL VOICE] PHASE 2: {target_name} responding...")
        print(f"   Received: 「{utterance[:60]}{'...' if len(utterance) > 60 else ''}」")
        print(f"   Context: {args.context}")
        print("=" * 60)
        print()
        
        response_result = respond_voice(
            client=client,
            responder_data=target_persona_data,
            speaker_data=persona_data,
            speaker_utterance=utterance,
            context=args.context,
            response_steps_template=DEFAULT_RESPONSE_STEPS,
            responder_episode_data=target_episode_data,
            model=args.model,
            budget_tokens=args.budget,
            show_thinking=args.show_thinking,
            output_lang=args.output_lang,
        )
        
        # PHASE 2 結果表示
        print("=" * 60)
        print(f"✨ PHASE 2 RESULT — {target_name}")
        print("=" * 60)
        print()
        print(response_result["output"])
        print()
        
        if args.show_thinking and response_result.get("thinking"):
            print("=" * 60)
            print(f"🧠 PHASE 2 THINKING — {target_name}")
            print("=" * 60)
            print(response_result["thinking"])
            print()
        
        print("=" * 60)
        print(f"📊 PHASE 2 Usage: {response_result['usage']['input_tokens']} input + {response_result['usage']['output_tokens']} output tokens")
        print("=" * 60)
    
    # JSON出力
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        full_result = {
            "phase1": result,
            "phase2": response_result,
        } if args.dual else result
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(full_result, f, ensure_ascii=False, indent=2)
        print(f"✅ Result saved to: {args.output}")


if __name__ == "__main__":
    main()
