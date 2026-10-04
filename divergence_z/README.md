# divergence_z — ライブラリ / Library reference

使い方のマニュアルはリポジトリ直下の [README.md](../README.md) を参照。ここはコードから使う人向けの一覧。
For the user manual see the [top-level README](../README.md). This page lists the library API.

## 共通層 `core/`

```python
from divergence_z.core import LLM, Keys, load_source_corpus, get_model, check_fit

llm = LLM(Keys(openai="sk-...", anthropic="sk-ant-..."))   # BYOK（CLI は Keys.from_env()）
result = llm.complete(system, user, model="claude-opus-5-5", effort="high")
result.text, result.usage, llm.total_usage()
```

| モジュール | 中身 |
|---|---|
| `core/llm.py` | `LLM.complete()`（OpenAI Responses / Anthropic Messages を同じ形で）、`Keys`、`LLMResult`、`classify_error()` |
| `core/models.py` | モデル登録表 `get_model()` / `list_models()`。`~/.divergence_z/models.yaml`（または `$DZ_MODELS`）で上書き |
| `core/budget.py` | `estimate_tokens()`、`check_fit(spec, prompt, output_tokens)` → トークン数・収まるか・概算費用 |
| `core/loaders.py` | `load_source_corpus(path)`：ファイル / フォルダ（自然順）を `=== FILE: … ===` 区切りで連結。txt / md / pdf / epub |
| `core/yamlio.py` | LLM 出力からの YAML 取り出し・クォート修復、`iter_episodes()`、原文照合用の正規化 |
| `core/cancel.py` | `CancelToken`（`LLM(..., cancel=token)` で受信中・ポーリング中にも中止） |
| `core/progress.py` | 進行状況コールバック（ライブラリは print せず `progress(msg)` を呼ぶ） |

## 機能ごとの関数

すべて `llm=` を受け取り、結果を dataclass で返す。ファイル保存は呼ぶ側の責任（翻訳だけは出力フォルダを管理する）。

| モジュール | 関数 | 返り値 |
|---|---|---|
| `cast_extractor` | `extract_cast(corpus, llm=, work=, hint=)` | `CastResult(yaml_text, data, error)` |
| `persona_extractor_v2` | `extract_persona(corpus, character, llm=, cast_text=, output_lang=)` | `PersonaResult(yaml_text, valid, issues)` |
| `episode_extractor` | `extract_episodes(corpus, character, llm=, work=, cast_text=, persona_text=)` | `EpisodeExtraction(yaml_text, valid, quotes_total, quotes_missing, …)` |
| `persona_generator` | `generate_persona(name, source, desc, llm=, web_search=True)` | `PersonaGeneration(yaml_text, valid, research, …)` |
| `episode_generator` | `generate_episodes(name, source, desc, llm=, web_search=True)` | `EpisodeResult(yaml_text, valid, episode_count, …)` |
| `chapter_translator` | `open_book(source, cast_path)` → `translate_chapter(book, idx, llm=, out_dir=, target_lang=)` | `ChapterResult(translated, issues, complete, output_path, …)` |
| `chapter_translator` | `estimate_chapter(book, idx, out_dir, model)` | `FitReport`（API を呼ばない） |
| `localizer` | `build_policy(presets, overrides)` → `localize_chapter(l0_dir, stem, lang, policy, llm=, out_dir=)` | `LocalizeResult(applied, rejected, diagnoses, output_path, …)`。L0 は変えず `translations/<lang>@<variant>/` に出力 |
| `localizer` | `set_edit_status(out_dir, stem, lang, edit_id, "reverted")` | 台帳（1件戻して再描画。API を呼ばない） |
| `persona_voice` | `transform_voice(llm=, persona_data=, input_text=, context=, …)` / `respond_voice(…)` | dict（`output`, `usage`, …） |

どの関数にも `model=` / `effort=` / `progress=` を渡せる。各スクリプトは同名の CLI でもある（`python cast_extractor.py --help`）。

## サイドカー API `server/`

デスクトップアプリ用のローカル API（FastAPI）。仕様は [server/README.md](server/README.md)。

```bash
python -m divergence_z.server     # → {"event":"ready","port":…,"token":…}
```

## 旧系統 `old/`

行単位の Z軸翻訳と IAP / ZAP 評価（アーカイブ）。[old/README.md](old/README.md)。
