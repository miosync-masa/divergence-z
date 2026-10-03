// Divergence-Z — Electron main process
//
// - Python サイドカー（divergence_z.server）を子プロセスとして起動し、stdout の ready 行から
//   ポートとトークンを受け取る。トークンと API キーはこのプロセスから外（レンダラー）に出さない。
// - レンダラーは preload の window.dz 経由で IPC を呼ぶだけ（contextIsolation + sandbox）。
// - API キーは OS のキーチェーン（safeStorage）で暗号化して userData に保存し、起動時にサイドカーへ渡す。

const { app, BrowserWindow, ipcMain, dialog, safeStorage, shell } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const readline = require("node:readline");

const REPO_ROOT = path.resolve(__dirname, "..", "..");
const DEV_URL = process.env.DZ_DEV_URL;
const SMOKE = process.argv.includes("--smoke");   // 起動 → 画面キャプチャ → 終了（開発用）

let win = null;
let sidecar = null;          // ChildProcess
let endpoint = null;         // { base, token }
let sidecarError = null;
const subscriptions = new Map();   // jobId -> AbortController

// ---------------------------------------------------------------------------
// sidecar
// ---------------------------------------------------------------------------

function pythonPath() {
  if (process.env.DZ_PYTHON) return process.env.DZ_PYTHON;
  const venv = path.join(REPO_ROOT, ".venv", "bin", "python");
  return fs.existsSync(venv) ? venv : "python3";
}

function startSidecar() {
  return new Promise((resolve, reject) => {
    // macOS: universal な Python は GUI アプリから起動すると x86_64 で立ち上がることがあり、
    // arm64 の venv（pydantic_core 等のネイティブ拡張）を読めずに落ちる。Electron と同じ arch に固定する
    const [cmd, args] = process.platform === "darwin"
      ? ["/usr/bin/arch", [`-${process.arch === "arm64" ? "arm64" : "x86_64"}`, pythonPath(), "-m", "divergence_z.server"]]
      : [pythonPath(), ["-m", "divergence_z.server"]];
    const proc = spawn(cmd, args, {
      cwd: REPO_ROOT,
      env: { ...process.env, PYTHONUNBUFFERED: "1" },
      stdio: ["ignore", "pipe", "pipe"],
    });
    sidecar = proc;
    const timer = setTimeout(() => reject(new Error("sidecar did not become ready in 30s")), 30000);

    readline.createInterface({ input: proc.stdout }).on("line", (line) => {
      try {
        const msg = JSON.parse(line);
        if (msg.event === "ready") {
          clearTimeout(timer);
          endpoint = { base: `http://${msg.host}:${msg.port}`, token: msg.token };
          resolve(endpoint);
        }
      } catch {
        /* ready 行以外は無視 */
      }
    });
    let stderr = "";
    const log = fs.createWriteStream(path.join(app.getPath("userData"), "sidecar.log"), { flags: "w" });
    proc.stderr.on("data", (d) => {
      log.write(d);
      stderr = (stderr + d.toString()).slice(-4000);
    });
    proc.on("exit", (code) => {
      clearTimeout(timer);
      if (!endpoint) {
        // 末尾（例外メッセージ）が一番役に立つ
        const tail = stderr.trim().split("\n").slice(-3).join(" / ");
        reject(new Error(`sidecar exited (${code}): ${tail}`));
      }
      endpoint = null;
      sidecarError = `sidecar exited (${code})`;
      win?.webContents.send("dz:sidecar", { ready: false, error: sidecarError });
    });
  });
}

async function api(method, pathname, body) {
  if (!endpoint) throw new Error(sidecarError || "sidecar not ready");
  const res = await fetch(endpoint.base + pathname, {
    method,
    headers: {
      Authorization: `Bearer ${endpoint.token}`,
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { raw: text };
  }
  return { status: res.status, ok: res.ok, data };
}

// SSE を main で読み、レンダラーへ転送する（トークンをレンダラーに渡さないため）
async function subscribe(jobId, lastEventId = 0) {
  if (subscriptions.has(jobId)) return;
  const ctrl = new AbortController();
  subscriptions.set(jobId, ctrl);
  try {
    const res = await fetch(`${endpoint.base}/jobs/${jobId}/events?last_event_id=${lastEventId}`, {
      headers: { Authorization: `Bearer ${endpoint.token}` },
      signal: ctrl.signal,
    });
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    let ev = {};
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, idx);
        buf = buf.slice(idx + 1);
        if (line.startsWith("id:")) ev.id = Number(line.slice(3).trim());
        else if (line.startsWith("event:")) ev.type = line.slice(6).trim();
        else if (line.startsWith("data:")) ev.data = JSON.parse(line.slice(5));
        else if (line === "" && ev.type) {
          win?.webContents.send("dz:event", { jobId, ...ev });
          ev = {};
        }
      }
    }
  } catch (e) {
    if (e.name !== "AbortError") win?.webContents.send("dz:event", { jobId, type: "stream_error", data: { message: String(e) } });
  } finally {
    subscriptions.delete(jobId);
  }
}

