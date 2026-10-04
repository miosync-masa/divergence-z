#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Localizer v1.0
訳し上がった訳文（L0）を読み込み、プリセットで選んだ領域（宗教・性表現など）だけを調整する。

翻訳とローカライズは別工程:
  [translate] chapter_translator → translations/<lang>/       L0。原文に忠実な訳。ここには一切触らない
  [localize]  localizer          → translations/<lang>@<variant>/

LLM は本文を書き直さない。出すのは「修正リスト」（段落ID・置換前・置換後・領域）と
「診断」（本文に触れない指摘）だけ。適用はローカルで、置換前の文字列がその段落の L0 に
ちょうど1回出てくる場合だけ置換する。リストに無い変更は起こりえない。

処理（action）:
  keep        触らない
  annotate    L2 補完。訳注・補足を足す（L0 の語は消さない）
  substitute  L3 等価置換。読者の文化の等価物に置き換える（強度・機能は保つ）。表記（notation）は L1
  soften      緩和。表現の強度を下げる（出来事・関係性は変えない）。利用者が明示的に選んだときだけ
  flag        L4 診断。本文に触れず、摩擦しうる箇所を報告する

範囲（scope。省略時は 緩和 → modifier、差別語 → nominal、それ以外 → any）:
  modifier    修飾部（擬態語・副詞・程度表現）だけ。述語の中核を変えたいなら、それは出来事の変更 = L4
              日本語・韓国語では、置換範囲が文末に届いた修正を機械的に却下する（述語が文末に来るため）
  nominal     人や集団を属性で名指す語だけ。「狂ったように」のような慣用的な比喩は対象外

出力（translations/<lang>@<variant>/）:
    {章}.{lang}.md             クリーン版（納品物）
    {章}.{lang}.annotated.md   注記版（介入箇所に 〔〕 / ⟦⟧ の標識。作家のレビュー用）
    {章}.{lang}.segments.json  原文・L0・ローカライズ後の段落対応
    {章}.{lang}.ledger.json    介入台帳（修正ごとに applied / reverted / rejected）
    {章}.{lang}.diagnosis.md   L4 診断（本文に触れていない指摘）
    policy.yaml                このバリアントで使った設定

Usage:
    cd divergence_z
    python localizer.py --input translations/STARGAZER_en --lang en --preset pg15 --preset halal
    python localizer.py ... --revert stargazer_ep01:E003   # 1件戻す（LLM は呼ばない）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from divergence_z.core import (EFFORTS, LLM, Keys, LLMResult, Progress, dump_yaml, print_progress,
                               resolve_progress)
from divergence_z.persona_extractor_v2 import DEFAULT_MODEL, SUPPORTED_LANGUAGES

DEFAULT_EFFORT = "medium"
PRESET_DIR = Path(__file__).resolve().parent / "localize_presets"
NOTES_FILE = "translation_notes.yaml"
POLICY_FILE = "policy.yaml"

DOMAINS: Dict[str, Tuple[str, str]] = {
    # key: (表示名, 何が含まれるか — LLM への説明)
    "religion": ("宗教", "religious practices, figures, scripture, rituals, and blasphemy or profanity "
                         "involving the sacred"),
    "sexual": ("性表現", "sexual acts, nudity, erotic description, sexual innuendo"),
    "violence": ("暴力描写", "graphic violence, gore, torture, self-harm, cruelty"),
    "slurs": ("差別語・罵倒", "slurs, discriminatory terms, insults and swearing"),
    "food_taboo": ("食の禁忌", "pork, alcohol, and other foods or drinks restricted by religion or culture"),
    "politics": ("政治・歴史", "political or historical references, contested territory and events, "
                              "national symbols"),
    "commodity": ("商品・生活文化", "brand names, products, everyday objects and customs specific to the "
                                  "source culture"),
    "notation": ("表記", "units of measure, currency, date and time formats"),
}

ACTIONS: Dict[str, str] = {
    "keep": "触らない",
    "annotate": "補完（訳注を足す）",
    "substitute": "等価置換",
    "soften": "緩和（強度を下げる）",
    "flag": "診断のみ",
}

