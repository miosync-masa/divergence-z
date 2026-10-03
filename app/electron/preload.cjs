// レンダラーに公開する API（最小限）。トークン・API キーはここを通らない。
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("dz", {
  sidecar: () => ipcRenderer.invoke("dz:sidecar"),
  onSidecar: (cb) => {
    const h = (_e, s) => cb(s);
    ipcRenderer.on("dz:sidecar", h);
    return () => ipcRenderer.removeListener("dz:sidecar", h);
  },
  api: (method, path, body) => ipcRenderer.invoke("dz:api", method, path, body),
  subscribe: (jobId, lastEventId = 0) => ipcRenderer.invoke("dz:subscribe", jobId, lastEventId),
  unsubscribe: (jobId) => ipcRenderer.invoke("dz:unsubscribe", jobId),
  onEvent: (cb) => {
    const h = (_e, ev) => cb(ev);
    ipcRenderer.on("dz:event", h);
    return () => ipcRenderer.removeListener("dz:event", h);
  },
  keys: {
    status: () => ipcRenderer.invoke("dz:keys:status"),
    save: (update) => ipcRenderer.invoke("dz:keys:save", update),
  },
  pickFolder: (title) => ipcRenderer.invoke("dz:pickFolder", title),
  reveal: (p) => ipcRenderer.invoke("dz:reveal", p),
});
