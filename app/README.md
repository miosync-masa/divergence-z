# Divergence-Z Desktop (Electron)

BYOK のデスクトップアプリ。Python サイドカー（`divergence_z.server`）を子プロセスで起動し、
画面（React）は Electron の IPC 経由でだけ API を呼ぶ。トークンと API キーは画面側に渡らない。

## 開発

```bash
# 1. Python 側（リポジトリ直下）
python3 -m venv .venv && .venv/bin/pip install -e ".[server]"

# 2. アプリ
cd app
npm install
npm run dev          # Vite + Electron（ホットリロード）
npm run build && npm start   # ビルド版で起動
```

| 環境変数 | 説明 |
|---|---|
| `DZ_PYTHON` | サイドカーに使う Python（既定: リポジトリの `.venv/bin/python`） |
| `DZ_HOME` | プロジェクト一覧の保存先（既定: `~/.divergence_z`） |

サイドカーのログ: `~/Library/Application Support/divergence-z-app/sidecar.log`

## 画面確認（スクリーンショット）

```bash
DZ_SMOKE_OUT=/tmp/shots DZ_SMOKE_ROUTES="#/,#/settings" npx electron . --smoke
```

ウィンドウを表示せずに各ルートをキャプチャして終了する。

## 構成

```
electron/main.cjs     サイドカー起動・API 中継・SSE 中継・キー保存（safeStorage）
electron/preload.cjs  window.dz（画面に公開する最小 API）
src/pages/            プロジェクト一覧 / 設定 / プロジェクト（パイプライン・人物表・翻訳・ボイス・設定）
src/styles/theme.css  cyber pop テーマ
```
