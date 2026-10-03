"""Divergence-Z core: LLM provider layer (BYOK), model registry, loaders, YAML helpers.

ライブラリ関数（build / translate / voice）はすべてこの層を通して LLM を呼ぶ。
CLI と UI（Electron サイドカー）は同じ関数を呼び、違いは progress コールバックとキーの渡し方だけ。
"""

from .budget import FitReport, check_fit, estimate_tokens
from .cancel import CancelToken, Cancelled
from .llm import LLM, Keys, LLMError, LLMRefusal, LLMResult, classify_error
from .loaders import (DEFAULT_EXTENSIONS, collect_source_files, load_source_corpus,
                      load_source_file)
from .models import EFFORTS, ModelSpec, get_model, list_models, registry
from .progress import Progress, print_progress, silent
from .progress import resolve as resolve_progress
from .yamlio import (appears_in, clean_yaml_output, dump_yaml, extract_yaml, fix_yaml_quoting,
                     iter_episodes, normalize_for_match)

__all__ = [
    "FitReport", "check_fit", "estimate_tokens",
    "CancelToken", "Cancelled",
    "LLM", "Keys", "LLMError", "LLMRefusal", "LLMResult", "classify_error",
    "DEFAULT_EXTENSIONS", "collect_source_files", "load_source_corpus", "load_source_file",
    "EFFORTS", "ModelSpec", "get_model", "list_models", "registry",
    "Progress", "print_progress", "resolve_progress", "silent",
    "appears_in", "clean_yaml_output", "dump_yaml", "extract_yaml", "fix_yaml_quoting",
    "iter_episodes", "normalize_for_match",
]
