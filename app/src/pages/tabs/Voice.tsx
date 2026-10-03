import { useState } from "react";
import { api } from "../../lib/api";
import { useAsync, useJob } from "../../lib/hooks";
import { ErrorBox, JobConsole, Pill, Sticker } from "../../components/ui";
import type { ProjectCtx } from "../Project";

// 出力から 【見出し】 の本文を取り出す
function section(text: string, header: string): string | null {
  const i = text.indexOf(header);
  if (i < 0) return null;
  const rest = text.slice(i + header.length);
  const j = rest.indexOf("【");
  return (j >= 0 ? rest.slice(0, j) : rest).trim();
}

export function VoiceTab({ ctx }: { ctx: ProjectCtx }) {
  const { project } = ctx;
  const cast = useAsync(() => api.cast(project.id).catch(() => null), [project.id]);
  const labels: string[] = (cast.data?.data?.characters || [])
    .map((c: any) => c.label)
    .filter((l: string) => project.status?.personas[l]);

  const [persona, setPersona] = useState<string>("");
  const [target, setTarget] = useState<string>("");
  const [input, setInput] = useState("");
  const [context, setContext] = useState("");
  const [outLang, setOutLang] = useState("");
  const [dual, setDual] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [showRaw, setShowRaw] = useState(false);
  const job = useJob(jobId);

  const who = persona || labels[0] || "";
  const run = async () => {
    setErr(null);
    try {
      const j = await api.submit("voice", project.id, {
        persona: who, input, context, output_lang: outLang || undefined,
        target: target || undefined, dual: dual && !!target,
      });
      setJobId(j.id);
    } catch (e: any) {
      setErr(e.message);
    }
  };

  const p1 = job.result?.phase1?.output as string | undefined;
  const p2 = job.result?.phase2?.output as string | undefined;
  const running = job.status === "queued" || job.status === "running";

  return (
    <div className="grid c2" style={{ alignItems: "start" }}>
      <div className="card hot stack">
        <div className="row"><Sticker color="pink">VOICE</Sticker><h2>この人の声で言わせる</h2></div>
        <label className="field">話す人
          <select value={who} onChange={(e) => setPersona(e.target.value)}>
            {labels.map((l) => <option key={l}>{l}</option>)}
          </select>
        </label>
        <label className="field">言わせたいこと
          <textarea value={input} onChange={(e) => setInput(e.target.value)} placeholder="例: 今日の夕飯はカレーにしよう" />
        </label>
        <label className="field">状況
          <input value={context} onChange={(e) => setContext(e.target.value)} placeholder="例: 主人公の家の台所。地球に来て数週間" />
        </label>
        <div className="grid c2">
          <label className="field">聞き手（任意）
            <select value={target} onChange={(e) => setTarget(e.target.value)}>
              <option value="">—</option>
              {labels.filter((l) => l !== who).map((l) => <option key={l}>{l}</option>)}
            </select>
          </label>
          <label className="field">出力言語
            <select value={outLang} onChange={(e) => setOutLang(e.target.value)}>
              <option value="">原文と同じ</option>
              {["en", "zh", "ko", "fr", "es", "de"].map((l) => <option key={l}>{l}</option>)}
            </select>
          </label>
        </div>
        <label className="row small" style={{ gap: 8 }}>
          <input type="checkbox" checked={dual} disabled={!target} onChange={(e) => setDual(e.target.checked)} />
          聞き手にも返事をさせる（デュアル）
        </label>
        <div className="row">
          <button className="btn big" disabled={!who || !input || running} onClick={run}>{running ? "変換中…" : "▶ 声にする"}</button>
          <span className="dim small mono">{project.models.voice?.model} · {project.models.voice?.effort}</span>
        </div>
        {err ? <ErrorBox error={err} /> : null}
      </div>

      <div className="stack" style={{ gap: 26 }}>
        {p1 ? (
          <>
            <div className="stack">
              <div className="row"><Sticker>{who}</Sticker>{section(p1, "【適用された z_mode】") ? <Pill status="running" label={section(p1, "【適用された z_mode】")!.split(/\s|（/)[0]} /> : null}</div>
              <div className="voice-out">{section(p1, "【変換結果】") ?? p1}</div>
            </div>
            {p2 ? (
              <div className="stack" style={{ marginTop: 10 }}>
                <div className="row"><Sticker color="cyan">{target}</Sticker></div>
                <div className="voice-out" style={{ background: "linear-gradient(135deg, #fff, #e3fbff)", boxShadow: "var(--pop-lg), 0 0 40px rgba(34,228,255,.35)" }}>
                  {section(p2, "【応答結果】") ?? p2}
                </div>
              </div>
            ) : null}
            <button className="btn ghost sm" style={{ width: "fit-content" }} onClick={() => setShowRaw(!showRaw)}>
              {showRaw ? "分析を隠す" : "分析（z_mode / 感情テンソル）を見る"}
            </button>
            {showRaw ? <div className="console" style={{ maxHeight: 420 }}><div className="ln">{p1}{p2 ? `\n\n────────\n\n${p2}` : ""}</div></div> : null}
          </>
        ) : !jobId ? (
          <div className="card flat empty"><div className="big">SAY IT</div>左で話す人と言わせたいことを入れてください</div>
        ) : null}
        {jobId && !p1 ? <JobConsole job={job} title="voice" onCancel={() => api.cancel(jobId)} /> : null}
      </div>
    </div>
  );
}
