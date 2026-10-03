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
