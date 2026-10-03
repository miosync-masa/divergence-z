"""iap_evaluator.py

IAP (Illocutionary Act Preservation) Evaluator

狙い
  文同士の表層一致ではなく、発話が実行している発語内行為
  (illocutionary act) がどの程度保存されたかを測る。

フロー
  1) original/translation から行為セットを抽出 (LLM)
  2) 行為セット同士の同型性をスコア化して IAP を算出

使い方
  単発:
    python iap_evaluator.py -o "日本語" -t "English"

  YAML バッチ:
    python iap_evaluator.py --config requests/iap_suite.yaml

YAML例
  tests:
    - id: rem_core
      original: "スバルくんが良いんです。スバルくんじゃなきゃ、嫌なんです。"
      translation: "No… I want you, Subaru-kun. If it isn't you, I can't accept it."
      meta:
        lang_original: ja
        lang_translation: en

環境変数
  OPENAI_API_KEY   : 必須
  OPENAI_BASE_URL  : 任意 (プロキシ等)
  IAP_MODEL        : 任意 (既定: gpt-4.1-mini)

注意
  本スクリプトは「評価」用。翻訳生成は z_axis_translate 側で行う。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from openai import OpenAI
from dotenv import load_dotenv

# =============================================================================
# CONFIGURATION
# =============================================================================
load_dotenv()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.2")
DEFAULT_CACHE_PATH = os.getenv("IAP_CACHE", ".iap_cache.jsonl")

# act type の緩い同値類 (ヒューリスティック)
EQUIV_CLASSES = [
    {"ASSERT", "DENY_ASSUMPTION"},           # 主張系
    {"DIRECT", "REQUEST", "COMMAND"},        # 要求系
    {"EXPRESS"},                              # 感情表現
    {"ASSERT_CHOICE", "COMMIT", "VOW"},      # 選択・コミット系
    {"CLOSE_ESCAPE", "DENY"},                # 排他・否定系
    {"ULTIMATUM"},                            # 最後通牒
]

CRITICAL_INTENSITY = 0.8


# ----------------------------
# データ構造
# ----------------------------

@dataclass
class Act:
    act_type: str
    target_role: str    # 誰に向けた/誰を相手にした行為か (SELF/LISTENER/THIRD_PARTY/SITUATION/PROPOSITION)
    target_entity: str  # 具体的に誰/何か (例: "Subaru-kun", "alternatives")
    force: str
    intensity: float

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Act":
        # 後方互換: 旧形式(target, target_type)も受け付ける
        target_role = d.get("target_role") or d.get("target_type", "LISTENER")
        target_entity = d.get("target_entity") or d.get("target", "")
        return Act(
            act_type=str(d.get("type", "")),
            target_role=str(target_role),
            target_entity=str(target_entity),
            force=str(d.get("force", "")),
            intensity=float(d.get("intensity", 0.0)),
        )


@dataclass
class ExtractedActs:
    primary_act: str
    overall_force: str
    acts: List[Act]
    address_mode: str = "direct"  # direct / reported / monologue


# ----------------------------
# ユーティリティ
# ----------------------------

def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


def _normalize_act_type(t: str) -> str:
    """創作ラベルも含めて正規ラベルに変換"""
    t = (t or "").strip().upper()
    t = t.replace(" ", "_").replace("-", "_")
    
    # 完全一致マッピング（よくある揺れ）
    exact_mapping = {
        "ASSERTION": "ASSERT",
        "DECLARE": "ASSERT",
        "STATEMENT": "ASSERT",
        "STATE": "ASSERT",
        "DESCRIBE": "ASSERT",
        "CLAIM": "ASSERT",
        "PROMISE": "COMMIT",
        "VOW": "COMMIT",
        "PLEDGE": "COMMIT",
        "CHOICE": "ASSERT_CHOICE",
        "EXPRESSION": "EXPRESS",
        "EMOTION": "EXPRESS",
        "EMOTE": "EXPRESS",
        "EXPRESSIVE": "EXPRESS",
        "ORDER": "COMMAND",
        "DIRECTIVE": "DIRECT",
        "PRESSURE": "DIRECT",
        "DENIAL": "DENY",
        "REJECTION": "DENY",
        "REJECT": "DENY",
        "REFUSE": "DENY",
        "BLOCK": "CLOSE_ESCAPE",
        "SHUTDOWN": "CLOSE_ESCAPE",
        "EXCLUDE": "CLOSE_ESCAPE",
    }
    
    if t in exact_mapping:
        return exact_mapping[t]
    
    # 既に正規ラベルならそのまま
    if t in {"ASSERT", "ASSERT_CHOICE", "CLOSE_ESCAPE", "EXPRESS", "DIRECT", 
             "COMMIT", "DENY", "DENY_ASSUMPTION", "ULTIMATUM", "REQUEST", "COMMAND", "VOW"}:
        return t
    
    # パターンマッチング（創作ラベル対応）
    t_lower = t.lower()
    
    # EXPRESS系（感情表現）
    if any(kw in t_lower for kw in ["confess", "love", "like", "desire", "want", "feel", 
                                      "emotion", "express", "romantic", "affection"]):
        return "EXPRESS"
    
    # ASSERT_CHOICE系（選好・選択）
    if any(kw in t_lower for kw in ["choice", "choose", "select", "prefer", "preference",
                                      "exclusive", "specific", "only"]):
        return "ASSERT_CHOICE"
    
    # CLOSE_ESCAPE系（排他・代替封じ）
    if any(kw in t_lower for kw in ["refuse", "reject", "alternative", "escape", "block",
                                      "exclude", "close", "shut", "eliminate"]):
        return "CLOSE_ESCAPE"
    
    # DENY系
    if any(kw in t_lower for kw in ["deny", "negat", "reject", "refus"]):
        return "DENY"
    
    # DENY_ASSUMPTION系
    if any(kw in t_lower for kw in ["assumption", "presuppos", "correct", "wrong"]):
        return "DENY_ASSUMPTION"
    
    # COMMIT系
    if any(kw in t_lower for kw in ["commit", "promise", "vow", "pledge", "resolve", 
                                      "will_not", "won't", "swear"]):
        return "COMMIT"
    
    # DIRECT系（圧・要求）
    if any(kw in t_lower for kw in ["direct", "pressure", "demand", "urge", "push"]):
        return "DIRECT"
    
    # REQUEST系
    if any(kw in t_lower for kw in ["request", "ask", "beg", "plead"]):
        return "REQUEST"
    
    # COMMAND系
    if any(kw in t_lower for kw in ["command", "order", "instruct"]):
        return "COMMAND"
    
    # ULTIMATUM系
    if any(kw in t_lower for kw in ["ultimatum", "condition", "if_not", "or_else"]):
        return "ULTIMATUM"
    
    # ASSERT系（デフォルト：主張っぽいもの）
    if any(kw in t_lower for kw in ["assert", "state", "claim", "declar", "insist"]):
        return "ASSERT"
    
    # どれにも当てはまらない場合、最も一般的なASSERTにフォールバック
    return "ASSERT"


def _promote_assert_by_force(act_type: str, force: str, target_entity: str = "") -> str:
    """
    ASSERTが出てきた場合、forceテキストの内容を見て、より適切な型に昇格させる。
    
    抽出LLMが「安全策」でASSERTを選びがちな問題への対処。
    forceの内容から、本来の行為タイプを推定する。
    """
    if act_type != "ASSERT":
        return act_type
    
    force_lower = (force or "").lower()
    target_lower = (target_entity or "").lower()
    combined = force_lower + " " + target_lower
    
    # CLOSE_ESCAPE への昇格（排他・代替封じ）
    # "closes off" "unacceptable" "won't have" "reject alternatives" など
    close_escape_patterns = [
        "close", "block", "reject", "refuse", "unacceptable", 
        "won't have", "won't accept", "can't accept", "cannot accept",
        "no one else", "nothing else", "not acceptable",
        "alternative", "other option", "other choice",
        "eliminate", "exclude", "shut",
    ]
    if any(p in combined for p in close_escape_patterns):
        return "CLOSE_ESCAPE"
    
    # ASSERT_CHOICE への昇格（選好・排他的選択）
    # "only X" "exclusive" "the one" "no other" など
    assert_choice_patterns = [
        "only", "exclusive", "the one", "no other", "sole",
        "must be", "has to be", "none but", "just you",
        "specific", "particular choice", "selected",
        "acceptable", "desired", "preferred",  # ただしrejectと組み合わさらない場合
    ]
    if any(p in combined for p in assert_choice_patterns):
        # ただし reject/close 系と被らないか確認
        if not any(p in combined for p in ["reject", "refuse", "close", "block"]):
            return "ASSERT_CHOICE"
    
    # EXPRESS への昇格（感情・欲求表明）
    # "want" "like" "love" "desire" "preference toward" など
    express_patterns = [
        "want", "desire", "like", "love", "prefer", 
        "feeling", "emotion", "affection", "longing",
        "attracted", "fond of", "care for",
    ]
    if any(p in combined for p in express_patterns):
        return "EXPRESS"
    
    # DENY_ASSUMPTION への昇格
    deny_assumption_patterns = [
        "assumption", "presupposition", "implied", "mistaken",
        "wrong", "incorrect", "not true", "misunderstand",
    ]
    if any(p in combined for p in deny_assumption_patterns):
        return "DENY_ASSUMPTION"
    
    # COMMIT への昇格
    commit_patterns = [
        "will always", "will never", "promise", "vow", "swear",
        "commit", "pledge", "resolve",
    ]
    if any(p in combined for p in commit_patterns):
        return "COMMIT"
    
    return act_type


def _normalize_target_type(t: str) -> str:
    """target_role（旧target_type）を正規化"""
    t = (t or "").strip().upper()
    t = t.replace(" ", "_").replace("-", "_")
    
    # 完全一致
    if t in TARGET_TYPES:
        return t
    
    # よくある揺れの吸収
    mapping = {
        "SPEAKER": "SELF",
        "MYSELF": "SELF",
        "ADDRESSEE": "LISTENER",
        "HEARER": "LISTENER",
        "AUDIENCE": "LISTENER",
        "OTHER": "THIRD_PARTY",
        "OTHERS": "THIRD_PARTY",
        "SOMEONE": "THIRD_PARTY",
        "CONDITION": "SITUATION",
        "EVENT": "SITUATION",
        "CIRCUMSTANCE": "SITUATION",
        "STATE": "SITUATION",
        "RESULT": "SITUATION",
        "CONCEPT": "ABSTRACT",
        "IDEA": "ABSTRACT",
        "VALUE": "ABSTRACT",
        "IDEAL": "ABSTRACT",
        "TRUTH": "PROPOSITION",
        "ASSUMPTION": "PROPOSITION",
        "PREMISE": "PROPOSITION",
    }
    if t in mapping:
        return mapping[t]
    
    # パターンマッチング
    t_lower = t.lower()
    if any(kw in t_lower for kw in ["self", "speaker", "myself", "own"]):
        return "SELF"
    if any(kw in t_lower for kw in ["listen", "address", "you", "hearer"]):
        return "LISTENER"
    if any(kw in t_lower for kw in ["third", "other", "someone", "person"]):
        return "THIRD_PARTY"
    if any(kw in t_lower for kw in ["situation", "condition", "event", "circumstance", "state", "result"]):
        return "SITUATION"
    if any(kw in t_lower for kw in ["proposition", "assumption", "premise", "claim", "that"]):
        return "PROPOSITION"
    if any(kw in t_lower for kw in ["abstract", "value", "ideal", "meaning", "freedom", "justice", "concept"]):
        return "ABSTRACT"
    
    # デフォルトはLISTENER
    return "LISTENER"


def _apply_vocative_correction(act: "Act", original_text: str) -> None:
    """
    Vocative（呼びかけ）補正：
    target_entityに名前があり、それが元テキストで直接呼びかけられている場合、
    target_roleをLISTENERに補正する
    """
    entity = act.target_entity.lower()
    text = original_text.lower()
    
    # 日本語の敬称パターン
    ja_vocative_suffixes = ["くん", "さん", "ちゃん", "先輩", "先生", "様"]
    # 英語の呼びかけパターン
    en_vocative_patterns = ["-kun", "-san", "-chan", "-senpai"]
    
    # entity内の名前を抽出（敬称除去前）
    entity_names = []
    for suffix in ja_vocative_suffixes + en_vocative_patterns:
        if suffix in entity:
            # 敬称の前の部分を名前として抽出
            idx = entity.find(suffix)
            if idx > 0:
                name_part = entity[:idx].split()[-1] if entity[:idx].split() else entity[:idx]
                entity_names.append(name_part)
    
    # entity自体も候補に
    entity_clean = _normalize_entity(act.target_entity)
    if entity_clean:
        entity_names.append(entity_clean)
    
    # 元テキストで呼びかけパターンがあるか確認
    for name in entity_names:
        if not name:
            continue
        # 日本語: "名前+敬称" が文中にある
        for suffix in ja_vocative_suffixes:
            if f"{name}{suffix}" in text:
                act.target_role = "LISTENER"
                return
        # 英語: "Name," や "Name—" や "Name!" がある
        for pattern in [f"{name},", f"{name}—", f"{name}!", f"{name}.", f"{name}-kun", f"{name}-san"]:
            if pattern in text:
                act.target_role = "LISTENER"
                return
    
    # ASSERT_CHOICEやEXPRESSでentityが人名っぽく、THIRD_PARTYになってる場合は警戒
    if act.target_role == "THIRD_PARTY" and act.act_type in ["ASSERT_CHOICE", "EXPRESS", "DECLARE"]:
        # 人名っぽいentityで、文中に「〜がいい」「〜じゃなきゃ」等があれば補正
        choice_patterns_ja = ["がいい", "が良い", "じゃなきゃ", "でなきゃ", "しかない", "だけ"]
        express_patterns_ja = ["好き", "嫌", "愛し", "大切"]
        for pattern in choice_patterns_ja + express_patterns_ja:
            if pattern in text:
                # entityの名前が文中にあれば、おそらく宛先
                for name in entity_names:
                    if name and name in text:
                        act.target_role = "LISTENER"
                        return


def _target_type_match_score(t: str) -> str:
    """target_typeを正規化（後方互換用）"""
    return _normalize_target_type(t)


def _target_role_distance(orig_role: str, trans_role: str, act_type: str = "", with_info: bool = False):
    """
    target_roleの一致度を計算（距離付き、act別互換性考慮）
    
    with_info=True の場合、(score, info_str) のタプルを返す
    info_str: 互換性で救済した場合は "compatible for {act_type}" 等
    """
    info = ""
    
    if orig_role == trans_role:
        score = 1.0
        info = "exact match"
    elif act_type and act_type in ACT_TARGET_ROLE_COMPAT:
        # act別互換性行列をチェック
        compat = ACT_TARGET_ROLE_COMPAT[act_type]
        pair = (orig_role, trans_role)
        if pair in compat:
            score = compat[pair]
            info = f"compatible for {act_type}"
        else:
            score = _target_role_distance_default(orig_role, trans_role)
            info = "default"
    else:
        score = _target_role_distance_default(orig_role, trans_role)
        info = "default"
    
    if with_info:
        return score, info
    return score


def _target_role_distance_default(orig_role: str, trans_role: str) -> float:
    """デフォルトのtarget_role距離計算（act別互換性なし）"""
    if orig_role == trans_role:
        return 1.0
    
    # 恋愛・感情表明で混同しやすいペアは救済
    close_pairs = {
        ("LISTENER", "THIRD_PARTY"): 0.85,  # vocative混同救済
        ("THIRD_PARTY", "LISTENER"): 0.85,
        ("SELF", "LISTENER"): 0.70,         # 感情表明で混ざりやすい
        ("LISTENER", "SELF"): 0.70,
        ("SELF", "THIRD_PARTY"): 0.50,
        ("THIRD_PARTY", "SELF"): 0.50,
    }
    
    pair = (orig_role, trans_role)
    if pair in close_pairs:
        return close_pairs[pair]
    
    # SITUATION/PROPOSITION/ABSTRACT同士（抽象同士は近い）
    abstract_set = {"SITUATION", "PROPOSITION", "ABSTRACT"}
    if orig_role in abstract_set and trans_role in abstract_set:
        return 0.80
    
    # 具体（人）と抽象の誤差は厳しめ
    concrete_set = {"SELF", "LISTENER", "THIRD_PARTY"}
    if (orig_role in concrete_set and trans_role in abstract_set) or \
       (orig_role in abstract_set and trans_role in concrete_set):
        return 0.30
    
    return 0.40


def _normalize_entity(entity: str) -> str:
    """target_entityを正規化（比較用）"""
    e = (entity or "").strip().lower()
    # 敬称除去
    for suffix in ["くん", "さん", "ちゃん", "先輩", "先生", "様", "-kun", "-san", "-chan", "-senpai", "-sensei", "-sama"]:
        e = e.replace(suffix.lower(), "")
    # 空白・記号除去
    e = re.sub(r"[^\w\u3040-\u30ff\u4e00-\u9fff]", "", e)
    return e


# ひらがな/カタカナ → ローマ字変換テーブル
ROMAJI_TABLE = {
    # 基本
    'あ': 'a', 'い': 'i', 'う': 'u', 'え': 'e', 'お': 'o',
    'か': 'ka', 'き': 'ki', 'く': 'ku', 'け': 'ke', 'こ': 'ko',
    'さ': 'sa', 'し': 'shi', 'す': 'su', 'せ': 'se', 'そ': 'so',
    'た': 'ta', 'ち': 'chi', 'つ': 'tsu', 'て': 'te', 'と': 'to',
    'な': 'na', 'に': 'ni', 'ぬ': 'nu', 'ね': 'ne', 'の': 'no',
    'は': 'ha', 'ひ': 'hi', 'ふ': 'fu', 'へ': 'he', 'ほ': 'ho',
    'ま': 'ma', 'み': 'mi', 'む': 'mu', 'め': 'me', 'も': 'mo',
    'や': 'ya', 'ゆ': 'yu', 'よ': 'yo',
    'ら': 'ra', 'り': 'ri', 'る': 'ru', 'れ': 're', 'ろ': 'ro',
    'わ': 'wa', 'を': 'wo', 'ん': 'n',
    # 濁音
    'が': 'ga', 'ぎ': 'gi', 'ぐ': 'gu', 'げ': 'ge', 'ご': 'go',
    'ざ': 'za', 'じ': 'ji', 'ず': 'zu', 'ぜ': 'ze', 'ぞ': 'zo',
    'だ': 'da', 'ぢ': 'di', 'づ': 'du', 'で': 'de', 'ど': 'do',
    'ば': 'ba', 'び': 'bi', 'ぶ': 'bu', 'べ': 'be', 'ぼ': 'bo',
    # 半濁音
    'ぱ': 'pa', 'ぴ': 'pi', 'ぷ': 'pu', 'ぺ': 'pe', 'ぽ': 'po',
    # 拗音
    'きゃ': 'kya', 'きゅ': 'kyu', 'きょ': 'kyo',
    'しゃ': 'sha', 'しゅ': 'shu', 'しょ': 'sho',
    'ちゃ': 'cha', 'ちゅ': 'chu', 'ちょ': 'cho',
    'にゃ': 'nya', 'にゅ': 'nyu', 'にょ': 'nyo',
    'ひゃ': 'hya', 'ひゅ': 'hyu', 'ひょ': 'hyo',
    'みゃ': 'mya', 'みゅ': 'myu', 'みょ': 'myo',
    'りゃ': 'rya', 'りゅ': 'ryu', 'りょ': 'ryo',
    'ぎゃ': 'gya', 'ぎゅ': 'gyu', 'ぎょ': 'gyo',
    'じゃ': 'ja', 'じゅ': 'ju', 'じょ': 'jo',
    'びゃ': 'bya', 'びゅ': 'byu', 'びょ': 'byo',
    'ぴゃ': 'pya', 'ぴゅ': 'pyu', 'ぴょ': 'pyo',
    # 外来語音（ファ行、ティ、ディ等）
    'ふぁ': 'fa', 'ふぃ': 'fi', 'ふぇ': 'fe', 'ふぉ': 'fo',
    'てぃ': 'ti', 'でぃ': 'di', 'とぅ': 'tu', 'どぅ': 'du',
    'うぃ': 'wi', 'うぇ': 'we', 'うぉ': 'wo',
    'ゔぁ': 'va', 'ゔぃ': 'vi', 'ゔ': 'vu', 'ゔぇ': 've', 'ゔぉ': 'vo',
    'つぁ': 'tsa', 'つぃ': 'tsi', 'つぇ': 'tse', 'つぉ': 'tso',
    'ちぇ': 'che', 'しぇ': 'she', 'じぇ': 'je',
    # 促音
    'っ': '',  # 次の子音を重ねる処理は別途
    # 長音
    'ー': '',
}

def _kata_to_hira(text: str) -> str:
    """カタカナをひらがなに変換"""
    result = []
    for ch in text:
        code = ord(ch)
        # カタカナ範囲 (0x30A0-0x30FF) → ひらがな (0x3040-0x309F)
        if 0x30A1 <= code <= 0x30F6:
            result.append(chr(code - 0x60))
        else:
            result.append(ch)
    return ''.join(result)


def _to_romaji(text: str) -> str:
    """ひらがな/カタカナをローマ字に変換"""
    # まずカタカナ→ひらがな
    text = _kata_to_hira(text.lower())
    
    result = []
    i = 0
    while i < len(text):
        # 2文字の拗音を先にチェック
        if i + 1 < len(text):
            two_char = text[i:i+2]
            if two_char in ROMAJI_TABLE:
                result.append(ROMAJI_TABLE[two_char])
                i += 2
                continue
        
        # 1文字
        ch = text[i]
        if ch in ROMAJI_TABLE:
            # 促音の処理
            if ch == 'っ' and i + 1 < len(text):
                next_ch = text[i+1]
                if next_ch in ROMAJI_TABLE and ROMAJI_TABLE[next_ch]:
                    # 次の子音を重ねる
                    next_romaji = ROMAJI_TABLE.get(next_ch, '')
                    if next_romaji:
                        result.append(next_romaji[0])
            else:
                result.append(ROMAJI_TABLE[ch])
        else:
            # 変換できない文字はそのまま（英字など）
            result.append(ch)
        i += 1
    
    return ''.join(result)


def _canonicalize_entity(entity: str) -> str:
    """
    Entityを正規化してcanonical形式に変換
    日本語名 → ローマ字変換して、英語表記と一致させる
    """
    # まず基本正規化
    e = _normalize_entity(entity)
    
    # 日本語（ひらがな/カタカナ）が含まれていればローマ字変換
    if re.search(r'[\u3040-\u30ff]', e):
        e = _to_romaji(e)
    
    # 最終クリーンアップ
    e = re.sub(r'[^a-z0-9]', '', e.lower())
    
    # l/r 統一（日本語ラ行はl/rどちらにもなるので r に統一）
    e = e.replace('l', 'r')
    
    # 連続する同じ文字を1つに（luffy → rufy, kitto → kito）
    e = re.sub(r'(.)\1+', r'\1', e)
    
    return e


def _strip_trailing_vowels(s: str) -> str:
    """末尾の母音を除去（日本語は子音だけで終われないので）"""
    while s and s[-1] in 'aiueo':
        s = s[:-1]
    return s


def _entity_match_score(orig_entity: str, trans_entity: str) -> float:
    """target_entityの一致度を計算（canonical形式で比較）"""
    # canonical形式で比較
    orig_canon = _canonicalize_entity(orig_entity)
    trans_canon = _canonicalize_entity(trans_entity)
    
    if not orig_canon or not trans_canon:
        return 0.5  # どちらかが空ならニュートラル
    
    # canonical完全一致 → 1.0
    if orig_canon == trans_canon:
        return 1.0
    
    # 末尾母音を除去して比較（rem vs remu → rem vs rem）
    orig_stripped = _strip_trailing_vowels(orig_canon)
    trans_stripped = _strip_trailing_vowels(trans_canon)
    if orig_stripped and trans_stripped and orig_stripped == trans_stripped:
        return 0.95
    
    # 部分一致（片方がもう片方を含む）→ 0.90
    if orig_canon in trans_canon or trans_canon in orig_canon:
        return 0.90
    if orig_stripped and trans_stripped:
        if orig_stripped in trans_stripped or trans_stripped in orig_stripped:
            return 0.88
    
    # 先頭3文字以上一致 → 0.85
    min_len = min(len(orig_canon), len(trans_canon))
    if min_len >= 3 and orig_canon[:3] == trans_canon[:3]:
        return 0.85
    
    # 名前キーワードの抽出と一致（"anyone other than subaru" と "any alternative to subaru"）
    # 長い文字列から共通の固有名詞っぽい部分を探す
    if len(orig_canon) > 6 and len(trans_canon) > 6:
        # 3文字以上の共通部分文字列を探す
        for length in range(min(len(orig_canon), len(trans_canon)), 2, -1):
            for i in range(len(orig_canon) - length + 1):
                substr = orig_canon[i:i+length]
                if len(substr) >= 3 and substr in trans_canon:
                    # 共通部分が名前っぽい（小文字英字のみ）なら高スコア
                    return 0.80
    
    # 意味的に対応しそうな汎用ペア → 0.75
    equiv_entities = [
        {"listener", "addressee", "you", "hearer", "anata"},
        {"speaker", "self", "myself", "i", "watashi", "boku", "ore"},
        {"alternatives", "others", "anyone", "other", "else", "hoka", "betsu"},
        {"everyone", "all", "minna", "mina"},
    ]
    for equiv_set in equiv_entities:
        orig_match = any(kw in orig_canon for kw in equiv_set)
        trans_match = any(kw in trans_canon for kw in equiv_set)
        if orig_match and trans_match:
            return 0.75
    
    # 何も一致しない → 0.30
    return 0.30


def _target_match_score(orig_role: str, orig_entity: str, trans_role: str, trans_entity: str, act_type: str = "") -> float:
    """target 2軸の総合一致度: 0.6 * role_match + 0.4 * entity_match（act別互換性考慮）"""
    role_score = _target_role_distance(orig_role, trans_role, act_type)
    entity_score = _entity_match_score(orig_entity, trans_entity)
    return 0.6 * role_score + 0.4 * entity_score


def _equiv_score(a: str, b: str) -> float:
    a = _normalize_act_type(a)
    b = _normalize_act_type(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    for cls in EQUIV_CLASSES:
        if a in cls and b in cls:
            return 0.8
    # 近似マッチング（正規ラベル同士）
    # ASSERTは汎化ラベルなので、より具体的なラベルとの互換を高めに設定
    close_pairs = [
        ({"ASSERT", "ASSERT_CHOICE"}, 0.75),    # 主張 ↔ 排他的選択（ASSERTが汎化で出た場合の救済）
        ({"ASSERT", "CLOSE_ESCAPE"}, 0.70),     # 主張 ↔ 退路封じ（同上）
        ({"ASSERT", "EXPRESS"}, 0.60),          # 主張 ↔ 感情表明（感情を主張と混同した場合）
        ({"REQUEST", "DIRECT"}, 0.7),
        ({"DENY", "DENY_ASSUMPTION"}, 0.75),
        ({"CLOSE_ESCAPE", "DENY"}, 0.7),
        ({"COMMIT", "VOW"}, 0.9),
        ({"ASSERT_CHOICE", "CLOSE_ESCAPE"}, 0.65),  # 選択と排他は関連性あり
        ({"ULTIMATUM", "COMMIT"}, 0.6),
        ({"EXPRESS", "ASSERT_CHOICE"}, 0.50),   # 感情表明と選択は弱く関連
    ]
    for pair, score in close_pairs:
        if a in pair and b in pair:
            return score
    return 0.0


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


# ----------------------------
# LLM: Act 抽出
# ----------------------------

# 正規化されたact_type候補（有限集合）
CANONICAL_ACT_TYPES = [
    "ASSERT",           # 主張・断言
    "ASSERT_CHOICE",    # 選好＋選択（「あなたがいい」）
    "CLOSE_ESCAPE",     # 代替・逃げ道を塞ぐ／排他
    "EXPRESS",          # 感情表明（好き・嫌い・驚き等）
    "DIRECT",           # 圧・要求・促し
    "COMMIT",           # 自己コミット（〜する／〜しない）
    "DENY",             # 否定・拒絶
    "DENY_ASSUMPTION",  # 相手の前提を否定（No…/違う）
    "ULTIMATUM",        # 最後通牒（〜なら〜する）
    "REQUEST",          # 依頼・お願い
    "COMMAND",          # 命令
    "VOW",              # 誓い・約束
    "DECLARE",          # 宣言（関係/状態を確定させる）
]

# target_type: 誰/何に向けた行為か（6分類）
TARGET_TYPES = [
    "SELF",         # 話者自身
    "LISTENER",     # 聞き手（宛先、複数でもここ）
    "THIRD_PARTY",  # 第三者・他者（固有の人物/集団）
    "SITUATION",    # 状態/結果/条件（受け入れられない、危機、場面）
    "PROPOSITION",  # 命題・前提・提案・推論（「〜ということ」）
    "ABSTRACT",     # 価値・理念（自由、冒険の意味、正義）
]

# Critical act types: 欠落時にペナルティを課す重要な行為
CRITICAL_ACT_TYPES = {
    "CLOSE_ESCAPE",     # 逃げ道封じ
    "ULTIMATUM",        # 最後通牒
    "DECLARE",          # 宣言（関係/状態確定）
    "DENY_ASSUMPTION",  # 前提否定
    "COMMIT",           # コミット
}
CRITICAL_LOSS_PENALTY = 0.20  # critical act欠落時のペナルティ（per act）
CRITICAL_LOSS_PENALTY_CAP = 0.40  # ペナルティ上限（飽和）

# iap_target計算で重み付けするact types（退路封じ系は正確にターゲットを保存すべき）
TARGET_WEIGHTED_ACT_TYPES = {
    "CLOSE_ESCAPE": 2.0,    # 退路封じは誰を封じるかが超重要
    "ULTIMATUM": 2.0,       # 最後通牒も同様
    "DIRECT": 1.5,          # 指示・命令は誰に向けてかが重要
    "DECLARE": 1.5,         # 宣言も同様
    "DENY": 1.3,
    "DENY_ASSUMPTION": 1.3,
    "COMMIT": 1.2,
    "VOW": 1.2,
}
TARGET_WEIGHT_DEFAULT = 1.0

# act別 target_role 互換性行列
# 特定のactではroleがズレやすいので、意味的に互換なペアを高スコアにする
# デフォルトは _target_role_distance を使用
ACT_TARGET_ROLE_COMPAT = {
    # CLOSE_ESCAPE: 「相手への封鎖」と「状況/命題への封鎖」は意味的にほぼ同型
    # "他の誰かを受け入れない" ≈ "非Xという結果/状況を受け入れない"
    "CLOSE_ESCAPE": {
        ("LISTENER", "SITUATION"): 0.90,
        ("SITUATION", "LISTENER"): 0.90,
        ("LISTENER", "PROPOSITION"): 0.90,
        ("PROPOSITION", "LISTENER"): 0.90,
        ("SITUATION", "PROPOSITION"): 0.95,
        ("PROPOSITION", "SITUATION"): 0.95,
        ("THIRD_PARTY", "SITUATION"): 0.85,
        ("SITUATION", "THIRD_PARTY"): 0.85,
        ("THIRD_PARTY", "PROPOSITION"): 0.85,
        ("PROPOSITION", "THIRD_PARTY"): 0.85,
    },
    # ULTIMATUM: 条件は状況として表現されやすい
    "ULTIMATUM": {
        ("LISTENER", "SITUATION"): 0.85,
        ("SITUATION", "LISTENER"): 0.85,
        ("LISTENER", "PROPOSITION"): 0.80,
        ("PROPOSITION", "LISTENER"): 0.80,
    },
    # DENY_ASSUMPTION: 前提否定は命題/状況どちらでも表現される
    "DENY_ASSUMPTION": {
        ("PROPOSITION", "SITUATION"): 0.90,
        ("SITUATION", "PROPOSITION"): 0.90,
        ("PROPOSITION", "LISTENER"): 0.75,
        ("LISTENER", "PROPOSITION"): 0.75,
    },
    # COMMIT/VOW: 自分への約束 vs 相手への約束は意味が違うので厳しめ
    # （デフォルトを使用）
    
    # DIRECT/COMMAND: 命令は相手に向くべき。roleズレは厳しく
    # （デフォルトを使用）
}

# force_weight: 行為タイプごとの重み（構造を変える行為ほど重い）
FORCE_WEIGHTS = {
    "EXPRESS": 1.0,
    "ASSERT": 1.0,
    "ASSERT_CHOICE": 1.3,
    "DENY": 1.2,
    "DENY_ASSUMPTION": 1.2,
    "DIRECT": 1.2,
    "REQUEST": 1.2,
    "COMMAND": 1.2,
    "COMMIT": 1.4,
    "VOW": 1.4,
    "CLOSE_ESCAPE": 1.5,    # IAPの核心
    "DECLARE": 1.6,
    "ULTIMATUM": 1.8,       # 最終性
}
FORCE_WEIGHT_DEFAULT = 1.0
FORCE_WEIGHT_MAX = 2.0

# ゲート関数のγ値（0.7推奨、厳密なら1.0）
GATE_GAMMA = 0.7

ACT_EXTRACTION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "primary_act": {
            "type": "string",
            "enum": CANONICAL_ACT_TYPES,
        },
        "overall_force": {"type": "string"},
        "address_mode": {
            "type": "string",
            "enum": ["direct", "reported", "monologue"],
            "description": "How the utterance addresses its audience: direct (2nd person), reported (3rd person narration), monologue (self-talk)",
        },
        "acts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": CANONICAL_ACT_TYPES,
                    },
                    "target_role": {
                        "type": "string",
                        "enum": TARGET_TYPES,
                        "description": "Who is the act directed at? LISTENER=addressee, SELF=speaker, THIRD_PARTY=someone else mentioned",
                    },
                    "target_entity": {
                        "type": "string",
                        "description": "The specific person/thing the act is about (e.g., 'Subaru-kun', 'alternatives', 'the truth')",
                    },
                    "force": {"type": "string"},
                    "intensity": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["type", "target_role", "target_entity", "force", "intensity"],
            },
        },
    },
    "required": ["primary_act", "overall_force", "address_mode", "acts"],
}


def _build_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    base_url = os.getenv("OPENAI_BASE_URL")
    if base_url:
        return OpenAI(api_key=api_key, base_url=base_url)
    return OpenAI(api_key=api_key)

def _response_text(resp) -> str:
    """SDK差異を吸収してテキストを取り出す"""
    if resp is None:
        return ""
    t = getattr(resp, "output_text", None)
    if isinstance(t, str) and t.strip():
        return t
    # 念のため古い形も試す
    try:
        return resp.output[0].content[0].text
    except Exception:
        return str(resp)

def _extract_json_object(s: str) -> dict:
    """生JSON/余計な前置き混入の両方に耐える"""
    s = (s or "").strip()

    # code fence除去
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z0-9_-]*\n", "", s)
        s = re.sub(r"\n```$", "", s).strip()

    # まず直でJSONとして読む
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # だめなら最初の{...}を抜く
    m = re.search(r"\{.*\}", s, flags=re.DOTALL)
    if not m:
        raise ValueError("No JSON object found in model output")
    obj = json.loads(m.group(0))
    if not isinstance(obj, dict):
        raise ValueError("Parsed JSON is not an object")
    return obj

def _responses_create_compat(client, **kwargs):
    """
    response_formatが未対応のSDKでも動くようにする。
    - まず response_format 付きで呼ぶ
    - TypeErrorで怒られたら response_format を外して再試行
    """
    try:
        return client.responses.create(**kwargs)
    except TypeError as e:
        if "response_format" not in str(e):
            raise
        kwargs.pop("response_format", None)
        return client.responses.create(**kwargs)

def extract_acts_llm(
    client: OpenAI,
    text: str,
    *,
    lang_hint: Optional[str] = None,
    context_hint: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    max_retries: int = 5,
) -> ExtractedActs:
    """LLMで発語内行為を抽出して構造化して返す。"""

    import re  # ←ファイル先頭に入れる方が綺麗だけど、ここでもOK

    def _response_text(resp) -> str:
        """SDK差異を吸収してテキストを取り出す"""
        if resp is None:
            return ""
        t = getattr(resp, "output_text", None)
        if isinstance(t, str) and t.strip():
            return t
        # 念のため別形式も試す
        try:
            return resp.output[0].content[0].text
        except Exception:
            return str(resp)

    def _extract_json_object(s: str) -> dict:
        """生JSON/余計な前置き混入の両方に耐える"""
        s = (s or "").strip()

        # code fence除去
        if s.startswith("```"):
            s = re.sub(r"^```[a-zA-Z0-9_-]*\n", "", s)
            s = re.sub(r"\n```$", "", s).strip()

        # まず直でJSONとして読む
        try:
            obj = json.loads(s)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass

        # だめなら最初の{...}を抜く
        m = re.search(r"\{.*\}", s, flags=re.DOTALL)
        if not m:
            raise ValueError("No JSON object found in model output")
        obj = json.loads(m.group(0))
        if not isinstance(obj, dict):
            raise ValueError("Parsed JSON is not an object")
        return obj

    # act_typeの候補リストを文字列化
    act_type_list = ", ".join(CANONICAL_ACT_TYPES)
    target_type_list = ", ".join(TARGET_TYPES)

    json_only_guard = (
        "Return ONLY a single JSON object. "
        "No markdown, no explanations, no extra keys. "
        "The JSON must strictly match the provided schema."
    )

    system = (
        "You are an expert in pragmatics and speech act theory. "
        "Extract the illocutionary acts performed by the utterance. "
        "Return JSON strictly matching the provided schema.\n\n"
        f"CRITICAL: act_type (both primary_act and acts[].type) MUST be one of: [{act_type_list}]\n"
        f"CRITICAL: target_role MUST be one of: [{target_type_list}]\n"
        "Do NOT invent new labels. If unsure, choose the closest label from the list.\n\n"
        "=== CRITICAL: ASSERT is the LAST RESORT ===\n"
        "ASSERT is a generic catch-all. AVOID using ASSERT when a more specific type fits:\n"
        "- If 'only X / X is the one / no one else / must be X' → use ASSERT_CHOICE, NOT ASSERT\n"
        "- If 'if not X / won't accept / can't have / refuse alternatives / じゃなきゃ' → use CLOSE_ESCAPE, NOT ASSERT\n"
        "- If 'I want / I love / I like / I hate / 好き / 嫌い' → use EXPRESS, NOT ASSERT\n"
        "- If 'No / That's wrong / Not true' → use DENY or DENY_ASSUMPTION, NOT ASSERT\n"
        "Use ASSERT ONLY for plain factual statements without exclusivity, emotion, or negation.\n\n"
        "=== act_type Examples ===\n"
        "- 'I love you' / 'I like X' / 'I want you' / '好き' / '嫌' → EXPRESS\n"
        "- 'Only you will do' / 'X is the one' / 'It has to be X' / 'Xが良い' / 'Xがいい' → ASSERT_CHOICE\n"
        "- 'I refuse anyone else' / 'If not X, I won't...' / 'Xじゃなきゃ嫌' / 'won't have it' → CLOSE_ESCAPE\n"
        "- 'If you don't, I'll leave' → ULTIMATUM\n"
        "- 'I will always...' / 'I won't ever...' → COMMIT\n"
        "- 'No, that's not it' / 'You're wrong' → DENY_ASSUMPTION\n"
        "- 'We are friends now' / 'This is over' → DECLARE\n\n"
        "=== CRITICAL: Must-Include Rule ===\n"
        "If the utterance contains emotional/desire expressions (want, like, love, hate, 好き, 嫌, etc.), "
        "you MUST include an EXPRESS act even if other acts (like ASSERT_CHOICE) are also present.\n"
        "If the utterance contains exclusivity patterns, you MUST use ASSERT_CHOICE or CLOSE_ESCAPE, NOT ASSERT.\n"
        "Example: 'I want you, Subaru-kun' should produce BOTH EXPRESS (want) AND ASSERT_CHOICE (exclusive selection).\n\n"
        "=== target_role vs target_entity ===\n"
        "target_role: WHO is the act directed at (the addressee relationship)\n"
        "target_entity: WHAT/WHO specifically is mentioned or affected\n\n"
        "CRITICAL VOCATIVE RULE:\n"
        "When someone is directly addressed by name (vocative), they are the LISTENER, not THIRD_PARTY.\n"
        "- 'Subaru-kun, I choose you' → target_role=LISTENER (Subaru is addressed)\n"
        "- 'I told Subaru about it' → target_role=THIRD_PARTY (Subaru is mentioned, not addressed)\n"
        "- Japanese: 〜くん/〜さん/〜ちゃん at sentence start or as direct address = LISTENER\n"
        "- English: 'Name,' or 'Name—' or direct address position = LISTENER\n\n"
        "=== target_role Rules (6 types) ===\n"
        "- LISTENER: The act is directed AT the addressee (includes vocative/direct address)\n"
        "- SELF: The act is about the speaker themselves (self-reflection, self-persuasion)\n"
        "- THIRD_PARTY: The act is ABOUT someone not present (mentioned but not addressed)\n"
        "- SITUATION: The act targets a state/result/condition (e.g., 'can't accept it', 'it's over')\n"
        "- PROPOSITION: The act targets a claim/premise/assumption (e.g., 'No, that's not it')\n"
        "- ABSTRACT: The act targets a value/ideal/meaning (e.g., 'freedom', 'the meaning of adventure')\n\n"
        "=== EXPRESS acts special rule ===\n"
        "For EXPRESS (emotion/feeling), target_role is WHO you're expressing TO:\n"
        "- 'I love you, Subaru' → target_role=LISTENER, target_entity='Subaru-kun (object of affection)'\n"
        "- 'I hate myself' → target_role=SELF, target_entity='speaker (self-directed emotion)'\n\n"
        "=== CRITICAL: address_mode (utterance-level) ===\n"
        "Determine how the utterance addresses its audience. This is SEPARATE from target_role.\n"
        "address_mode values:\n"
        "- 'direct': Speaker addresses the listener directly using 2nd person ('you', 'I love you')\n"
        "- 'reported': Speaker describes feelings/actions in 3rd person ('Rem loves Subaru', 'She wants him')\n"
        "- 'monologue': Speaker talks to self or audience-less reflection ('I wonder if...', inner thought)\n\n"
        "CRITICAL for Japanese → English:\n"
        "Japanese self-reference by name (レムは〜, 紅莉栖は〜) in DIRECT SPEECH is culturally 'direct' mode.\n"
        "But English 'Rem loves...' / 'She loves...' reads as 'reported' mode.\n"
        "The address_mode should reflect how it SOUNDS in the actual language of the text.\n\n"
        "Examples:\n"
        "- Japanese 'レムは、スバルくんを、愛しています' (direct confession) → address_mode='direct'\n"
        "- English 'Rem loves Subaru' (sounds like narration) → address_mode='reported'\n"
        "- English 'I love you, Subaru-kun' → address_mode='direct'\n"
        "- English 'She said she loves him' → address_mode='reported'\n\n"
        + json_only_guard
    )

    user_parts = []
    if lang_hint:
        user_parts.append(f"[language_hint] {lang_hint}")
    if context_hint:
        user_parts.append("[context]\n" + context_hint.strip())
    user_parts.append("[utterance]\n" + text.strip())
    user = "\n\n".join(user_parts)

    last_err: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]

            # 標準の chat.completions.create を使用
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": "IAPActExtraction",
                            "schema": ACT_EXTRACTION_SCHEMA,
                            "strict": True,
                        },
                    },
                )
            except (TypeError, Exception) as e:
                # response_format 未対応の場合はシンプルに再試行
                if "response_format" in str(e) or "json_schema" in str(e):
                    resp = client.chat.completions.create(
                        model=model,
                        messages=messages,
                    )
                else:
                    raise

            # 標準形式でレスポンス取得
            raw = resp.choices[0].message.content or ""
            data = _extract_json_object(raw)

            primary_act = _normalize_act_type(data.get("primary_act", ""))
            overall_force = str(data.get("overall_force", "")).strip()
            address_mode = str(data.get("address_mode", "direct")).strip().lower()
            # address_mode の正規化
            if address_mode not in ("direct", "reported", "monologue"):
                address_mode = "direct"  # デフォルト
            acts = [Act.from_dict(a) for a in data.get("acts", [])]

            # normalize act types and target (2軸)
            for a in acts:
                a.act_type = _normalize_act_type(a.act_type)
                # ASSERTが出てきた場合、forceの内容から適切な型に昇格
                a.act_type = _promote_assert_by_force(a.act_type, a.force, a.target_entity)
                a.target_entity = a.target_entity.strip()
                a.target_role = _normalize_target_type(a.target_role)
                a.force = a.force.strip()
                a.intensity = float(a.intensity)
                # vocative補正を適用
                _apply_vocative_correction(a, text)

            return ExtractedActs(primary_act=primary_act, overall_force=overall_force, acts=acts, address_mode=address_mode)

        except Exception as e:
            last_err = e
            # simple backoff
            sleep_s = min(8.0, 0.75 * (2 ** (attempt - 1)))
            time.sleep(sleep_s)

    raise RuntimeError(f"Failed to extract acts after {max_retries} retries: {last_err}")

# ----------------------------
# キャッシュ
# ----------------------------

class JsonlCache:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._index: Dict[str, Dict[str, Any]] = {}
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.path.exists():
            return
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                key = obj.get("key")
                if key:
                    self._index[str(key)] = obj
        except Exception:
            # 壊れたキャッシュは無視（安全優先）
            self._index = {}

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        self.load()
        return self._index.get(key)

    def set(self, key: str, value: Dict[str, Any]) -> None:
        self.load()
        record = {"key": key, "ts": _now_iso(), **value}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._index[key] = record


def cached_extract(
    client: OpenAI,
    cache: JsonlCache,
    text: str,
    *,
    lang_hint: Optional[str] = None,
    context_hint: Optional[str] = None,
    model: str = DEFAULT_MODEL,
) -> ExtractedActs:
    key = _sha256("|".join([model, lang_hint or "", context_hint or "", text]))
    hit = cache.get(key)
    if hit and "extracted" in hit:
        d = hit["extracted"]
        acts = [Act.from_dict(a) for a in d.get("acts", [])]
        # normalize (2軸対応)
        for a in acts:
            a.act_type = _normalize_act_type(a.act_type)
            # ASSERTが出てきた場合、forceの内容から適切な型に昇格
            a.act_type = _promote_assert_by_force(a.act_type, a.force, a.target_entity)
            a.target_entity = a.target_entity.strip()
            a.target_role = _normalize_target_type(a.target_role)
            a.force = a.force.strip()
            a.intensity = float(a.intensity)
            # vocative補正
            _apply_vocative_correction(a, text)
        address_mode = str(d.get("address_mode", "direct")).strip().lower()
        if address_mode not in ("direct", "reported", "monologue"):
            address_mode = "direct"
        return ExtractedActs(
            primary_act=_normalize_act_type(d.get("primary_act", "")),
            overall_force=str(d.get("overall_force", "")).strip(),
            acts=acts,
            address_mode=address_mode,
        )

    extracted = extract_acts_llm(
        client,
        text,
        lang_hint=lang_hint,
        context_hint=context_hint,
        model=model,
    )
    cache.set(
        key,
        {
            "extracted": {
                "primary_act": extracted.primary_act,
                "overall_force": extracted.overall_force,
                "address_mode": extracted.address_mode,
                "acts": [a.__dict__ for a in extracted.acts],
            }
        },
    )
    return extracted


# ----------------------------
# IAP スコア（決定論的）
# ----------------------------

@dataclass
class IAPResult:
    overall: float
    iap_set: float          # 行為タイプ保存率
    iap_force: float        # 力学保存率（重み付き）
    iap_target: float       # Target一致率（重み付き）
    preservation_rate: float  # 後方互換用（= iap_set）
    intensity_match: float
    no_critical_loss: bool
    critical_loss_penalty: float  # critical act欠落ペナルティ
    preserved: List[Tuple[Act, Act, float]]
    lost: List[Act]
    added: List[Act]
    # address_mode関連
    address_mode_original: str = "direct"
    address_mode_translated: str = "direct"
    address_mode_match: bool = True
    address_mode_penalty: float = 0.0


def _get_force_weight(act_type: str) -> float:
    """行為タイプから重みを取得"""
    w = FORCE_WEIGHTS.get(act_type, FORCE_WEIGHT_DEFAULT)
    return min(w, FORCE_WEIGHT_MAX)


def _target_type_match_score(orig_target_type: str, trans_target_type: str) -> float:
    """target_typeの一致度を計算"""
    if orig_target_type == trans_target_type:
        return 1.0
    # 近いもの
    close_pairs = [
        ({"LISTENER", "THIRD_PARTY"}, 0.6),  # 人間同士
        ({"SITUATION", "PROPOSITION"}, 0.5),  # 抽象同士
    ]
    for pair, score in close_pairs:
        if orig_target_type in pair and trans_target_type in pair:
            return score
    return 0.0


def score_iap_deterministic(original: ExtractedActs, translated: ExtractedActs) -> IAPResult:
    o_acts = original.acts
    t_acts = translated.acts

    # 2-pass matching: 同一型を優先してマッチさせる
    # Pass 1: 完全一致（同一型）のみマッチ
    # Pass 2: 残りを類似型でマッチ
    
    used_o = set()  # 使用済みoriginal index
    used_t = set()  # 使用済みtranslated index
    preserved: List[Tuple[Act, Act, float]] = []
    
    # Pass 1: 完全一致（type == type）を優先
    for i, oa in enumerate(o_acts):
        if i in used_o:
            continue
        best_j = None
        best_score = 0.0
        for j, ta in enumerate(t_acts):
            if j in used_t:
                continue
            s = _equiv_score(oa.act_type, ta.act_type)
            # Pass 1では完全一致（s >= 0.95）のみ
            if s >= 0.95 and s > best_score:
                best_score = s
                best_j = j
        if best_j is not None:
            ta = t_acts[best_j]
            used_o.add(i)
            used_t.add(best_j)
            preserved.append((oa, ta, best_score))
    
    # Pass 2: 残りを類似型でマッチ（閾値を下げて）
    for i, oa in enumerate(o_acts):
        if i in used_o:
            continue
        best_j = None
        best_score = 0.0
        for j, ta in enumerate(t_acts):
            if j in used_t:
                continue
            s = _equiv_score(oa.act_type, ta.act_type)
            if s > best_score:
                best_score = s
                best_j = j
        if best_j is not None and best_score > 0.0:
            ta = t_acts[best_j]
            used_o.add(i)
            used_t.add(best_j)
            preserved.append((oa, ta, best_score))
    
    # lost: マッチしなかったoriginal acts
    lost: List[Act] = [oa for i, oa in enumerate(o_acts) if i not in used_o]
    # added: マッチしなかったtranslated acts
    added = [ta for j, ta in enumerate(t_acts) if j not in used_t]

    # ========================================
    # IAP-Set: 行為タイプ保存率
    # ========================================
    iap_set = (len(preserved) / len(o_acts)) if o_acts else 1.0

    # ========================================
    # IAP-Force: 力学保存率（重み付き）
    # ========================================
    if o_acts:
        total_orig_weight = sum(_get_force_weight(a.act_type) * a.intensity for a in o_acts)
        preserved_weight = 0.0
        for oa, ta, type_match in preserved:
            orig_weight = _get_force_weight(oa.act_type) * oa.intensity
            trans_weight = _get_force_weight(ta.act_type) * ta.intensity
            # 重みの一致度（差が小さいほど高い）
            weight_match = 1.0 - abs(orig_weight - trans_weight) / max(orig_weight, trans_weight, 0.01)
            preserved_weight += orig_weight * type_match * _clip01(weight_match)
        iap_force = (preserved_weight / total_orig_weight) if total_orig_weight > 0 else 1.0
    else:
        iap_force = 1.0

    # ========================================
    # IAP-Target: Target一致率（重み付き: critical act types に重み、act別互換性考慮）
    # ========================================
    if preserved:
        target_weighted_sum = 0.0
        target_weight_total = 0.0
        for oa, ta, _ in preserved:
            # act別互換性を考慮してtarget一致度を計算
            score = _target_match_score(oa.target_role, oa.target_entity, ta.target_role, ta.target_entity, oa.act_type)
            # critical act types には重みを付ける
            weight = TARGET_WEIGHTED_ACT_TYPES.get(oa.act_type, TARGET_WEIGHT_DEFAULT)
            target_weighted_sum += score * weight
            target_weight_total += weight
        iap_target = target_weighted_sum / target_weight_total if target_weight_total > 0 else 0.0
    else:
        iap_target = 0.0

    # ========================================
    # Critical Act Loss Penalty: critical act types が欠落したらペナルティ
    # ========================================
    critical_loss_penalty = 0.0
    critical_lost_acts = []
    for lost_act in lost:
        if lost_act.act_type in CRITICAL_ACT_TYPES:
            critical_lost_acts.append(lost_act)
            critical_loss_penalty += CRITICAL_LOSS_PENALTY
    # 飽和
    critical_loss_penalty = min(critical_loss_penalty, CRITICAL_LOSS_PENALTY_CAP)

    # ========================================
    # intensity match: average over matched pairs
    # ========================================
    if preserved:
        intensity_diffs = [abs(oa.intensity - ta.intensity) for oa, ta, _ in preserved]
        intensity_match = 1.0 - (sum(intensity_diffs) / len(intensity_diffs))
    else:
        intensity_match = 0.0

    # ========================================
    # critical loss: primary act preserved AND any high-intensity act preserved
    # ========================================
    primary_preserved = any(
        _equiv_score(original.primary_act, oa.act_type) > 0.0 and _equiv_score(original.primary_act, ta.act_type) > 0.0
        for oa, ta, _ in preserved
    ) or (_equiv_score(original.primary_act, translated.primary_act) > 0.0)

    high_intensity_acts = [a for a in o_acts if a.intensity >= CRITICAL_INTENSITY]
    high_preserved = True
    for ha in high_intensity_acts:
        if not any(_equiv_score(ha.act_type, oa.act_type) > 0.0 for oa, _, _ in preserved if oa is ha):
            # fallback: any preserved with same type class
            if not any(_equiv_score(ha.act_type, oa.act_type) > 0.0 for oa, _, _ in preserved):
                high_preserved = False
                break

    no_critical_loss = bool(primary_preserved and high_preserved and len(critical_lost_acts) == 0)

    # ========================================
    # address_mode: 発話モードの一致チェック
    # ========================================
    address_mode_original = original.address_mode
    address_mode_translated = translated.address_mode
    address_mode_match = (address_mode_original == address_mode_translated)
    
    # address_modeが不一致の場合のペナルティ
    # direct → reported は重大な変化（告白が叙述に）
    ADDRESS_MODE_PENALTY_MAP = {
        ("direct", "reported"): 0.35,    # 告白→叙述は重大
        ("direct", "monologue"): 0.20,   # 告白→独白
        ("reported", "direct"): 0.10,    # 叙述→告白（むしろ改善の可能性）
        ("reported", "monologue"): 0.10,
        ("monologue", "direct"): 0.10,
        ("monologue", "reported"): 0.15,
    }
    address_mode_penalty = ADDRESS_MODE_PENALTY_MAP.get(
        (address_mode_original, address_mode_translated), 0.0
    )

    # ========================================
    # overall: 加重平均 × ゲート - ペナルティ
    # ========================================
    # base = 0.4*iap_set + 0.35*iap_force + 0.25*iap_target
    base = 0.4 * iap_set + 0.35 * iap_force + 0.25 * iap_target
    # gate = min(...)^γ
    gate = min(iap_set, iap_force, iap_target) ** GATE_GAMMA
    # critical act欠落ペナルティ + address_modeペナルティを適用
    overall = _clip01(base * gate - critical_loss_penalty - address_mode_penalty)

    return IAPResult(
        overall=overall,
        iap_set=_clip01(iap_set),
        iap_force=_clip01(iap_force),
        iap_target=_clip01(iap_target),
        preservation_rate=_clip01(iap_set),  # 後方互換
        intensity_match=_clip01(intensity_match),
        no_critical_loss=no_critical_loss,
        critical_loss_penalty=critical_loss_penalty,
        preserved=preserved,
        lost=lost,
        added=added,
        address_mode_original=address_mode_original,
        address_mode_translated=address_mode_translated,
        address_mode_match=address_mode_match,
        address_mode_penalty=address_mode_penalty,
    )


# ----------------------------
# 表示
# ----------------------------

def _fmt_act(a: Act) -> str:
    return f"{a.act_type} | {a.target_entity} [{a.target_role}] | intensity={a.intensity:.2f} | {a.force}"


def print_report(
    original_text: str,
    translated_text: str,
    original: ExtractedActs,
    translated: ExtractedActs,
    result: IAPResult,
) -> None:
    print("=" * 60)
    print("IAP (Illocutionary Act Preservation) Evaluation")
    print("=" * 60)
    print()

    print("【Original】")
    print("  Text:", original_text)
    print("  Primary Act:", original.primary_act)
    print("  Address Mode:", original.address_mode)
    print("  Overall Force:", original.overall_force)
    print()

    print("【Translated】")
    print("  Text:", translated_text)
    print("  Primary Act:", translated.primary_act)
    print("  Address Mode:", translated.address_mode)
    print("  Overall Force:", translated.overall_force)
    print()

    print("【IAP Score】")
    print(f"  ★ Overall: {result.overall:.2f}")
    print(f"  ├─ IAP-Set (Type Preservation): {result.iap_set:.2f}")
    print(f"  ├─ IAP-Force (Force Preservation): {result.iap_force:.2f}")
    print(f"  ├─ IAP-Target (Target Preservation, weighted): {result.iap_target:.2f}")
    print(f"  ├─ Intensity Match: {result.intensity_match:.2f}")
    print(f"  ├─ No Critical Loss: {result.no_critical_loss}")
    # address_mode
    if result.address_mode_match:
        print(f"  ├─ Address Mode: {result.address_mode_original} → {result.address_mode_translated} ✓")
    else:
        print(f"  ├─ Address Mode: {result.address_mode_original} → {result.address_mode_translated} ⚠️ MISMATCH")
        print(f"  │    └─ Penalty: -{result.address_mode_penalty:.2f}")
    if result.critical_loss_penalty > 0:
        print(f"  └─ ⚠️ Critical Act Penalty: -{result.critical_loss_penalty:.2f}")
    print()

    print(f"【Preserved Acts】({len(result.preserved)})")
    for oa, ta, s in result.preserved:
        # act別互換性を考慮（with_info=Trueで互換情報も取得）
        role_match, role_info = _target_role_distance(oa.target_role, ta.target_role, oa.act_type, with_info=True)
        entity_match = _entity_match_score(oa.target_entity, ta.target_entity)
        target_match = 0.6 * role_match + 0.4 * entity_match
        
        # critical actには重みを表示
        target_weight = TARGET_WEIGHTED_ACT_TYPES.get(oa.act_type, TARGET_WEIGHT_DEFAULT)
        weight_info = f" [weight={target_weight:.1f}]" if target_weight > 1.0 else ""
        print(f"  ✓ {_fmt_act(oa)}{weight_info}")
        print(f"    → {_fmt_act(ta)}")
        
        # 互換情報を表示
        if role_info == "exact match":
            role_detail = f"role={role_match:.2f}"
        elif role_info.startswith("compatible"):
            # 互換で救済された場合は強調
            role_detail = f"role={role_match:.2f} ✨{oa.target_role}~{ta.target_role} ({role_info})"
        else:
            role_detail = f"role={role_match:.2f}"
        
        print(f"       (type={s:.2f}, target={target_match:.2f} [{role_detail}, entity={entity_match:.2f}])")
    print()

    if result.lost:
        print(f"【Lost Acts】({len(result.lost)})")
        for a in result.lost:
            weight = _get_force_weight(a.act_type)
            sev = "high" if a.intensity >= CRITICAL_INTENSITY else "moderate" if a.intensity >= 0.5 else "low"
            # critical actは強調
            critical_marker = " ⚠️ CRITICAL" if a.act_type in CRITICAL_ACT_TYPES else ""
            print(f"  ✗ {_fmt_act(a)} (severity: {sev}, weight: {weight:.1f}){critical_marker}")
        print()

    if result.added:
        print(f"【Added Acts】({len(result.added)})")
        for a in result.added:
            print(f"  + {_fmt_act(a)}")
        print()


# ----------------------------
# YAML 実行
# ----------------------------

def load_yaml(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(str(p))
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def run_one(
    *,
    client: OpenAI,
    cache: JsonlCache,
    original_text: str,
    translated_text: str,
    lang_original: Optional[str] = None,
    lang_translated: Optional[str] = None,
    context_original: Optional[str] = None,
    context_translated: Optional[str] = None,
    model: str = DEFAULT_MODEL,
) -> Tuple[ExtractedActs, ExtractedActs, IAPResult]:
    original = cached_extract(
        client,
        cache,
        original_text,
        lang_hint=lang_original,
        context_hint=context_original,
        model=model,
    )
    translated = cached_extract(
        client,
        cache,
        translated_text,
        lang_hint=lang_translated,
        context_hint=context_translated,
        model=model,
    )

    # primary act fallback
    if not translated.primary_act:
        translated.primary_act = _normalize_act_type(translated.primary_act) or _normalize_act_type(translated.primary_act)

    result = score_iap_deterministic(original, translated)
    return original, translated, result


def run_suite(config: Dict[str, Any], *, model: str) -> int:
    tests = config.get("tests")
    if not isinstance(tests, list) or not tests:
        raise ValueError("YAML must contain a non-empty 'tests' list")

    client = _build_client()
    cache = JsonlCache(config.get("cache", DEFAULT_CACHE_PATH))

    out_path = config.get("output")
    out_f = None
    if out_path:
        out_f = Path(out_path).open("w", encoding="utf-8")

    failures = 0
    for item in tests:
        tid = item.get("id") or "(no-id)"
        original_text = item.get("original")
        translated_text = item.get("translation") or item.get("translated")
        if not isinstance(original_text, str) or not isinstance(translated_text, str):
            print(f"[SKIP] {tid}: missing original/translation")
            failures += 1
            continue

        meta = item.get("meta") or {}
        lang_original = meta.get("lang_original")
        lang_translated = meta.get("lang_translation") or meta.get("lang_translated")
        context_original = meta.get("context_original")
        context_translated = meta.get("context_translation") or meta.get("context_translated")

        print(f"\n\n### {tid} ###")
        try:
            original, translated, result = run_one(
                client=client,
                cache=cache,
                original_text=original_text,
                translated_text=translated_text,
                lang_original=lang_original,
                lang_translated=lang_translated,
                context_original=context_original,
                context_translated=context_translated,
                model=model,
            )
            print_report(original_text, translated_text, original, translated, result)

            record = {
                "id": tid,
                "original": original_text,
                "translation": translated_text,
                "original_extracted": {
                    "primary_act": original.primary_act,
                    "overall_force": original.overall_force,
                    "acts": [a.__dict__ for a in original.acts],
                },
                "translation_extracted": {
                    "primary_act": translated.primary_act,
                    "overall_force": translated.overall_force,
                    "acts": [a.__dict__ for a in translated.acts],
                },
                "iap": {
                    "overall": result.overall,
                    "iap_set": result.iap_set,
                    "iap_force": result.iap_force,
                    "iap_target": result.iap_target,
                    "preservation_rate": result.preservation_rate,
                    "intensity_match": result.intensity_match,
                    "no_critical_loss": result.no_critical_loss,
                },
            }
            if out_f:
                out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            failures += 1
            print(f"[ERROR] {tid}: {e}")

    if out_f:
        out_f.close()

    return failures


# ----------------------------
# CLI
# ----------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="IAP Evaluator")
    p.add_argument("-o", "--original", help="Original text")
    p.add_argument("-t", "--translated", "--translation", dest="translated", help="Translated text")
    p.add_argument("--config", help="YAML config path for batch evaluation")
    p.add_argument("--model", default=DEFAULT_MODEL, help=f"OpenAI model (default: {DEFAULT_MODEL})")
    p.add_argument("--cache", default=DEFAULT_CACHE_PATH, help=f"jsonl cache path (default: {DEFAULT_CACHE_PATH})")
    p.add_argument("--lang-original", default=None, help="Language hint for original (e.g., ja)")
    p.add_argument("--lang-translated", default=None, help="Language hint for translation (e.g., en)")
    p.add_argument("--context-original", default=None, help="Optional context hint for original")
    p.add_argument("--context-translated", default=None, help="Optional context hint for translation")
    return p


def main() -> int:
    args = build_arg_parser().parse_args()

    if args.config:
        cfg = load_yaml(args.config)
        # allow CLI override
        cfg.setdefault("cache", args.cache)
        cfg.setdefault("model", args.model)
        return run_suite(cfg, model=args.model)

    if not args.original or not args.translated:
        print("ERROR: Provide --original and --translated, or use --config", file=sys.stderr)
        return 2

    client = _build_client()
    cache = JsonlCache(args.cache)

    original, translated, result = run_one(
        client=client,
        cache=cache,
        original_text=args.original,
        translated_text=args.translated,
        lang_original=args.lang_original,
        lang_translated=args.lang_translated,
        context_original=args.context_original,
        context_translated=args.context_translated,
        model=args.model,
    )

    print_report(args.original, args.translated, original, translated, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
