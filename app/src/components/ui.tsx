import { ReactNode, useEffect, useRef } from "react";
import { ERROR_HINTS, EstimateRow } from "../lib/api";
import { JobState } from "../lib/hooks";

export function Glitch({ text, jp = false, size }: { text: string; jp?: boolean; size?: number }) {
  return (
    <h1 className={`glitch${jp ? " jp" : ""}`} data-text={text} style={size ? { fontSize: size } : undefined}>
      {text}
    </h1>
  );
}

export function Pill({ status, label }: { status: string; label?: string }) {
  return <span className={`pill ${status}`}>{label ?? status.replace("_", " ")}</span>;
}

export function Sticker({ children, color }: { children: ReactNode; color?: "pink" | "cyan" | "lime" }) {
  return <span className={`sticker${color ? " " + color : ""}`}>{children}</span>;
}

export function ErrorBox({ error }: { error: { code: string; message: string } | string | null }) {
  if (!error) return null;
  const e = typeof error === "string" ? { code: "", message: error } : error;
  return (
    <div className="banner pink" role="alert">
      <span className="mono">ERR{e.code ? `::${e.code}` : ""}</span>
      <div className="stack" style={{ gap: 2 }}>
        <span>{ERROR_HINTS[e.code] || "エラーが起きました"}</span>
        <span className="small" style={{ fontWeight: 400 }}>{e.message.slice(0, 280)}</span>
      </div>
    </div>
  );
}

export function ProgressBar({ index, total, done }: { index: number; total: number; done?: boolean }) {
  const pct = total ? Math.min(100, ((index + (done ? 1 : 0.5)) / total) * 100) : 0;
  return (
    <div className={`bar${done ? " idle" : ""}`}>
      <i style={{ width: `${done ? 100 : pct}%` }} />
    </div>
  );
}

const fmtTime = (t?: number) => {
  const d = t ? new Date(t * 1000) : new Date();
  return d.toTimeString().slice(0, 8);
};

export function JobConsole({ job, title, onCancel }: { job: JobState; title?: string; onCancel?: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.scrollTo({ top: ref.current.scrollHeight });
  }, [job.events.length]);
  if (!job.status) return null;
  const running = job.status === "running" || job.status === "queued" || job.status === "awaiting_review";
  return (
    <div className="card cool">
      <div className="card-head">
        <div className="row">
          <Sticker color="cyan">JOB</Sticker>
          <h3>{title}</h3>
          <Pill status={job.status} />
        </div>
        <div className="row">
          {job.usage?.input_tokens ? (
            <span className="mono small dim">
              {job.usage.input_tokens.toLocaleString()} in / {(job.usage.output_tokens || 0).toLocaleString()} out
            </span>
          ) : null}
          {running && onCancel ? <button className="btn danger sm" onClick={onCancel}>■ 中止</button> : null}
        </div>
      </div>
      {job.progress ? (
        <div className="stack" style={{ gap: 6, marginBottom: 14 }}>
          <div className="row between small">
            <span className="mono">{job.progress.step?.toUpperCase()}</span>
            <span className="mono">{Math.min(job.progress.index + 1, job.progress.total)} / {job.progress.total}</span>
          </div>
          <ProgressBar index={job.progress.index} total={job.progress.total} done={!running} />
        </div>
      ) : null}
      <div className="console" ref={ref}>
        {job.events.map((ev, i) => {
          const t = <span className="t">{fmtTime(ev.data?.time)}</span>;
          if (ev.type === "progress" && ev.data.level === "debug") return null;
          if (ev.type === "status") return <div key={i} className="ln status">{t}» {ev.data.status}{ev.data.reason ? ` (${ev.data.reason})` : ""}</div>;
          if (ev.type === "artifact") return <div key={i} className="ln artifact">{t}✚ {ev.data.kind}: {ev.data.path}</div>;
          if (ev.type === "done") return <div key={i} className={`ln ${ev.data.error ? "err" : "done"}`}>{t}■ {ev.data.status}{ev.data.error ? ` — ${ev.data.error.code}` : ""}</div>;
          if (ev.type === "stream_error") return <div key={i} className="ln err">{t}{ev.data.message}</div>;
          return <div key={i} className="ln">{t}{ev.data.message}</div>;
        })}
      </div>
      {job.error ? <div style={{ marginTop: 14 }}><ErrorBox error={job.error} /></div> : null}
    </div>
  );
}

export function EstimateTable({ rows, total, allFit }: { rows: EstimateRow[]; total: number | null; allFit: boolean | null }) {
  return (
    <div className="stack">
      <div className="row">
        <span className="sticker lime">ESTIMATE</span>
        <span className="muted small">API を呼ばずに計算した概算です（日本語は 1 文字 ≒ 1.4 トークン）</span>
        <span className="spacer" />
        <span className="mono" style={{ fontSize: 22, fontWeight: 700, color: "var(--yellow)" }}>
          {total == null ? "$ ?" : `≈ $${total.toFixed(2)}`}
        </span>
        {allFit === false ? <Pill status="failed" label="TOO LARGE" /> : allFit ? <Pill status="done" label="FITS" /> : <Pill status="pending" label="CONTEXT ?" />}
      </div>
      <table className="t">
        <thead>
          <tr><th>STEP</th><th>TARGET</th><th>MODEL</th><th>IN</th><th>OUT</th><th>FIT</th><th>COST</th></tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td className="mono">{r.step}</td>
              <td>{r.target}</td>
              <td className="mono small">{r.model}</td>
              <td className="mono">{r.input_tokens.toLocaleString()}</td>
              <td className="mono">{r.output_tokens.toLocaleString()}</td>
              <td>{r.fits == null ? <span className="dim">?</span> : r.fits ? <span style={{ color: "var(--lime)" }}>OK</span> : <span style={{ color: "var(--red)" }}>NG</span>}</td>
              <td className="mono">{r.cost_usd == null ? "?" : `$${r.cost_usd.toFixed(2)}`}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <div className="big">{title}</div>
      <div>{children}</div>
    </div>
  );
}