# どこまで触れてよいか。省略時は action / domain から決まる（緩和 → modifier、差別語 → nominal）
SCOPES: Dict[str, str] = {
    "modifier": "修飾部のみ（擬態語・副詞・程度表現）。述語の中核は触らない",
    "nominal": "人や集団を属性で名指す語のみ。慣用的な比喩は対象外",
    "any": "制限なし",
}

# 述語が文末に来る言語。ここでは「緩和の範囲が文末に届いた = 述語に手が入った」として機械的に却下できる
HEAD_FINAL_LANGS = {"ja", "ko"}
_SENTENCE_END = re.compile(r"^[」』）)\]\s]*(?:[。．.！？!?]|$)")

# 注記版の標識。訳文に既に出てくる記号は使わない（作者の括弧と区別できなくなる）
MARKERS = [("〔", "〕"), ("⟦", "⟧")]


# =============================================================================
# POLICY / PRESETS
# =============================================================================

@dataclass
class DomainRule:
    action: str = "keep"
    instruction: str = ""
    scope: str = ""             # 空なら default_scope()


def default_scope(domain: str, rule: DomainRule) -> str:
    if rule.scope:
        return rule.scope
    if domain == "slurs":
        return "nominal"
    return "modifier" if rule.action == "soften" else "any"


@dataclass
class Policy:
    name: str = ""
    presets: List[str] = field(default_factory=list)
    domains: Dict[str, DomainRule] = field(default_factory=dict)

    def active(self) -> Dict[str, DomainRule]:
        return {d: r for d, r in self.domains.items() if r.action != "keep"}

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "presets": self.presets,
                "domains": {d: {"action": r.action,
                                **({"scope": r.scope} if r.scope else {}),
                                **({"instruction": r.instruction} if r.instruction else {})}
                            for d, r in self.domains.items()}}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Policy":
        p = cls(name=str(data.get("name") or ""), presets=list(data.get("presets") or []))
        for d, raw in (data.get("domains") or {}).items():
            if d not in DOMAINS:
                raise ValueError(f"unknown domain: {d} (one of {list(DOMAINS)})")
            raw = raw if isinstance(raw, dict) else {"action": raw}
            action = str(raw.get("action") or "keep")
            if action not in ACTIONS:
                raise ValueError(f"unknown action for {d}: {action} (one of {list(ACTIONS)})")
            scope = str(raw.get("scope") or "")
            if scope and scope not in SCOPES:
                raise ValueError(f"unknown scope for {d}: {scope} (one of {list(SCOPES)})")
            p.domains[d] = DomainRule(action, str(raw.get("instruction") or ""), scope)
        return p


