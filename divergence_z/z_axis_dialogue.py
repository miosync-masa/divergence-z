#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Z-Axis Dialogue Translation System v3.0
Operation: Babel Inverse — 対話シーン翻訳

複数のペルソナ間の対話を、Z軸（感情・葛藤構造）を保存しながら翻訳する。
z_axis_translate.py v3.0 をベースに、対話特有の機能を追加。

v3.0 Changes:
- z decomposition support (z + z_mode + z_leak)
- Layer A/B two-layer output handling
- arc tracking across dialogue turns
- z_mode_shift trigger detection

実行例:
  python z_axis_dialogue.py --config requests/subaru_rem_dialogue.yaml

YAML形式:
  personas:
    A: "personas/subaru_v3.yaml"
    B: "personas/rem_v3.yaml"
  
  scene: "白鯨戦後、精神的限界"
  relationships:
    A_to_B: "信頼、依存しつつある"
    B_to_A: "愛情、献身"
  
  dialogue:
    - speaker: A
      line: "俺は、俺が大嫌いだ"
    - speaker: B
      line: "レムは、スバルくんの味方です"
  
  target_lang: "en"
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
    )
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from z_axis_translate import (
        z_axis_translate,
        OpenAIResponsesClient,
        DEFAULT_MODEL,
        extract_v3_features,
    )

load_dotenv()


# =============================================================================
# DIALOGUE-SPECIFIC FUNCTIONS v3.0
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


