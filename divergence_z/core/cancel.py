"""ジョブの中止。

UI から中止されたら CancelToken.cancel() を呼ぶ。ライブラリ側は区切り（キャラクター1人・章1つ）
ごとに check() し、LLM 層はストリーム受信中 / background ポーリング中にも確認して即座に止める。
"""

from __future__ import annotations

import threading
from typing import Optional


class Cancelled(Exception):
    pass


class CancelToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        if self._event.is_set():
            raise Cancelled()


def check(token: Optional[CancelToken]) -> None:
    if token is not None:
        token.check()