def list_presets(extra_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """同梱プリセット＋プロジェクトのプリセット（同じ id ならプロジェクト側が優先）"""
    found: Dict[str, Dict[str, Any]] = {}
    for directory, origin in ((PRESET_DIR, "builtin"), (extra_dir, "project")):
        if not directory or not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.yaml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            pid = str(data.get("id") or path.stem)
            Policy.from_dict(data)          # 壊れたプリセットはここで落とす
            found[pid] = {**data, "id": pid, "origin": origin}
    return sorted(found.values(), key=lambda p: (p.get("order", 99), p["id"]))


def build_policy(preset_ids: List[str], overrides: Optional[Dict[str, Any]] = None,
                 extra_dir: Optional[Path] = None, name: str = "") -> Policy:
    """プリセットを順に重ね（後のものが優先）、最後に領域ごとの手動調整を重ねる"""
    presets = {p["id"]: p for p in list_presets(extra_dir)}
    unknown = [p for p in preset_ids if p not in presets]
    if unknown:
        raise ValueError(f"unknown preset(s): {unknown} (available: {sorted(presets)})")
    policy = Policy(presets=list(preset_ids))
    for pid in preset_ids:
        policy.domains.update(Policy.from_dict(presets[pid]).domains)
    if overrides:
        policy.domains.update(Policy.from_dict({"domains": overrides}).domains)
    policy.name = variant_name(name or "+".join(preset_ids) or "custom")
    return policy


def variant_name(name: str) -> str:
    """フォルダ名に使える形に（translations/<lang>@<variant>/）"""
    cleaned = re.sub(r"[^\w+\-]", "_", name.strip()).strip("_")
    return cleaned or "custom"


def variant_dir(translations_root: Path, lang: str, variant: str) -> Path:
    return translations_root / f"{lang}@{variant_name(variant)}"


# =============================================================================
# PROMPT
# =============================================================================

def build_system_prompt(policy: Policy, target_lang: str) -> str:
    lang = SUPPORTED_LANGUAGES.get(target_lang, target_lang)
    rules = []
    for d, r in policy.active().items():
        label, scope = DOMAINS[d]
        line = f"- {d} ({scope}): action = {r.action}, scope = {default_scope(d, r)}"
        if r.instruction:
            line += f"\n  instruction: {r.instruction}"
        rules.append(line)
    return f"""You localize an existing {lang} translation of a work of fiction for a specific readership.
The translation (TARGET) is finished and faithful to the SOURCE. You do NOT rewrite it. You output a
short list of precise EDITS, and DIAGNOSES for things you must not change.

## DOMAINS AND ACTIONS FOR THIS RUN (domains not listed must not be touched at all)
{chr(10).join(rules)}

## WHAT EACH ACTION ALLOWS
- annotate: ADD a brief gloss or explanatory phrase next to the term. The original wording stays;
  "after" must contain "before" unchanged.
- substitute: replace a culture-specific item with what does the same job for {lang} readers.
  Preserve INTENSITY and FUNCTION: an insult stays as harsh, a luxury stays a luxury, a joke stays a joke.
  For notation (units, currency, dates) convert the form only; the value must stay equivalent.
- soften: lower the intensity of the expression (explicitness, gore, vulgarity) as the instruction says.
  Never change what happens, who does it, or the relationship between characters. If softening would
  change an event or a relationship, do not edit — write a DIAGNOSIS instead.
- flag: never edit. Write a DIAGNOSIS for passages that may conflict with the readership.

## WHAT EACH SCOPE ALLOWS (applies to edits AND diagnoses)
- modifier: touch ONLY modifiers — onomatopoeia/mimetic words, adverbs, degree and intensity phrases.
  The core predicate (the main verb and what it does to whom) stays exactly as in TARGET, and so does
  the narrator's vocabulary: never swap a character's own words for clinical, formal, or neutral ones.
  Example: "ate them, crunching them to bits" → "ate them" is fine; "took them as medication" is NOT
  (it replaces the verb and the narrator's way of seeing). If the intensity lives in the predicate
  itself, do not edit — write a DIAGNOSIS.
- nominal: only words that name or label a person or group by an attribute (nouns, epithets, forms
  of address). Idiomatic similes and manner expressions ("worked like crazy", "fought like a madman")
  name no one and are out of scope.
- any: no restriction beyond the action.
Everyday hyperbole and set phrases (e.g. "it hurts so much I could die", Korean 아파 죽겠다) are speech
habits, not depictions of violence: leave them. Check the SOURCE when unsure.
Glossary targets in TRANSLATION NOTES are the translator's deliberate choices: soften must never remove
or replace them (diagnose instead). substitute may replace them — that is what localization is for.

## HARD RULES
1. Each edit replaces one short span inside ONE segment's TARGET. "before" must be copied EXACTLY from
   that TARGET (same characters, punctuation, spacing) and must occur exactly ONCE in it — include a few
   neighbouring words if needed to make it unique. Keep spans as short as possible.
2. Never edit for style, accuracy, or taste. Only the domains and actions listed above.
3. Do not edit inside dialogue voice beyond what the action requires; keep each character's register.
4. If nothing needs changing, return empty lists. Fewer, well-justified edits are better.

## OUTPUT (only this JSON, nothing else)
{{"edits": [
  {{"seg": "P012", "domain": "<domain>", "action": "<action>",
   "before": "exact span from TARGET", "after": "replacement", "note": "short reason"}}
 ],
 "diagnoses": [
  {{"seg": "P040", "domain": "<domain>", "note": "what may conflict and why (no edit made)"}}
 ]}}"""


def build_user_prompt(chapter: str, segments: List[Dict[str, str]], notes_text: str) -> str:
    parts = []
    if notes_text.strip():
        parts.append("## TRANSLATION NOTES (decisions made by the translator — respect them)\n"
                     "```yaml\n" + notes_text.strip() + "\n```")
    body = "\n".join(f'<seg id="{s["id"]}">\n<source>{s["source"]}</source>\n'
                     f'<target>{s["target"]}</target>\n</seg>' for s in segments)
    parts.append(f"## CHAPTER: {chapter}\n{body}")
    parts.append("Return the JSON with edits and diagnoses for these segments.")
    return "\n\n".join(parts)


def chunk_segments(segments: List[Dict[str, str]], limit: int) -> List[List[Dict[str, str]]]:
    chunks, cur, size = [], [], 0
    for s in segments:
        n = len(s["source"]) + len(s["target"])
        if cur and size + n > limit:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(s)
        size += n
    if cur:
        chunks.append(cur)
    return chunks


def parse_response(text: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return [], [], "no JSON in response"
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        return [], [], f"invalid JSON: {e}"
    edits = [e for e in data.get("edits") or [] if isinstance(e, dict)]
    diags = [d for d in data.get("diagnoses") or [] if isinstance(d, dict)]
    return edits, diags, None


# =============================================================================
# VALIDATE / APPLY / RENDER (ローカル。LLM は呼ばない)
# =============================================================================

def level_of(domain: str, action: str) -> str:
    if action == "annotate":
        return "L2"
    if action == "substitute":
        return "L1" if domain == "notation" else "L3"
    if action == "soften":
        return "緩和"
    return "L4"


# 修飾部の終わりに来やすい字（連用・連体の語尾、助詞）。変化した範囲がここで終わっていれば
# 「修飾語だけを変え、後ろの述語はそのまま」とみなす
_MODIFIER_END_JA = set("でにとくなずのいがをはもへや、")   # 「て」は補助動詞（〜てしまう）の接続にもなるので含めない


def changed_span(before: str, after: str) -> Tuple[int, int]:
    """before のうち実際に変わった範囲 [a, b)。共通の頭と、修飾部の切れ目で終わる共通の尻尾を外す"""
    a = 0
    while a < min(len(before), len(after)) and before[a] == after[a]:
        a += 1
    b = len(before)
    k = 0
    while k < min(len(before), len(after)) - a and before[-1 - k] == after[-1 - k]:
        k += 1
    # 共通の尻尾は、外した後の変化範囲が修飾部の切れ目で終わるところまでだけ外す
    # （「食べてしまった → 服用してしまった」の「てしまった」は外さない = 述語の変更として扱う）
    for n in range(k, 0, -1):
        end = len(before) - n
        if end > a and before[end - 1] in _MODIFIER_END_JA:
            b = end
            break
    return a, b


def reaches_sentence_end(target: str, before: str, after: str = "") -> bool:
    """
    実際に変わった範囲が文末（句点・段落末）まで届いているか。述語が文末に来る言語では、
    届いていれば述語に手が入ったことになる。目印として述語を含めただけの修正は通す。
    """
    a, b = changed_span(before, after)
    changed = before[a:b]
    if re.search(r"[。．！？!?]\s*$", changed):
        return True
    rest = target[target.index(before) + b:]
    return bool(_SENTENCE_END.match(rest))


def glossary_terms(notes_text: str) -> List[str]:
    """訳語表の訳語（緩和で消したり置き換えたりしてはいけない、翻訳者の決定）"""
    try:
        data = yaml.safe_load(notes_text) or {}
    except yaml.YAMLError:
        return []
    terms = [str(g.get("target", "")).strip() for g in data.get("glossary") or [] if isinstance(g, dict)]
    return [t for t in terms if len(t) >= 2]


def validate_edits(raw: List[Dict[str, Any]], segments: List[Dict[str, str]],
                   policy: Policy, start: int = 1, lang: str = "",
                   protected: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    修正リストを検証して台帳の項目にする。不正なものも rejected として残す（理由つき）。
    applied の修正は、L0 上で位置が一意に決まり、互いに重ならない。
    protected（訳語表の訳語）は緩和の変更範囲に含められない。等価置換は訳語表の語も置き換えてよい
    """
    targets = {s["id"]: s["target"] for s in segments}
    taken: Dict[str, List[Tuple[int, int]]] = {}
    out = []
    for n, e in enumerate(raw, start):
        seg, domain, action = str(e.get("seg", "")), str(e.get("domain", "")), str(e.get("action", ""))
        before, after = str(e.get("before", "")), str(e.get("after", ""))
        entry = {"id": f"E{n:03d}", "seg": seg, "domain": domain, "action": action,
                 "level": level_of(domain, action), "before": before, "after": after,
                 "note": str(e.get("note", "")), "status": "applied"}
        rule = policy.domains.get(domain)
        reason = None
        if seg not in targets:
            reason = f"unknown segment {seg}"
        elif not rule or rule.action in ("keep", "flag"):
            reason = f"domain {domain} is not editable in this policy"
        elif action != rule.action:
            reason = f"action {action} not allowed for {domain} (policy: {rule.action})"
        elif not before or before == after:
            reason = "empty or no-op edit"
        elif targets[seg].count(before) != 1:
            reason = f"'before' occurs {targets[seg].count(before)} time(s) in the segment (must be 1)"
        elif action == "annotate" and before not in after:
            reason = "annotate must keep the original wording"
        elif (default_scope(domain, rule) == "modifier" and lang in HEAD_FINAL_LANGS
              and reaches_sentence_end(targets[seg], before, after)):
            reason = "scope modifier: the span reaches the end of the sentence (core predicate)"
        elif action == "soften" and any(
                t in before[slice(*changed_span(before, after))] for t in protected or []):
            term = next(t for t in protected or [] if t in before[slice(*changed_span(before, after))])
            reason = f"'{term}' is a glossary decision (translation_notes); soften must not change it"
        else:
            pos = targets[seg].index(before)
            span = (pos, pos + len(before))
            if any(a < span[1] and span[0] < b for a, b in taken.get(seg, [])):
                reason = "overlaps another edit"
            else:
                taken.setdefault(seg, []).append(span)
                entry["pos"] = pos
        if reason:
            entry["status"] = "rejected"
            entry["reason"] = reason
        out.append(entry)
    return out


def pick_marker(texts: List[str]) -> Tuple[str, str]:
    joined = "".join(texts)
    for o, c in MARKERS:
        if o not in joined and c not in joined:
            return o, c
    return MARKERS[-1]


def _tag(e: Dict[str, Any], marker: Tuple[str, str]) -> str:
    label = DOMAINS.get(e["domain"], (e["domain"],))[0]
    o, c = marker
    if e["action"] == "annotate":
        return f"{o}{e['level']}・{label}{c}"
    return f"{o}{e['level']}・{label}: {e['before']}{c}"


def apply_edits(target: str, edits: List[Dict[str, Any]],
                marker: Optional[Tuple[str, str]] = None) -> str:
    """applied の修正を L0 の段落に適用する（後ろから置換するので位置がずれない）。marker で注記版"""
    out = target
    for e in sorted((e for e in edits if e["status"] == "applied"), key=lambda e: -e["pos"]):
        repl = e["after"] + (_tag(e, marker) if marker else "")
        out = out[:e["pos"]] + repl + out[e["pos"] + len(e["before"]):]
    return out


def render_variant(out_dir: Path, stem: str, lang: str, ledger: Dict[str, Any]) -> None:
    """台帳からクリーン版・注記版・段落対応・診断を書き出す"""
    segments = ledger["segments"]
    marker = pick_marker([s["source"] + s["target"] for s in segments])
    by_seg: Dict[str, List[Dict[str, Any]]] = {}
    for e in ledger["edits"]:
        by_seg.setdefault(e["seg"], []).append(e)

    clean, annotated, aligned = [], [], []
    for s in segments:
        edits = by_seg.get(s["id"], [])
        c = apply_edits(s["target"], edits)
        clean.append(c)
        annotated.append(apply_edits(s["target"], edits, marker))
        aligned.append({"id": s["id"], "source": s["source"], "l0": s["target"], "target": c})

    (out_dir / f"{stem}.{lang}.md").write_text("\n\n".join(clean) + "\n", encoding="utf-8")
    (out_dir / f"{stem}.{lang}.annotated.md").write_text("\n\n".join(annotated) + "\n", encoding="utf-8")
    (out_dir / f"{stem}.{lang}.segments.json").write_text(
        json.dumps(aligned, ensure_ascii=False, indent=1), encoding="utf-8")

    lines = [f"# 診断: {stem} ({lang}@{ledger['policy']['name']})", "",
             "本文には触れていない指摘です（L4）。変えるかどうかは編集者・作家が判断してください。", ""]
    for d in ledger["diagnoses"]:
        lines.append(f"- **{d.get('seg', '?')}** [{DOMAINS.get(d.get('domain', ''), (d.get('domain', ''),))[0]}] "
                     f"{d.get('note', '')}")
    if not ledger["diagnoses"]:
        lines.append("（指摘なし）")
    rejected = [e for e in ledger["edits"] if e["status"] == "rejected"]
    if rejected:
        lines += ["", "## 適用しなかった修正案", ""]
        lines += [f"- {e['id']} {e['seg']} [{e['domain']}/{e['action']}] "
                  f"「{e['before']}」→「{e['after']}」 — {e.get('reason', '')}" for e in rejected]
    (out_dir / f"{stem}.{lang}.diagnosis.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def ledger_path(out_dir: Path, stem: str, lang: str) -> Path:
    return out_dir / f"{stem}.{lang}.ledger.json"


def load_ledger(out_dir: Path, stem: str, lang: str) -> Dict[str, Any]:
    return json.loads(ledger_path(out_dir, stem, lang).read_text(encoding="utf-8"))


def set_edit_status(out_dir: Path, stem: str, lang: str, edit_id: str, status: str) -> Dict[str, Any]:
    """1件の修正を applied / reverted に切り替えて再描画する（LLM は呼ばない）"""
    if status not in ("applied", "reverted"):
        raise ValueError("status must be applied or reverted")
    ledger = load_ledger(out_dir, stem, lang)
    for e in ledger["edits"]:
        if e["id"] == edit_id:
            if e["status"] == "rejected":
                raise ValueError(f"{edit_id} was rejected ({e.get('reason')}) and cannot be applied")
            e["status"] = status
            break
    else:
        raise KeyError(edit_id)
    ledger_path(out_dir, stem, lang).write_text(json.dumps(ledger, ensure_ascii=False, indent=1),
                                                encoding="utf-8")
    render_variant(out_dir, stem, lang, ledger)
    return ledger


# =============================================================================
# LIBRARY
# =============================================================================

def l0_chapters(l0_dir: Path, lang: str) -> List[str]:
    """訳し上がった章（{章}.{lang}.md がある = 完成した章）の stem"""
    suffix = f".{lang}.md"
    return sorted(p.name[:-len(suffix)] for p in l0_dir.glob(f"*{suffix}")
                  if (l0_dir / f"{p.name[:-len(suffix)]}.{lang}.segments.json").exists())


@dataclass
class LocalizeResult:
    chapter: str
    edits: int
    applied: int
    rejected: int
    diagnoses: int
    output_path: Path
    errors: List[str] = field(default_factory=list)
    llm: Optional[LLMResult] = None


def localize_chapter(l0_dir: Path, stem: str, lang: str, policy: Policy, *, llm: LLM,
                     out_dir: Path, model: str = DEFAULT_MODEL,
                     effort: Optional[str] = DEFAULT_EFFORT, max_chunk_chars: int = 12000,
                     max_output_tokens: int = 32000, cancel_check=None,
                     progress: Optional[Progress] = None) -> LocalizeResult:
    report = resolve_progress(progress)
    if not policy.active():
        raise ValueError("policy has no active domain (every domain is keep)")
    out_dir.mkdir(parents=True, exist_ok=True)
    segments = json.loads((l0_dir / f"{stem}.{lang}.segments.json").read_text(encoding="utf-8"))
    notes_path = l0_dir / NOTES_FILE
    notes_text = notes_path.read_text(encoding="utf-8") if notes_path.exists() else ""
    system = build_system_prompt(policy, lang)

    raw_edits: List[Dict[str, Any]] = []
    diagnoses: List[Dict[str, Any]] = []
    errors: List[str] = []
    last = None
    chunks = chunk_segments([s for s in segments if s.get("target")], max_chunk_chars)
    for k, chunk in enumerate(chunks, 1):
        if cancel_check:
            cancel_check()
        report(f"🧭 {stem} {chunk[0]['id']}–{chunk[-1]['id']} ({k}/{len(chunks)})")
        last = llm.complete(system, build_user_prompt(stem, chunk, notes_text), model=model,
                            effort=effort, max_output_tokens=max_output_tokens)
        edits, diags, err = parse_response(last.text)
        if err:
            errors.append(f"{chunk[0]['id']}–{chunk[-1]['id']}: {err}")
            report(f"   ⚠️  {err}")
        raw_edits += edits
        diagnoses += diags

    ledger = {"chapter": stem, "lang": lang, "policy": policy.to_dict(),
              "segments": [{"id": s["id"], "source": s["source"], "target": s["target"]} for s in segments],
              "edits": validate_edits(raw_edits, segments, policy, lang=lang,
                                      protected=glossary_terms(notes_text)), "diagnoses": diagnoses,
              "errors": errors}
    ledger_path(out_dir, stem, lang).write_text(json.dumps(ledger, ensure_ascii=False, indent=1),
                                                encoding="utf-8")
    (out_dir / POLICY_FILE).write_text(dump_yaml(policy.to_dict()), encoding="utf-8")
    render_variant(out_dir, stem, lang, ledger)
    applied = sum(e["status"] == "applied" for e in ledger["edits"])
    rejected = sum(e["status"] == "rejected" for e in ledger["edits"])
    report(f"   ✏️  {applied} applied · {rejected} rejected · 🩺 {len(diagnoses)} diagnosis")
    return LocalizeResult(stem, len(ledger["edits"]), applied, rejected, len(diagnoses),
                          out_dir / f"{stem}.{lang}.md", errors, last)


# =============================================================================
# CLI
# =============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(description="Localizer v1.0 — adjust a finished translation by preset")
    parser.add_argument("--input", "-i", default="", help="L0 translation folder (chapter_translator output)")
    parser.add_argument("--lang", "-t", default="", help="Language of the translation, e.g. en")
    parser.add_argument("--preset", "-p", action="append", default=[], help="Preset id (repeatable; later wins)")
    parser.add_argument("--set", action="append", default=[], metavar="DOMAIN=ACTION",
                        help="Override one domain, e.g. --set violence=keep")
    parser.add_argument("--name", default="", help="Variant name (default: preset ids joined by +)")
    parser.add_argument("--chapters", default="", help="Comma-separated chapter stems (default: all)")
    parser.add_argument("--out-dir", "-o", default="", help="Default: <input>/../<lang>@<variant>")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--model", "-m", default=DEFAULT_MODEL)
    parser.add_argument("--effort", "-r", default=DEFAULT_EFFORT, choices=EFFORTS)
    parser.add_argument("--list-presets", action="store_true")
    parser.add_argument("--revert", default="", metavar="CHAPTER:EDIT", help="Revert one edit and re-render")
    parser.add_argument("--reapply", default="", metavar="CHAPTER:EDIT", help="Re-apply a reverted edit")
    args = parser.parse_args()

    if args.list_presets:
        for p in list_presets():
            print(f"{p['id']:<20} {p.get('name', '')}")
        return 0
    if not args.input or not args.lang:
        parser.error("--input and --lang are required")

    overrides = {}
    for item in args.set:
        d, _, a = item.partition("=")
        overrides[d.strip()] = {"action": a.strip()}
    policy = build_policy(args.preset, overrides, name=args.name)
    l0_dir = Path(args.input)
    out_dir = Path(args.out_dir) if args.out_dir else variant_dir(l0_dir.parent, args.lang, policy.name)

    for flag, status in ((args.revert, "reverted"), (args.reapply, "applied")):
        if flag:
            stem, _, edit_id = flag.partition(":")
            set_edit_status(out_dir, stem, args.lang, edit_id, status)
            print(f"✅ {stem} {edit_id} → {status} ({out_dir})")
            return 0

    print(f"🧭 policy {policy.name}: " +
          ", ".join(f"{d}={r.action}" for d, r in policy.active().items()))
    llm = LLM(Keys.from_env(), progress=print_progress)
    wanted = [c.strip() for c in args.chapters.split(",") if c.strip()]
    for stem in wanted or l0_chapters(l0_dir, args.lang):
        if ledger_path(out_dir, stem, args.lang).exists() and not args.force:
            print(f"⏭  {stem}: already localized")
            continue
        r = localize_chapter(l0_dir, stem, args.lang, policy, llm=llm, out_dir=out_dir,
                             model=args.model, effort=args.effort, progress=print_progress)
        print(f"📁 {r.output_path}")
    print(f"usage: {llm.total_usage()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
