#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Z-Axis Dialogue Translation System v3.2
Operation: Babel Inverse — 対話シーン翻訳（多言語対応）

複数のペルソナ間の対話を、Z軸（感情・葛藤構造）を保存しながら翻訳する。
z_axis_translate.py v3.0 をベースに、対話特有の機能を追加。

v3.2 Changes:
- LLM-based trigger detection (replaces hardcoded keyword matching)
- Removed extract_keywords() and check_triggers_v3()
- New llm_check_triggers() delegates trigger judgment to LLM
- Trigger accumulation now driven by LLM analysis, not regex
- All persona triggers work regardless of language or character

v3.1 Changes:
- Multi-language support (--source-lang / --target-lang)
- original_speech_patterns integration from persona v3.1
- Dynamic language display in summary
- Bidirectional translation support (ja→en, en→ja, zh→en, etc.)

実行例:
  # 日本語→英語（デフォルト）
  python z_axis_dialogue.py --config requests/rem_subaru_zero_v3.yaml

  # 英語→日本語
  python z_axis_dialogue.py --config requests/dialogue_en.yaml --target-lang ja

  # 中国語→英語
  python z_axis_dialogue.py --config requests/dialogue_zh.yaml --source-lang zh --target-lang en

YAML形式:
  personas:
    A: "personas/subaru_v3.yaml"
    B: "personas/rem_v3.yaml"
  
  scene: "白鯨戦後、精神的限界"
  relationships:
    A_to_B: "信頼、依存しつつある"
    B_to_A: "愛情、献身"
  
  source_lang: "ja"  # (optional, default: ja)
  target_lang: "en"
  
  dialogue:
    - speaker: A
      line: "俺は、俺が大嫌いだ"
    - speaker: B
      line: "レムは、スバルくんの味方です"
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from dotenv import load_dotenv

# z_axis_translate.py v3.0 からインポート
try:
    from z_axis_translate import (
        z_axis_translate,
        OpenAIResponsesClient,
        DEFAULT_MODEL,
        extract_v3_features,
        format_trigger_info,
    )
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from z_axis_translate import (
        z_axis_translate,
        OpenAIResponsesClient,
        DEFAULT_MODEL,
        extract_v3_features,
        format_trigger_info,
    )

load_dotenv()


# =============================================================================
# LANGUAGE CONFIGURATION v3.1
# =============================================================================

SUPPORTED_LANGUAGES = {
    "ja": {"name": "Japanese", "native": "日本語", "code": "JA"},
    "en": {"name": "English", "native": "English", "code": "EN"},
    "zh": {"name": "Chinese", "native": "中文", "code": "ZH"},
    "ko": {"name": "Korean", "native": "한국어", "code": "KO"},
    "fr": {"name": "French", "native": "Français", "code": "FR"},
    "es": {"name": "Spanish", "native": "Español", "code": "ES"},
    "de": {"name": "German", "native": "Deutsch", "code": "DE"},
    "pt": {"name": "Portuguese", "native": "Português", "code": "PT"},
    "it": {"name": "Italian", "native": "Italiano", "code": "IT"},
    "ru": {"name": "Russian", "native": "Русский", "code": "RU"},
}

def get_lang_display(lang_code: str) -> str:
    """言語コードから表示用文字列を取得"""
    lang_info = SUPPORTED_LANGUAGES.get(lang_code, {})
    return lang_info.get("code", lang_code.upper())


# =============================================================================
# LLM-BASED TRIGGER DETECTION v3.2
# =============================================================================

TRIGGER_CHECK_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "triggered": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "trigger_index": {
                        "type": "integer",
                        "description": "0-based index of the triggered item in the trigger list",
                    },
                    "trigger_text": {
                        "type": "string",
                        "description": "The trigger description that was activated",
                    },
                    "z_delta": {
                        "type": "number",
                        "description": "Z-delta value for this trigger (from persona definition)",
                    },
                    "z_mode_shift": {
                        "type": "string",
                        "enum": ["collapse", "rage", "numb", "plea", "shame", "leak", "none", ""],
                        "description": "Z-mode shift caused by this trigger",
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "description": "How confident the trigger activation is",
                    },
                    "reasoning": {
                        "type": "string",
                        "maxLength": 200,
                        "description": "Brief explanation of why this trigger activated",
                    },
                },
                "required": ["trigger_index", "trigger_text", "z_delta", "z_mode_shift", "confidence", "reasoning"],
            },
        },
        "total_z_delta": {
            "type": "number",
            "description": "Sum of all triggered z_deltas",
        },
        "final_z_mode_shift": {
            "type": "string",
            "enum": ["collapse", "rage", "numb", "plea", "shame", "leak", "none", ""],
            "description": "The dominant z_mode_shift (last high-confidence trigger wins)",
        },
    },
    "required": ["triggered", "total_z_delta", "final_z_mode_shift"],
}


