import { useEffect, useState } from "react";
import { KeyStatus } from "./lib/api";
import { go, useRoute } from "./lib/hooks";
import { ProjectsPage } from "./pages/Projects";
import { SettingsPage } from "./pages/Settings";
import { ProjectPage } from "./pages/Project";
import { Pill } from "./components/ui";

export function App() {
  const route = useRoute();
  const [sidecar, setSidecar] = useState<{ ready: boolean; error: string | null }>({ ready: false, error: null });
  const [keys, setKeys] = useState<KeyStatus | null>(null);

  useEffect(() => {
    window.dz.sidecar().then(setSidecar);
    window.dz.keys.status().then(setKeys);
    return window.dz.onSidecar(setSidecar);
  }, []);

  const [section, id, tab] = route;
  const page = section === "settings" ? "settings" : section === "p" && id ? "project" : "projects";

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="logo">
          <span className="word">DIVERGENCE</span>
          <span className="z">//<span>Z</span></span>
        </div>
        <nav className="nav">
          <a href="#/" className={page === "projects" || page === "project" ? "active" : ""}><span className="ico">▤</span>プロジェクト</a>
          <a href="#/settings" className={page === "settings" ? "active" : ""}><span className="ico">⚿</span>キー & モデル</a>
        </nav>
        <div className="foot">
          <div className="row" style={{ gap: 8 }}>
            <Pill status={sidecar.ready ? "done" : sidecar.error ? "failed" : "queued"} label={sidecar.ready ? "ENGINE" : sidecar.error ? "ENGINE DOWN" : "BOOTING"} />
          </div>
          <div className="row" style={{ gap: 6 }}>
            <span className={`chip${keys?.openai ? " on" : ""}`}>OpenAI</span>
            <span className={`chip${keys?.anthropic ? " on" : ""}`}>Anthropic</span>
          </div>
          {sidecar.error ? <div className="small" style={{ color: "var(--red)" }}>{sidecar.error.slice(0, 160)}</div> : null}
          <span className="mono">v0.1 · BYOK · local only</span>
        </div>
      </aside>
      <main className="main">
        {!sidecar.ready && !sidecar.error ? <div className="page"><span className="mono dim">STARTING ENGINE…</span></div> : null}
        {sidecar.ready && page === "projects" ? <ProjectsPage keys={keys} /> : null}
        {sidecar.ready && page === "settings" ? <SettingsPage keys={keys} onKeys={setKeys} /> : null}
        {sidecar.ready && page === "project" ? <ProjectPage id={id} tab={tab || "pipeline"} key={id} /> : null}
        {sidecar.error ? (
          <div className="page">
            <div className="banner pink">ENGINE DOWN — Python サイドカーを起動できませんでした
              <span className="spacer" /><button className="btn sm ghost" onClick={() => go("")}>再読込</button>
            </div>
          </div>
        ) : null}
      </main>
    </div>
  );
}
