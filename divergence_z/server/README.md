# Divergence-Z sidecar API

デスクトップアプリ（Electron / Tauri）から子プロセスとして起動する、ローカル専用の API。
ライブラリ関数（cast / persona / episode / translate / voice）をジョブとして実行する。

## 起動

```bash
pip install -e ".[server]"
python -m divergence_z.server            # または dz-server
```

stdout に1行だけ JSON が出る。アプリはこれを読んで接続先とトークンを知る:

```json
{"event": "ready", "host": "127.0.0.1", "port": 53817, "token": "…"}
```

| オプション | 説明 |
|---|---|
| `--port 0` | 空きポートを自動選択（既定） |
| `--allow-origin app://-` | CORS を許可するオリジン（繰り返し可）。開発サーバーなら `http://localhost:5173` |
| `--workers 2` | 同時実行ジョブ数 |
| `DZ_HOME` | プロジェクト一覧の保存先（既定 `~/.divergence_z`） |

親プロセスが終了するとサイドカーも自動終了する。

## セキュリティ

- 127.0.0.1 のみで待ち受け、`Host` が loopback 以外のリクエストは 403（DNS rebinding 対策）
- `/health` 以外は `Authorization: Bearer <token>` 必須（EventSource 用に `?token=` も可）
- API キーは `PUT /session/keys` でメモリにだけ保持。ディスク・ログ・ジョブ記録には書かない。
  永続化はアプリ側で OS のキーチェーン（Electron `safeStorage`）に

## エンドポイント

| | パス | |
|---|---|---|
| GET | `/health` | 生存確認（認証不要） |
| GET / PUT | `/session/keys` | `{openai?, anthropic?, openai_base_url?}`。`""` でクリア |
| GET | `/models` | モデル登録表（context_window / max_output / efforts / price） |
| GET / POST | `/projects` | 一覧 / フォルダを開く・作る `{root, name?, work?, source?, output_lang?, review_cast?, models?}` |
| GET / PATCH / DELETE | `/projects/{id}` | 状態（人物表・persona・episode の有無）/ 設定変更 / 一覧から外す（フォルダは消さない） |
| GET / PUT | `/projects/{id}/cast` | 人物表 `{yaml}` |
| GET | `/projects/{id}/personas`, `/episodes` | ファイル一覧 |
| GET / PUT | `/projects/{id}/personas/{label}`, `/episodes/{label}` | 人物ごとの YAML |
| GET | `/projects/{id}/translations/{lang}` | 章ごとの状態（done / incomplete / pending） |
| GET | `/projects/{id}/translations/{lang}/{chapter}` | 原文と訳文の段落対応 |
| GET / PUT | `/projects/{id}/translations/{lang}/notes` | 訳語表 |
| POST | `/projects/{id}/estimate` | `{steps, characters?, langs, chapters}` → ステップごとのトークン・適合・概算費用 |
| POST | `/jobs` | `{type, project_id, params}` → 202 + ジョブ |
| GET | `/jobs?project_id=` / `/jobs/{id}` | 一覧 / スナップショット |
| GET | `/jobs/{id}/events` | SSE（`Last-Event-ID` / `?last_event_id=` で再開） |
| POST | `/jobs/{id}/cancel` / `/resume` | 中止 / 人物表確認待ちから再開 |

## ジョブ

| type | params |
|---|---|
| `cast` | `hint?` |
| `persona` / `episode` | `characters?`（省略時は人物表の main）、`force?`、`max_episodes?` |
| `translate` | `lang`, `chapters?`（`"0-2,5"`）、`previous?`、`force?` |
| `voice` | `persona`, `input`, `context?`, `target?`, `dual?`, `output_lang?`, `show_thinking?` |
| `generate_persona` / `generate_episodes` | `name`, `source`, `desc?`, `lang?`, `web_search?` |
| `pipeline` | `characters?`, `translate_langs?`, `review_cast?`, `force_cast?` |

どのジョブも `params.models = {step: {model, effort}}` でプロジェクト設定を一時的に上書きできる。
作成済みの人物表・persona・episode・訳済みの章はスキップする（`force` で作り直し）ので、
失敗や中止のあとは同じジョブを投げ直せば続きから再開する。

状態: `queued → running → succeeded | failed | cancelled`（pipeline は途中で `awaiting_review`）

SSE イベント:

```
event: status    data: {"status":"awaiting_review","reason":"cast_ready","cast_file":"casts/cast.yaml"}
event: progress  data: {"message":"🌐 stargazer_ep03.md → en","step":"translate","index":0,"total":1,"lang":"en"}
event: artifact  data: {"kind":"translation","path":"translations/en/stargazer_ep03.en.md","complete":true,…}
event: done      data: {"status":"succeeded","result":{…},"error":null,"usage":{"input_tokens":…,"output_tokens":…,"calls":1}}
```

`error.code`: `auth_missing` / `auth_invalid` / `rate_limited` / `context_too_large` / `refusal` /
`provider_error` / `invalid_input` / `internal_error`

中止はストリーム受信中・OpenAI の background ポーリング中にも効く（受信を切って即終了）。

## プロジェクトフォルダ

```
MyProject/
  project.yaml            name / work / source / output_lang / review_cast / models
  casts/cast.yaml
  personas/  episodes/
  translations/<lang>/    <章>.<lang>.md / .segments.json / translation_notes.yaml
  .dz/jobs/<id>.json      ジョブ履歴（キーは含まない）
```