// ---------------------------------------------------------------------------
// BYOK keys (safeStorage)
// ---------------------------------------------------------------------------

const keysFile = () => path.join(app.getPath("userData"), "keys.bin");

function loadKeys() {
  try {
    if (!fs.existsSync(keysFile()) || !safeStorage.isEncryptionAvailable()) return {};
    return JSON.parse(safeStorage.decryptString(fs.readFileSync(keysFile())));
  } catch {
    return {};
  }
}

function saveKeys(keys) {
  if (!safeStorage.isEncryptionAvailable()) throw new Error("OS keychain is not available");
  fs.writeFileSync(keysFile(), safeStorage.encryptString(JSON.stringify(keys)), { mode: 0o600 });
}

async function pushKeysToSidecar(keys) {
  return api("PUT", "/session/keys", {
    openai: keys.openai ?? "",
    anthropic: keys.anthropic ?? "",
    openai_base_url: keys.openai_base_url ?? "",
  });
}

// ---------------------------------------------------------------------------
// IPC
// ---------------------------------------------------------------------------

function registerIpc() {
  ipcMain.handle("dz:sidecar", () => ({ ready: !!endpoint, error: sidecarError }));
  ipcMain.handle("dz:api", (_e, method, pathname, body) => api(method, pathname, body));
  ipcMain.handle("dz:subscribe", (_e, jobId, lastEventId) => {
    subscribe(jobId, lastEventId);
    return true;
  });
  ipcMain.handle("dz:unsubscribe", (_e, jobId) => {
    subscriptions.get(jobId)?.abort();
    return true;
  });
  // キーはレンダラーに返さない（設定済みかどうかだけ）
  ipcMain.handle("dz:keys:status", () => {
    const k = loadKeys();
    return { openai: !!k.openai, anthropic: !!k.anthropic, openai_base_url: k.openai_base_url || "" };
  });
  ipcMain.handle("dz:keys:save", async (_e, update) => {
    const keys = { ...loadKeys() };
    for (const name of ["openai", "anthropic", "openai_base_url"]) {
      if (update[name] !== undefined) keys[name] = update[name] || undefined;
    }
    saveKeys(keys);
    await pushKeysToSidecar(keys);
    return { openai: !!keys.openai, anthropic: !!keys.anthropic, openai_base_url: keys.openai_base_url || "" };
  });
  ipcMain.handle("dz:pickFolder", async (_e, title) => {
    const r = await dialog.showOpenDialog(win, { title, properties: ["openDirectory", "createDirectory"] });
    return r.canceled ? null : r.filePaths[0];
  });
  ipcMain.handle("dz:reveal", (_e, p) => shell.showItemInFolder(p));
}

// ---------------------------------------------------------------------------
// window
// ---------------------------------------------------------------------------

async function createWindow() {
  win = new BrowserWindow({
    width: 1360,
    height: 880,
    minWidth: 1040,
    minHeight: 680,
    backgroundColor: "#0a0a18",
    titleBarStyle: "hiddenInset",
    show: !SMOKE,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  // 外部リンクはブラウザで開き、アプリ内では遷移させない
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });
  if (DEV_URL) await win.loadURL(DEV_URL);
  else await win.loadFile(path.join(__dirname, "..", "dist", "index.html"));
}

app.whenReady().then(async () => {
  registerIpc();
  try {
    await startSidecar();
    const keys = loadKeys();
    if (keys.openai || keys.anthropic) await pushKeysToSidecar(keys);
  } catch (e) {
    sidecarError = String(e.message || e);
  }
  await createWindow();
  win.webContents.send("dz:sidecar", { ready: !!endpoint, error: sidecarError });

  if (SMOKE) {
    const out = process.env.DZ_SMOKE_OUT || path.join(app.getPath("temp"), "dz-smoke");
    fs.mkdirSync(out, { recursive: true });
    const routes = (process.env.DZ_SMOKE_ROUTES || "#/").split(",");
    for (const [i, route] of routes.entries()) {
      await win.webContents.executeJavaScript(`location.hash = ${JSON.stringify(route)}`);
      await new Promise((r) => setTimeout(r, Number(process.env.DZ_SMOKE_WAIT || 2500)));
      const img = await win.webContents.capturePage();
      fs.writeFileSync(path.join(out, `screen-${i}.png`), img.toPNG());
    }
    app.quit();
  }
});

app.on("window-all-closed", () => app.quit());
app.on("before-quit", () => {
  for (const ctrl of subscriptions.values()) ctrl.abort();
  sidecar?.kill();
});
