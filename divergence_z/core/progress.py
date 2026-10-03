"""進行状況の通知。

ライブラリ関数は print せず `progress(msg)` を呼ぶ。
CLI は print_progress を、UI（Electron サイドカー等）は独自のコールバックを渡す。
"""

from __future__ import annotations

from typing import Callable, Optional

Progress = Callable[[str], None]


def print_progress(msg: str) -> None:
    print(msg, flush=True)


def silent(msg: str) -> None:
    pass


def resolve(progress: Optional[Progress]) -> Progress:
    return progress or silent
