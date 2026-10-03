"""LLM 出力からの YAML 取り出し・クォート修復・原文照合用の正規化。"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Optional

import yaml

from .progress import Progress, resolve

# persona / episode / cast それぞれの YAML 本体の先頭になりうるキー
DEFAULT_START_KEYS = ("persona:", "identity_core:", "timelines:", "episodes:",
                      "work:", "narration:", "characters:")


def extract_yaml(raw: str, start_keys: Iterable[str] = DEFAULT_START_KEYS,
                 progress: Optional[Progress] = None) -> str:
    """
    モデル出力から YAML 部分を取り出す。
    1. ```yaml ... ```  2. ``` ... ```（meta: を含むもの）  3. `# ===` / `meta:` 行から
    4. 既知の先頭キーから（数行上に meta: があればそこから）  5. そのまま返す
    """
    if "```yaml" in raw:
        part = raw.split("```yaml", 1)[1]
        return part.split("```", 1)[0].strip() if "```" in part else part.strip()

    if "```" in raw:
        for part in raw.split("```")[1::2]:
            stripped = part.strip()
            if stripped.startswith("# ===") or "meta:" in stripped[:200]:
                return stripped

    lines = raw.split("\n")
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("# ===") or s.startswith("meta:"):
            return "\n".join(lines[i:])

    keys = tuple(start_keys)
    for i, line in enumerate(lines):
        if line.strip().startswith(keys):
            for j in range(max(0, i - 5), i):
                if lines[j].strip().startswith("meta:"):
                    return "\n".join(lines[j:])
            return "\n".join(lines[i:])

    resolve(progress)("   ⚠️  Could not reliably extract YAML from model output")
    return raw


def fix_yaml_quoting(yaml_content: str, progress: Optional[Progress] = None) -> str:
    """
    LLM がよく壊す `key: "From zero"を維持` 型のクォートを単一引用符で包み直す。
    元から valid なら何もしない。直しきれなければ部分修正版を返す。
    """
    report = resolve(progress)
    try:
        yaml.safe_load(yaml_content)
        return yaml_content
    except yaml.YAMLError:
        report("   🔧 YAML parse error detected, attempting auto-repair...")

    broken_pattern = re.compile(r'^(\s+\w[\w_]*:\s+)"([^"]*)"(.+)$')
    mid_quote_pattern = re.compile(r'^(\s+\w[\w_]*:\s+)([^"]*"[^"]*"[^"]*)$')

    fixed_lines = []
    fix_count = 0
    for line in yaml_content.split("\n"):
        m = broken_pattern.match(line)
        if m:
            value = f'"{m.group(2)}"{m.group(3)}'.replace("'", "''")
            fixed_lines.append(f"{m.group(1)}'{value}'")
            fix_count += 1
            continue
        m2 = mid_quote_pattern.match(line)
        if m2:
            try:
                yaml.safe_load(f"test: {m2.group(2)}")
                fixed_lines.append(line)
            except yaml.YAMLError:
                fixed_lines.append(f"{m2.group(1)}'{m2.group(2).replace(chr(39), chr(39) * 2)}'")
                fix_count += 1
            continue
        fixed_lines.append(line)

    if fix_count == 0:
        report("   ⚠️  No fixable quoting patterns found (error may be elsewhere)")
        return yaml_content

    fixed = "\n".join(fixed_lines)
    try:
        yaml.safe_load(fixed)
        report(f"   ✅ Auto-repaired {fix_count} broken YAML quote(s)")
    except yaml.YAMLError as e:
        report(f"   ⚠️  Auto-repair fixed {fix_count} lines but YAML still invalid: {str(e)[:200]}")
    return fixed


def clean_yaml_output(raw: str, start_keys: Iterable[str] = DEFAULT_START_KEYS,
                      progress: Optional[Progress] = None) -> str:
    """extract_yaml → fix_yaml_quoting をまとめて行う"""
    return fix_yaml_quoting(extract_yaml(raw, start_keys, progress), progress).strip()


def dump_yaml(data) -> str:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=1000)


def iter_episodes(data) -> list:
    """Episode Memory YAML の全エピソード（timelines[].episodes 形式と旧トップレベル episodes 形式の両方）"""
    if not isinstance(data, dict):
        return []
    episodes = []
    for tl in data.get("timelines") or []:
        if isinstance(tl, dict):
            episodes.extend(e for e in (tl.get("episodes") or []) if isinstance(e, dict))
    episodes.extend(e for e in (data.get("episodes") or []) if isinstance(e, dict))
    return episodes


# 原文照合用 -------------------------------------------------------------------

QUOTE_STRIP = "「」『』“”\"'‘’（）()"


def normalize_for_match(text: str) -> str:
    """NFKC + 空白除去（全角/半角・改行の差を無視して照合する）"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def appears_in(quote: str, normalized_corpus: str) -> bool:
    needle = normalize_for_match(quote).strip(QUOTE_STRIP)
    return not needle or needle in normalized_corpus