def format_triggers_for_llm(persona_data: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]]]:
    """
    ペルソナのtrigger情報をLLM判定用にフォーマット。
    
    Returns:
        (formatted_text, triggers_list)
    """
    triggers = persona_data.get('triggers', [])
    if not triggers:
        return "(No triggers defined)", []
    
    lines = []
    for i, t in enumerate(triggers):
        trigger = t.get('trigger', '')
        reaction = t.get('reaction', '')
        z_delta = t.get('z_delta', '+0.0')
        z_mode_shift = t.get('z_mode_shift', '')
        surface_effect = t.get('surface_effect', '')
        example = t.get('example_response', '')
        
        lines.append(
            f"[{i}] trigger: \"{trigger}\"\n"
            f"    reaction: {reaction}\n"
            f"    z_delta: {z_delta}\n"
            f"    z_mode_shift: {z_mode_shift or 'none'}\n"
            f"    surface_effect: {surface_effect}\n"
            f"    example_response: {example}"
        )
    
    return "\n".join(lines), triggers


def llm_check_triggers(
    *,
    client: OpenAIResponsesClient,
    model: str,
    line: str,
    speaker_name: str,
    listener_name: str,
    listener_persona_data: Dict[str, Any],
    scene: str = "",
    context_lines: List[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    v3.2: LLMベースのトリガー判定。
    
    発話内容がリスナーのtriggerに該当するかをLLMが判断する。
    ハードコードされたキーワードマッチングではなく、
    文脈・意味・ニュアンスを考慮した判定が可能。
    
    Returns:
        {
            "triggered": [...],
            "total_z_delta": float,
            "final_z_mode_shift": str,
        }
    """
    triggers_text, triggers_list = format_triggers_for_llm(listener_persona_data)
    
    # トリガーが定義されてなければスキップ
    if not triggers_list:
        return {
            "triggered": [],
            "total_z_delta": 0.0,
            "final_z_mode_shift": "",
        }
    
    # コンテキスト構築
    context_block = ""
    if context_lines:
        context_block = f"[Recent dialogue]\n" + "\n".join(context_lines[-5:])
    
    system_prompt = f"""You are a trigger detection system for Z-Axis Translation v3.2.

Task: Determine whether the SPEAKER's line activates any of the LISTENER's emotional triggers.

## IMPORTANT
- Judge by MEANING and CONTEXT, not just keyword matching.
- A trigger can activate even if the exact words don't appear, as long as the 
  semantic content or emotional impact matches the trigger condition.
- Consider the scene context and conversation flow.
- Only mark triggers with confidence >= 0.5 as activated.
- Use the z_delta values from the trigger definitions (parse the +/- number).

## LISTENER'S TRIGGER DEFINITIONS
{triggers_text}

Output MUST follow the provided JSON schema. Do NOT include chain-of-thought."""

    user_prompt = f"""[Scene] {scene}

{context_block}

[Speaker] {speaker_name}
[Listener] {listener_name}
[Line] {line}

Which of {listener_name}'s triggers (if any) are activated by this line?"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    
    if dry_run:
        return {
            "triggered": [],
            "total_z_delta": 0.0,
            "final_z_mode_shift": "",
            "_dry_run": True,
        }
    
    _, result = client.create_structured(
        model=model,
        name="trigger_check_v32",
        schema=TRIGGER_CHECK_SCHEMA,
        messages=messages,
        max_output_tokens=500,
        temperature=0.3,
        dry_run=False,
    )
    
    return result


# =============================================================================
# DIALOGUE-SPECIFIC FUNCTIONS v3.2
# =============================================================================

def load_dialogue_config(config_path: str) -> Dict[str, Any]:
    """
    対話用YAML設定ファイルを読み込む。
    各ペルソナファイルも読み込んでマージする。
    """
    config_path = Path(config_path)
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    # ペルソナファイルを読み込み
    personas_raw = config.get('personas', {})
    personas = {}
    persona_data = {}
    
    for role, persona_file in personas_raw.items():
        persona_path = config_path.parent / persona_file
        if not persona_path.exists():
            persona_path = Path(persona_file)
        
        with open(persona_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        personas[role] = yaml.dump(data, allow_unicode=True, default_flow_style=False)
        persona_data[role] = data
    
    config['personas_yaml'] = personas
    config['persona_data'] = persona_data
    
    return config


def extract_original_speech_patterns(persona_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    ペルソナから original_speech_patterns を抽出（v3.1）。
    翻訳時の参照用。
    """
    language = persona_data.get('language', {})
    return language.get('original_speech_patterns', {})


def extract_translation_compensations(persona_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    ペルソナから translation_compensations を抽出（v3.1）。
    ターゲット言語での補償戦略。
    """
    language = persona_data.get('language', {})
    return language.get('translation_compensations', {})


def build_dialogue_context_v3(
    translated_turns: List[Dict[str, Any]],
    current_index: int,
    max_context_turns: int = 5,
    source_lang: str = "ja",
    target_lang: str = "en",
) -> str:
    """
    前の発話を context_block 形式で構築する（v3.1）。
    z_mode と arc_phase も含める。言語コードを動的に表示。
    """
    if not translated_turns:
        return ""
    
    start = max(0, current_index - max_context_turns)
    relevant_turns = translated_turns[start:current_index]
    
    source_code = get_lang_display(source_lang)
    target_code = get_lang_display(target_lang)
    
    context_lines = []
    for turn in relevant_turns:
        speaker = turn.get('speaker_name', turn.get('speaker', '???'))
        original = turn.get('original_line', '')
        translated = turn.get('translation', '')
        z_mode = turn.get('z_mode', 'none')
        arc_phase = turn.get('arc_phase', 'stable')
        
        context_lines.append(f"[{speaker}] (z_mode={z_mode}, arc={arc_phase}) {original}")
        if translated:
            context_lines.append(f"[{speaker} ({target_code})] {translated}")
    
    return "\n".join(context_lines)


def build_context_lines_for_trigger(
    translated_turns: List[Dict[str, Any]],
    current_index: int,
    max_lines: int = 5,
) -> List[str]:
    """
    v3.2: トリガー判定用のコンテキスト行を構築。
    LLMが文脈を理解するための直近の対話行。
    """
    if not translated_turns:
        return []
    
    start = max(0, current_index - max_lines)
    relevant = translated_turns[start:current_index]
    
    lines = []
    for turn in relevant:
        speaker = turn.get('speaker_name', turn.get('speaker', '???'))
        original = turn.get('original_line', '')
        lines.append(f"[{speaker}] {original}")
    
    return lines


def estimate_z_intensity_v3(
    base_intensity: str,
    z_delta: float,
    z_mode: str = "none",
) -> str:
    """
    基本強度とtriggerによる変化からz_intensityを推定（v3.0）。
    z_mode も考慮（collapse/shame/plea は高強度になりやすい）。
    """
    intensity_map = {'low': 0.3, 'medium': 0.6, 'high': 0.9}
    reverse_map = {0.3: 'low', 0.6: 'medium', 0.9: 'high'}
    
    base_val = intensity_map.get(base_intensity, 0.5)
    new_val = min(1.0, base_val + z_delta)
    
    # v3.0: z_mode による補正
    high_intensity_modes = ['collapse', 'shame', 'plea', 'rage']
    if z_mode in high_intensity_modes:
        new_val = max(new_val, 0.7)  # 最低でも high 寄りに
    
    closest = min(reverse_map.keys(), key=lambda x: abs(x - new_val))
    return reverse_map[closest]


def get_speaker_name(persona_data: Dict[str, Any]) -> str:
    """ペルソナデータから話者名を取得"""
    persona = persona_data.get('persona', {})
    return persona.get('name', persona.get('name_en', 'Unknown'))


def extract_z_info_from_result(translate_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    翻訳結果から z 関連情報を抽出（v3.0）。
    Layer A と z_signature から取得。
    """
    z_info = {
        'z': 0.5,
        'z_mode': 'none',
        'z_leak': [],
        'arc_phase': 'stable',
        'arc_id': '',
    }
    
    # STEP1 Layer A から
    step1 = translate_result.get('step1', {})
    layer_a = step1.get('layer_a', {})
    if layer_a:
        z_info['z'] = layer_a.get('z', 0.5)
        z_info['z_mode'] = layer_a.get('z_mode', 'none')
        z_info['z_leak'] = layer_a.get('z_leak', [])
    
    # STEP1 arc から
    arc = step1.get('arc', {})
    if arc:
        z_info['arc_phase'] = arc.get('arc_phase', 'stable')
        z_info['arc_id'] = arc.get('arc_id', '')
    
    # STEP3 z_signature で上書き（より正確）
    step3 = translate_result.get('step3', {})
    z_sig = step3.get('z_signature', {})
    if z_sig:
        z_info['z'] = z_sig.get('z', z_info['z'])
        z_info['z_mode'] = z_sig.get('z_mode', z_info['z_mode'])
        z_info['z_leak'] = z_sig.get('z_leak_applied', z_info['z_leak'])
    
    # STEP3 arc から
    step3_arc = step3.get('arc', {})
    if step3_arc:
        z_info['arc_phase'] = step3_arc.get('arc_phase', z_info['arc_phase'])
        z_info['arc_id'] = step3_arc.get('arc_id', z_info['arc_id'])
    
    return z_info


def build_compensation_context(
    persona_data: Dict[str, Any],
    target_lang: str,
) -> str:
    """
    v3.1: translation_compensations からターゲット言語用の補償戦略を構築。
    翻訳プロンプトに追加するコンテキスト。
    """
    compensations = extract_translation_compensations(persona_data)
    if not compensations:
        return ""
    
    lines = ["[TRANSLATION COMPENSATION STRATEGIES]"]
    
    # Register
    register = compensations.get('register', '')
    if register:
        lines.append(f"Register: {register}")
    
    # Tone keywords
    tone = compensations.get('tone_keywords', [])
    if tone:
        lines.append(f"Tone: {', '.join(tone)}")
    
    # Language-specific strategies
    strategies = compensations.get('strategies', {})
    lang_strategies = strategies.get(target_lang, [])
    if lang_strategies:
        lines.append(f"Strategies for {target_lang.upper()}:")
        for s in lang_strategies:
            lines.append(f"  - {s}")
    
    # Untranslatable elements (for awareness)
    untranslatable = compensations.get('untranslatable_elements', [])
    if untranslatable:
        lines.append("Untranslatable elements (compensate via other means):")
        for elem in untranslatable[:3]:  # Top 3
            lines.append(f"  - {elem.get('element', '')}: {elem.get('note', '')}")
    
    return "\n".join(lines)


# =============================================================================
# MAIN DIALOGUE TRANSLATION v3.2
# =============================================================================

def z_axis_dialogue_translate(
    *,
    client: OpenAIResponsesClient,
    model: str,
    config: Dict[str, Any],
    source_lang: Optional[str] = None,
    target_lang: Optional[str] = None,
    dry_run: bool = False,
    verbose: bool = True,
) -> Dict[str, Any]:
    """
    対話シーン全体を翻訳する（v3.2）。
    
    v3.2 changes:
    - LLM-based trigger detection (no more hardcoded keywords)
    - Trigger judgment considers meaning, context, and nuance
    - All persona triggers work regardless of character
    
    v3.1 changes:
    - source_lang / target_lang support
    - original_speech_patterns integration
    - translation_compensations context
    - Dynamic language display
    """
    personas_yaml = config['personas_yaml']
    persona_data = config['persona_data']
    dialogue = config.get('dialogue', [])
    scene = config.get('scene', '')
    relationships = config.get('relationships', {})
    
    # v3.1: 言語設定（CLI > YAML > default）
    source_lang = source_lang or config.get('source_lang', 'ja')
    target_lang = target_lang or config.get('target_lang', 'en')
    
    base_z_intensity = config.get('z_axis_intensity', 'medium')
    
    # 言語表示用コード
    source_code = get_lang_display(source_lang)
    target_code = get_lang_display(target_lang)
    
    # 話者名のマッピング
    speaker_names = {}
    for role, data in persona_data.items():
        speaker_names[role] = get_speaker_name(data)
    
    if verbose:
        print(f"\n🌐 Translation: {source_code} → {target_code}")
        print(f"   Scene: {scene}")
        print(f"   Personas: {speaker_names}")
    
    results = []
    accumulated_z = {role: 0.0 for role in personas_yaml.keys()}
    current_z_mode = {role: "none" for role in personas_yaml.keys()}  # z_mode追跡
    
    for i, turn in enumerate(dialogue):
        speaker_role = turn.get('speaker', 'A')
        line = turn.get('line', '')
        turn_z_override = turn.get('z_axis_intensity')
        turn_z_mode_override = turn.get('z_mode')
        
        speaker_name = speaker_names.get(speaker_role, speaker_role)
        persona_yaml = personas_yaml.get(speaker_role, '')
        speaker_persona_data = persona_data.get(speaker_role, {})
        
        if verbose:
            print(f"\n{'='*60}")
            print(f"Turn {i+1}: [{speaker_name}]")
            print(f"Original ({source_code}): {line}")
        
        # 相手役を特定
        other_roles = [r for r in personas_yaml.keys() if r != speaker_role]
        
        # v3.2: LLMベースのトリガー検出
        context_lines = build_context_lines_for_trigger(results, i)
        
        for other_role in other_roles:
            trigger_result = llm_check_triggers(
                client=client,
                model=model,
                line=line,
                speaker_name=speaker_name,
                listener_name=speaker_names[other_role],
                listener_persona_data=persona_data[other_role],
                scene=scene,
                context_lines=context_lines,
                dry_run=dry_run,
            )
            
            z_delta = trigger_result.get('total_z_delta', 0.0)
            z_mode_shift = trigger_result.get('final_z_mode_shift', '')
            triggered_items = trigger_result.get('triggered', [])
            
            if triggered_items and verbose:
                triggered_texts = [t.get('trigger_text', '') for t in triggered_items]
                print(f"  → Triggers for {speaker_names[other_role]}:")
                for t_item in triggered_items:
                    conf = t_item.get('confidence', 0)
                    reason = t_item.get('reasoning', '')
                    print(f"     [{conf:.2f}] {t_item.get('trigger_text', '')} — {reason}")
                print(f"     Δz={z_delta:+.2f}, mode_shift={z_mode_shift or 'none'}")
            
            accumulated_z[other_role] += z_delta
            if z_mode_shift and z_mode_shift != "none" and z_mode_shift != "":
                current_z_mode[other_role] = z_mode_shift
        
        # この話者のz_intensity/z_modeを計算
        speaker_z_mode = turn_z_mode_override or current_z_mode.get(speaker_role, "none")
        current_z = turn_z_override or estimate_z_intensity_v3(
            base_z_intensity,
            accumulated_z[speaker_role],
            speaker_z_mode,
        )
        
        if verbose:
            print(f"  Z-Intensity: {current_z} (Δz={accumulated_z[speaker_role]:+.2f})")
            print(f"  Z-Mode: {speaker_z_mode}")
        
        # Relationship取得
        relationship_key = f"{speaker_role}_to_{other_roles[0]}" if other_roles else ""
        relationship = relationships.get(relationship_key, '')
        
        # Context構築（v3.1: 言語コード対応）
        context_block = build_dialogue_context_v3(
            results, i,
            source_lang=source_lang,
            target_lang=target_lang,
        )
        if scene:
            context_block = f"[Scene] {scene}\n\n" + context_block
        
        # v3.1: translation_compensations を追加
        compensation_context = build_compensation_context(speaker_persona_data, target_lang)
        if compensation_context:
            context_block = context_block + "\n\n" + compensation_context
        
        # z_axis_translate を呼び出し（v3.0: arc_position追加）
        translate_result = z_axis_translate(
            client=client,
            model=model,
            persona_yaml=persona_yaml,
            scene=scene,
            relationship=relationship,
            context_block=context_block,
            target_line=line,
            target_lang=target_lang,
            z_axis_intensity=current_z,
            dry_run=dry_run,
            arc_position=i + 1,
        )
        
        # v3.0: z情報を抽出
        z_info = extract_z_info_from_result(translate_result) if not dry_run else {}
        
        # 結果を蓄積
        turn_result = {
            'turn': i + 1,
            'speaker': speaker_role,
            'speaker_name': speaker_name,
            'original_line': line,
            'z_intensity': current_z,
            'accumulated_z_delta': accumulated_z[speaker_role],
            # v3.0 additions
            'z': z_info.get('z', 0.5),
            'z_mode': z_info.get('z_mode', speaker_z_mode),
            'z_leak': z_info.get('z_leak', []),
            'arc_phase': z_info.get('arc_phase', 'stable'),
            'arc_id': z_info.get('arc_id', ''),
            'translation_data': translate_result,
        }
        
        # 翻訳結果を抽出
        if not dry_run and 'step3' in translate_result:
            translation = translate_result['step3'].get('translation', '')
            turn_result['translation'] = translation
            
            # z_mode を更新（次のターンに影響）
            actual_z_mode = z_info.get('z_mode', 'none')
            current_z_mode[speaker_role] = actual_z_mode
            
            if verbose:
                print(f"  Translation ({target_code}): {translation}")
                print(f"  Actual z_mode: {actual_z_mode}, arc_phase: {z_info.get('arc_phase', '?')}")
        
        results.append(turn_result)
    
    return {
        'version': '3.2',
        'source_lang': source_lang,
        'target_lang': target_lang,
        'scene': scene,
        'personas': {role: speaker_names[role] for role in personas_yaml.keys()},
        'turns': results,
    }


def print_dialogue_summary_v3(result: Dict[str, Any]) -> None:
    """対話翻訳結果のサマリーを表示（v3.1: 多言語対応）"""
    source_lang = result.get('source_lang', 'ja')
    target_lang = result.get('target_lang', 'en')
    source_code = get_lang_display(source_lang)
    target_code = get_lang_display(target_lang)
    
    print("\n" + "=" * 70)
    print(f"📖 DIALOGUE TRANSLATION SUMMARY v{result.get('version', '3.2')}")
    print("=" * 70)
    print(f"Scene: {result.get('scene', 'N/A')}")
    print(f"Translation: {source_code} → {target_code}")
    print(f"Personas: {result.get('personas', {})}")
    print("-" * 70)
    
    print(f"\n🎭 ORIGINAL ({source_code}) → TRANSLATED ({target_code})\n")
    
    for turn in result.get('turns', []):
        speaker = turn.get('speaker_name', '???')
        original = turn.get('original_line', '')
        translation = turn.get('translation', '(not translated)')
        z = turn.get('z', 0.5)
        z_mode = turn.get('z_mode', 'none')
        z_leak = turn.get('z_leak', [])
        arc_phase = turn.get('arc_phase', '?')
        
        print(f"[{speaker}] (z={z:.2f}, mode={z_mode}, arc={arc_phase})")
        print(f"  z_leak: {', '.join(z_leak) if z_leak else 'none'}")
        print(f"  {source_code}: {original}")
        print(f"  {target_code}: {translation}")
        print()


def list_languages():
    """Print supported languages."""
    print("Supported languages:")
    print("-" * 40)
    for code, info in SUPPORTED_LANGUAGES.items():
        print(f"  {code:4} : {info['name']} ({info['native']})")
    print()


# =============================================================================
# CLI
# =============================================================================

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Z-Axis Dialogue Translation System v3.2 (LLM-driven triggers)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Japanese → English (default)
  python z_axis_dialogue.py --config requests/subaru_rem_dialogue.yaml

  # English → Japanese
  python z_axis_dialogue.py --config requests/dialogue_en.yaml --target-lang ja

  # Chinese → English  
  python z_axis_dialogue.py --config requests/dialogue_zh.yaml --source-lang zh --target-lang en

  # List supported languages
  python z_axis_dialogue.py --list-languages

  # Quiet mode with JSON output
  python z_axis_dialogue.py --config requests/dialogue.yaml --quiet --output result.json
        """
    )
    ap.add_argument("--config", help="対話設定YAMLファイルのパス")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="使用するモデル")
    ap.add_argument("--source-lang", "-s", 
                    choices=list(SUPPORTED_LANGUAGES.keys()),
                    help="Source language (overrides YAML)")
    ap.add_argument("--target-lang", "-t",
                    choices=list(SUPPORTED_LANGUAGES.keys()),
                    help="Target language (overrides YAML)")
    ap.add_argument("--output", "-o", help="結果をJSONファイルに出力")
    ap.add_argument("--quiet", "-q", action="store_true", help="詳細出力を抑制")
    ap.add_argument("--dry-run", action="store_true", help="APIを叩かず設定確認のみ")
    ap.add_argument("--list-languages", action="store_true", help="List supported languages")
    
    args = ap.parse_args()
    
    # Handle --list-languages
    if args.list_languages:
        list_languages()
        return
    
    # Check required arguments
    if not args.config:
        ap.error("--config is required (unless using --list-languages)")
    
    config = load_dialogue_config(args.config)
    client = OpenAIResponsesClient()
    
    result = z_axis_dialogue_translate(
        client=client,
        model=args.model,
        config=config,
        source_lang=args.source_lang,
        target_lang=args.target_lang,
        dry_run=args.dry_run,
        verbose=not args.quiet,
    )
    
    if not args.quiet:
        print_dialogue_summary_v3(result)
    
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(result, indent=2, ensure_ascii=False, fp=f)
        print(f"\n✅ Result saved to: {args.output}")
    elif args.quiet:
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