def extract_triggers_v3(persona_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """ペルソナからtrigger情報を抽出（v3.0: z_mode_shift対応）"""
    return persona_data.get('triggers', [])


def check_triggers_v3(
    line: str, 
    listener_persona_data: Dict[str, Any],
    speaker_name: str,
) -> Tuple[float, str, List[str]]:
    """
    発話内容が聞き手のtriggerに該当するかチェック（v3.0）。
    
    Returns:
        (z_delta_total, z_mode_shift, triggered_list)
    """
    triggers = extract_triggers_v3(listener_persona_data)
    z_delta_total = 0.0
    z_mode_shift = ""
    triggered_list = []
    
    for t in triggers:
        trigger_text = t.get('trigger', '')
        
        keywords = extract_keywords(trigger_text)
        
        if any(kw.lower() in line.lower() for kw in keywords):
            z_delta_str = t.get('z_delta', '+0.0')
            z_delta = float(z_delta_str.replace('+', ''))
            z_delta_total += z_delta
            triggered_list.append(trigger_text)
            
            # v3.0: z_mode_shift を取得（最後にマッチしたものを使用）
            if t.get('z_mode_shift'):
                z_mode_shift = t.get('z_mode_shift')
    
    return z_delta_total, z_mode_shift, triggered_list


def extract_keywords(trigger_text: str) -> List[str]:
    """トリガーテキストからキーワードを抽出"""
    keywords = []
    
    match = re.search(r'[「『](.+?)[」』]', trigger_text)
    if match:
        keywords.append(match.group(1))
    
    english_words = re.findall(r'[a-zA-Z]+', trigger_text)
    keywords.extend(english_words)
    
    # v3.0: より多くのキーワードを追加
    important_ja = [
        '助手', '好き', '危険', '危機', '指摘', 'クリスティーナ', 'ゾンビ',
        '死', '失敗', '無力', '嫌い', '助け', '信じ', '期待', '大嫌い',
        '味方', '愛して', '頼む', '救え',
    ]
    for word in important_ja:
        if word in trigger_text:
            keywords.append(word)
    
    return keywords


def build_dialogue_context_v3(
    translated_turns: List[Dict[str, Any]],
    current_index: int,
    max_context_turns: int = 5,
) -> str:
    """
    前の発話を context_block 形式で構築する（v3.0）。
    z_mode と arc_phase も含める。
    """
    if not translated_turns:
        return ""
    
    start = max(0, current_index - max_context_turns)
    relevant_turns = translated_turns[start:current_index]
    
    context_lines = []
    for turn in relevant_turns:
        speaker = turn.get('speaker_name', turn.get('speaker', '???'))
        original = turn.get('original_line', '')
        translated = turn.get('translation', '')
        z_mode = turn.get('z_mode', 'none')
        arc_phase = turn.get('arc_phase', 'stable')
        
        context_lines.append(f"[{speaker}] (z_mode={z_mode}, arc={arc_phase}) {original}")
        if translated:
            context_lines.append(f"[{speaker} (EN)] {translated}")
    
    return "\n".join(context_lines)


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


# =============================================================================
# MAIN DIALOGUE TRANSLATION v3.0
# =============================================================================

def z_axis_dialogue_translate(
    *,
    client: OpenAIResponsesClient,
    model: str,
    config: Dict[str, Any],
    dry_run: bool = False,
    verbose: bool = True,
) -> Dict[str, Any]:
    """
    対話シーン全体を翻訳する（v3.0）。
    
    v3.0 changes:
    - z_mode tracking across turns
    - z_mode_shift trigger detection
    - arc_position passing
    - Layer A/B output handling
    """
    personas_yaml = config['personas_yaml']
    persona_data = config['persona_data']
    dialogue = config.get('dialogue', [])
    scene = config.get('scene', '')
    relationships = config.get('relationships', {})
    target_lang = config.get('target_lang', 'en')
    base_z_intensity = config.get('z_axis_intensity', 'medium')
    
    # 話者名のマッピング
    speaker_names = {}
    for role, data in persona_data.items():
        speaker_names[role] = get_speaker_name(data)
    
    results = []
    accumulated_z = {role: 0.0 for role in personas_yaml.keys()}
    current_z_mode = {role: "none" for role in personas_yaml.keys()}  # v3.0: z_mode追跡
    
    for i, turn in enumerate(dialogue):
        speaker_role = turn.get('speaker', 'A')
        line = turn.get('line', '')
        turn_z_override = turn.get('z_axis_intensity')
        turn_z_mode_override = turn.get('z_mode')  # v3.0: ターン単位の z_mode 上書き
        
        speaker_name = speaker_names.get(speaker_role, speaker_role)
        persona_yaml = personas_yaml.get(speaker_role, '')
        
        if verbose:
            print(f"\n{'='*60}")
            print(f"Turn {i+1}: [{speaker_name}]")
            print(f"Original: {line}")
        
        # 相手役を特定
        other_roles = [r for r in personas_yaml.keys() if r != speaker_role]
        
        # v3.0: Trigger検出（z_mode_shift対応）
        for other_role in other_roles:
            z_delta, z_mode_shift, triggered = check_triggers_v3(
                line, 
                persona_data[other_role],
                speaker_name,
            )
            if triggered and verbose:
                print(f"  → Triggers for {speaker_names[other_role]}: {triggered}")
                print(f"     Δz={z_delta:+.2f}, mode_shift={z_mode_shift or 'none'}")
            accumulated_z[other_role] += z_delta
            if z_mode_shift:
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
        
        # Context構築（v3.0）
        context_block = build_dialogue_context_v3(results, i)
        if scene:
            context_block = f"[Scene] {scene}\n\n" + context_block
        
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
            arc_position=i + 1,  # v3.0
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
            
            # v3.0: z_mode を更新（次のターンに影響）
            actual_z_mode = z_info.get('z_mode', 'none')
            current_z_mode[speaker_role] = actual_z_mode
            
            if verbose:
                print(f"  Translation: {translation}")
                print(f"  Actual z_mode: {actual_z_mode}, arc_phase: {z_info.get('arc_phase', '?')}")
        
        results.append(turn_result)
    
    return {
        'version': '3.0',
        'scene': scene,
        'target_lang': target_lang,
        'personas': {role: speaker_names[role] for role in personas_yaml.keys()},
        'turns': results,
    }


def print_dialogue_summary_v3(result: Dict[str, Any]) -> None:
    """対話翻訳結果のサマリーを表示（v3.0）"""
    print("\n" + "=" * 70)
    print("📖 DIALOGUE TRANSLATION SUMMARY v3.0")
    print("=" * 70)
    print(f"Scene: {result.get('scene', 'N/A')}")
    print(f"Target Language: {result.get('target_lang', 'N/A')}")
    print(f"Personas: {result.get('personas', {})}")
    print("-" * 70)
    
    print("\n🎭 ORIGINAL → TRANSLATED\n")
    
    for turn in result.get('turns', []):
        speaker = turn.get('speaker_name', '???')
        original = turn.get('original_line', '')
        translation = turn.get('translation', '(not translated)')
        z = turn.get('z', 0.5)
        z_mode = turn.get('z_mode', 'none')
        z_leak = turn.get('z_leak', [])
        arc_phase = turn.get('arc_phase', '?')
        
        # v3.0: より詳細な表示
        print(f"[{speaker}] (z={z:.2f}, mode={z_mode}, arc={arc_phase})")
        print(f"  z_leak: {', '.join(z_leak) if z_leak else 'none'}")
        print(f"  JA: {original}")
        print(f"  EN: {translation}")
        print()


# =============================================================================
# CLI
# =============================================================================

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Z-Axis Dialogue Translation System v3.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python z_axis_dialogue.py --config requests/subaru_rem_dialogue.yaml
  python z_axis_dialogue.py --config requests/dialogue.yaml --quiet
  python z_axis_dialogue.py --config requests/dialogue.yaml --output result.json
        """
    )
    ap.add_argument("--config", required=True, help="対話設定YAMLファイルのパス")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="使用するモデル")
    ap.add_argument("--output", "-o", help="結果をJSONファイルに出力")
    ap.add_argument("--quiet", "-q", action="store_true", help="詳細出力を抑制")
    ap.add_argument("--dry-run", action="store_true", help="APIを叩かず設定確認のみ")
    
    args = ap.parse_args()
    
    config = load_dialogue_config(args.config)
    client = OpenAIResponsesClient()
    
    result = z_axis_dialogue_translate(
        client=client,
        model=args.model,
        config=config,
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
