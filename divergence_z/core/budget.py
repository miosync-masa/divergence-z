"""実行前のトークン見積もり・コンテキスト適合チェック・費用見積もり。

厳密なトークン数はプロバイダのトークナイザ次第なので、ここは保守的な概算。
日本語・中国語などの CJK 文字は 1 文字 ≒ 1 トークン強、それ以外は 4 文字 ≒ 1 トークンとみなす。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .models import ModelSpec

_CJK = re.compile(r"[　-ヿ㐀-鿿豈-﫿＀-￯가-힯]")


def estimate_tokens(text: str) -> int:
    cjk = len(_CJK.findall(text))
    return int(cjk * 1.2 + (len(text) - cjk) / 4) + 1


@dataclass
class FitReport:
    input_tokens: int
    output_tokens: int
    context_window: Optional[int]
    fits: Optional[bool]          # None = モデルのコンテキスト長が不明
    cost_usd: Optional[float]     # None = 料金が不明
    message: str


def check_fit(spec: ModelSpec, prompt_text: str, output_tokens: int,
              margin: float = 0.9) -> FitReport:
    """入力 + 出力がコンテキストに収まるか（margin 分の余裕を見る）と概算費用"""
    tokens_in = estimate_tokens(prompt_text)
    cost = None
    if spec.price_in is not None and spec.price_out is not None:
        cost = (tokens_in * spec.price_in + output_tokens * spec.price_out) / 1_000_000

    if spec.context_window is None:
        fits, msg = None, (f"~{tokens_in:,} input tokens; context window of {spec.id} unknown "
                           f"(set it in models.yaml)")
    else:
        fits = tokens_in + output_tokens <= spec.context_window * margin
        msg = (f"~{tokens_in:,} input + {output_tokens:,} output tokens "
               f"/ {spec.context_window:,} context — {'OK' if fits else 'TOO LARGE'}")
    if cost is not None:
        msg += f" / est. ${cost:.2f}"
    return FitReport(tokens_in, output_tokens, spec.context_window, fits, cost, msg)
