import { useState } from "react";
import { api, KeyStatus } from "../lib/api";
import { useAsync } from "../lib/hooks";
import { ErrorBox, Glitch, Pill, Sticker } from "../components/ui";

export function SettingsPage({ keys, onKeys }: { keys: KeyStatus | null; onKeys: (k: KeyStatus) => void }) {
  const [openai, setOpenai] = useState("");
  const [anthropic, setAnthropic] = useState("");
  const [baseUrl, setBaseUrl] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const models = useAsync(api.models, []);

  const save = async (update: Parameters<typeof window.dz.keys.save>[0]) => {
    setError(null);
    try {
      const k = await window.dz.keys.save(update);
      onKeys(k);
      setOpenai("");
      setAnthropic("");
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e: any) {
      setError(e.message);
    }
  };

  return (
    <div className="page">
      <div className="stack" style={{ gap: 4 }}>
        <span className="eyebrow">bring your own key</span>
        <Glitch text="SETTINGS" />
      </div>

      <div className="card hot">
        <div className="card-head">
          <div className="row"><Sticker color="pink">BYOK</Sticker><h2>API キー</h2></div>
          {saved ? <Pill status="done" label="SAVED" /> : null}
        </div>
        <p className="muted small" style={{ marginTop: 0 }}>
          キーは OS のキーチェーンで暗号化してこの PC に保存します。画面側には読み戻さず、
          送信先は各プロバイダの API だけです。原稿もこの PC から外には出ません。
        </p>
        <div className="grid c2">
          <div className="stack">
            <div className="row between">
              <h3>OpenAI</h3>
              <Pill status={keys?.openai ? "done" : "pending"} label={keys?.openai ? "SET" : "NOT SET"} />
            </div>
            <input type="password" placeholder={keys?.openai ? "••••••••（変更する場合のみ入力）" : "sk-..."} value={openai} onChange={(e) => setOpenai(e.target.value)} />
            <input placeholder="Base URL（任意・プロキシ / 互換 API）" value={baseUrl ?? keys?.openai_base_url ?? ""} onChange={(e) => setBaseUrl(e.target.value)} />
            <div className="row">
              <button className="btn cyan sm" disabled={!openai && baseUrl == null} onClick={() => save({ ...(openai ? { openai } : {}), ...(baseUrl != null ? { openai_base_url: baseUrl } : {}) })}>保存</button>
              {keys?.openai ? <button className="btn ghost sm" onClick={() => save({ openai: "" })}>削除</button> : null}
            </div>
          </div>
          <div className="stack">
            <div className="row between">
              <h3>Anthropic</h3>
              <Pill status={keys?.anthropic ? "done" : "pending"} label={keys?.anthropic ? "SET" : "NOT SET"} />
            </div>
            <input type="password" placeholder={keys?.anthropic ? "••••••••（変更する場合のみ入力）" : "sk-ant-..."} value={anthropic} onChange={(e) => setAnthropic(e.target.value)} />
            <div className="row">
              <button className="btn cyan sm" disabled={!anthropic} onClick={() => save({ anthropic })}>保存</button>
              {keys?.anthropic ? <button className="btn ghost sm" onClick={() => save({ anthropic: "" })}>削除</button> : null}
            </div>
          </div>
        </div>
        {error ? <div style={{ marginTop: 14 }}><ErrorBox error={error} /></div> : null}
      </div>

      <div className="card">
        <div className="card-head">
          <div className="row"><Sticker>MODELS</Sticker><h2>モデル登録表</h2></div>
          <span className="dim small mono">~/.divergence_z/models.yaml で追加・上書き</span>
        </div>
        {models.error ? <ErrorBox error={models.error} /> : null}
        <table className="t">
          <thead>
            <tr><th>MODEL</th><th>PROVIDER</th><th>CONTEXT</th><th>MAX OUT</th><th>EFFORT</th><th>$ IN / OUT (1M)</th><th>WEB</th></tr>
          </thead>
          <tbody>
            {models.data?.map((m) => (
              <tr key={m.id}>
                <td><b>{m.label}</b><div className="mono small dim">{m.id}</div></td>
                <td>
                  <span className="chip">{m.provider}</span>
                  {m.provider === "openai" && !keys?.openai ? <div className="small" style={{ color: "var(--red)" }}>key なし</div> : null}
                  {m.provider === "anthropic" && !keys?.anthropic ? <div className="small" style={{ color: "var(--red)" }}>key なし</div> : null}
                </td>
                <td className="mono">{m.context_window ? m.context_window.toLocaleString() : <span className="dim">?</span>}</td>
                <td className="mono">{m.max_output ? m.max_output.toLocaleString() : <span className="dim">?</span>}</td>
                <td className="small">{m.efforts.join(" · ") || "—"}</td>
                <td className="mono">{m.price_in != null ? `$${m.price_in} / $${m.price_out}` : <span className="dim">?</span>}</td>
                <td>{m.web_search ? "✓" : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
