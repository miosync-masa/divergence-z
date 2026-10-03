# old/ — 旧 Z軸翻訳系（アーカイブ）

初期設計の「行ごとに Z軸状態（z / z_mode / z_leak）を推定 → 翻訳 → 保存度を指標で採点」系統。
保存度の指標（ZAP / IAP）がヒューリスティックで判定不能なため、
現行は「キャラクター構築系の出力（cast / persona / episode）＋これまでの訳文を LLM に渡して章単位で一括翻訳」
（`chapter_translator.py`）に移行した。

`Result/` 配下の既存実験結果を再現できるよう、コードは削除せずここに残す。

| ファイル | 役割 |
|---|---|
| `z_axis_translate.py` | 1行単位の Z軸翻訳（Step1/2/3） |
| `z_axis_dialogue.py` | 対話シーン翻訳 |
| `zap_evaluator.py` | ZAP（Z-Axis Preservation）評価 |
| `iap_evaluator.py` | IAP（発語内行為保存）評価 |
| `yaml_generator.py` | `z_axis_translate` 用リクエスト YAML 生成 |
| `yaml_formatter.py` | 台本 → `z_axis_dialogue` 用 YAML 変換 |
| `persona_extractor.py` | persona 抽出 v1.2（`persona_extractor_v2.py` に置換済み） |
| `requests/` | 上記の入力 YAML |

実行は `divergence_z/` から（`personas/` `episodes/` を相対パスで参照するため）:

```bash
cd divergence_z
python old/z_axis_translate.py --config old/requests/rem_test_a_suki.yaml
```

旧系統のスクリプトは当時の環境変数を読む（現行の `.env.example` には載っていない）:

| 変数 | 用途 |
|---|---|
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | API キー |
| `OPENAI_MODEL` | Step1/2 などで使う OpenAI モデル（当時の既定 `gpt-5.2`） |
| `CLAUDE_MODEL` | Step3 で使う Claude モデル（当時の既定 `claude-opus-4-5-20251101`） |
| `USE_CLAUDE_FOR_STEP3` | Step3 を Claude で行うか（既定 `true`） |
| `IAP_MODEL` | IAP 評価のモデル（既定 `gpt-4.1-mini`） |

## 論文との対応

実践報告 *Translation as Action Preservation (TAP): Evaluating Anime/Manga Translation Beyond Meaning*
（Journal of Audiovisual Translation 投稿）の実験は、この旧系統で行った。結果はリポジトリ直下の `Result/` にある。

| `Result/` | 内容 |
|---|---|
| `ReZERO/` | レムとスバル（z_axis_dialogue / v3.3 ペルソナ） |
| `STEINSGATE/` | 紅莉栖・まゆり・岡部（翻訳・ZAP 評価・persona_voice のデュアルボイス） |
| `ONEPIEC/` | ルフィとレイリー（多言語の対話翻訳） |
| `Shakespeare/` | persona_voice（ロミオとジュリエット） |
