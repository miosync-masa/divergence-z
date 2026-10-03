#!/usr/bin/env bash
# Build the Python sidecar into a standalone folder (dist-sidecar/dz-server/) with PyInstaller.
# The desktop app bundles this folder, so end users do not need Python.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
# 出力のアーキテクチャ（arm64 / x86_64）。既定はこのマシンのもの。
# python.org の universal Python は x86_64 で起動することがあるので、arch で固定して実行する
# （このスクリプト自体が Rosetta の bash で動くと uname -m は x86_64 を返すので、実機を見る）
if [[ -z "${TARGET_ARCH:-}" && "$(uname)" == "Darwin" ]]; then
  if [[ "$(sysctl -n hw.optional.arm64 2>/dev/null || echo 0)" == "1" ]]; then TARGET_ARCH=arm64; else TARGET_ARCH=x86_64; fi
fi
ARCH="${TARGET_ARCH:-$(uname -m)}"
RUN=("$PY")
if [[ "$(uname)" == "Darwin" ]]; then
  # PyInstaller は解析用に Python を子プロセスで起動し直すので、そちらの arch も揃える
  export ARCHPREFERENCE="$ARCH"
  RUN=(/usr/bin/arch "-$ARCH" "$PY")
fi
rm -rf build/dz-server dist-sidecar
ARCH_ARGS=()
if [[ "$(uname)" == "Darwin" ]]; then ARCH_ARGS=(--target-arch "$ARCH"); fi   # macOS だけのオプション
"${RUN[@]}" -m PyInstaller packaging/dz_server_entry.py \
  "${ARCH_ARGS[@]}" \
  --name dz-server \
  --onedir --noconfirm --clean \
  --distpath dist-sidecar --workpath build/dz-server --specpath build/dz-server \
  --collect-submodules uvicorn \
  --collect-submodules divergence_z \
  --collect-data anthropic \
  --collect-data openai \
  --hidden-import PyPDF2
echo "built: dist-sidecar/dz-server/ ($ARCH)"
