"""原作テキストの読み込み（txt / md / pdf / epub、フォルダは自然順で連結）。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, List, Optional, Tuple

from .progress import Progress, resolve

DEFAULT_EXTENSIONS = [".txt", ".text", ".md", ".pdf", ".epub"]

# 青空文庫など古いテキストは Shift_JIS が多い。latin-1 は最後の手段（必ず読める）
_ENCODINGS = ["utf-8", "cp932", "shift_jis", "euc-jp", "iso-2022-jp", "utf-16", "latin-1"]


def load_text_file(path: Path, progress: Optional[Progress] = None) -> str:
    for encoding in _ENCODINGS:
        try:
            text = path.read_text(encoding=encoding)
            resolve(progress)(f"   Encoding detected: {encoding}")
            return text
        except (UnicodeDecodeError, UnicodeError):
            continue
    return path.read_text(encoding="latin-1")


def load_pdf(path: Path) -> str:
    try:
        from PyPDF2 import PdfReader
    except ImportError:
        raise ImportError("PyPDF2 required: pip install PyPDF2")
    reader = PdfReader(str(path))
    return "\n".join(t for t in (page.extract_text() for page in reader.pages) if t)


def load_epub(path: Path) -> str:
    try:
        import ebooklib
        from bs4 import BeautifulSoup
        from ebooklib import epub
    except ImportError:
        raise ImportError("ebooklib and beautifulsoup4 required: pip install ebooklib beautifulsoup4")
    book = epub.read_epub(str(path))
    return "\n".join(
        BeautifulSoup(item.get_content(), "html.parser").get_text()
        for item in book.get_items()
        if item.get_type() == ebooklib.ITEM_DOCUMENT
    )


def load_source_file(source_path: str, progress: Optional[Progress] = None) -> str:
    path = Path(source_path)
    if not path.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return load_pdf(path)
    if suffix == ".epub":
        return load_epub(path)
    return load_text_file(path, progress)


def _natural_key(path: Path) -> List[Any]:
    """自然順ソート用キー（ep2 < ep10）"""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(path))]


def collect_source_files(source: str, extensions: List[str] = DEFAULT_EXTENSIONS,
                         recursive: bool = True) -> List[Path]:
    """source がファイルならそれ1つ、フォルダなら対象拡張子のファイルを自然順で返す"""
    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"Source not found: {source}")
    if path.is_file():
        return [path]

    exts = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in extensions}
    files = [
        p for p in path.glob("**/*" if recursive else "*")
        if p.is_file()
        and p.suffix.lower() in exts
        and not any(part.startswith(".") for part in p.relative_to(path).parts)
    ]
    return sorted(files, key=lambda p: _natural_key(p.relative_to(path)))


def load_source_corpus(source: str, extensions: List[str] = DEFAULT_EXTENSIONS,
                       recursive: bool = True,
                       progress: Optional[Progress] = None) -> Tuple[str, List[Tuple[str, int]]]:
    """
    ファイル or フォルダを読み込み、`=== FILE: 相対パス ===` 区切りで1本に連結する。
    Returns (corpus_text, [(相対パス, 文字数), ...])
    """
    report = resolve(progress)
    files = collect_source_files(source, extensions, recursive)
    if not files:
        raise FileNotFoundError(f"No source files ({', '.join(extensions)}) found in: {source}")

    base = Path(source) if Path(source).is_dir() else Path(source).parent
    parts: List[str] = []
    manifest: List[Tuple[str, int]] = []
    for f in files:
        rel = str(f.relative_to(base))
        report(f"   📄 {rel}")
        text = load_source_file(str(f), progress)
        if not text.strip():
            report("      (empty — skipped)")
            continue
        parts.append(f"=== FILE: {rel} ===\n{text.strip()}\n")
        manifest.append((rel, len(text)))
    return "\n".join(parts), manifest
