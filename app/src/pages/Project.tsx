import { useEffect, useState } from "react";
import { api, Project } from "../lib/api";
import { go, JobState, latestActiveJob, useAsync, useJob } from "../lib/hooks";
import { ErrorBox, Glitch, JobConsole, Pill } from "../components/ui";
import { PipelineTab } from "./tabs/Pipeline";
import { CastTab } from "./tabs/Cast";
import { TranslateTab } from "./tabs/Translate";
import { VoiceTab } from "./tabs/Voice";
import { ConfigTab } from "./tabs/Config";

const TABS: [string, string][] = [
  ["pipeline", "パイプライン"],
  ["cast", "人物表"],
  ["translate", "翻訳"],
  ["voice", "ボイス"],
  ["config", "設定"],
];

export interface ProjectCtx {
  project: Project;
  reload: () => void;
  job: JobState;
  jobId: string | null;
  jobType: string | null;
  run: (type: string, params?: Record<string, any>) => Promise<void>;
  cancel: () => void;
  resume: () => void;
  runError: string | null;
}

export function ProjectPage({ id, tab }: { id: string; tab: string }) {
  const { data: project, error, reload } = useAsync(() => api.project(id), [id]);
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobType, setJobType] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const job = useJob(jobId, () => reload());

  // 画面を開き直したとき、実行中のジョブがあれば再接続する
  useEffect(() => {
    latestActiveJob(id).then((j) => {
      if (j) {
        setJobId(j.id);
        setJobType(j.type);
      }
    }).catch(() => {});
  }, [id]);

  if (error) return <div className="page"><ErrorBox error={error} /></div>;
  if (!project) return <div className="page"><span className="mono dim">LOADING…</span></div>;

  const ctx: ProjectCtx = {
    project,
    reload,
    job,
    jobId,
    jobType,
    runError,
    run: async (type, params = {}) => {
      setRunError(null);
      try {
        const j = await api.submit(type, project.id, params);
        setJobType(type);
        setJobId(j.id);
      } catch (e: any) {
        setRunError(e.message);
      }
    },
    cancel: () => { if (jobId) api.cancel(jobId); },
    resume: () => { if (jobId) api.resume(jobId); },
  };
  const busy = job.status === "queued" || job.status === "running" || job.status === "awaiting_review";

  return (
    <div className="page">
      <header className="stack" style={{ gap: 10 }}>
        <div className="row between">
          <span className="eyebrow">project // {project.id}</span>
          <div className="row">
            {busy ? <Pill status={job.status!} label={`${jobType} · ${job.status}`} /> : null}
            <button className="btn ghost sm" onClick={() => window.dz.reveal(project.root)}>フォルダを表示</button>
            <button className="btn ghost sm" onClick={() => go("")}>← 一覧</button>
          </div>
        </div>
        <Glitch text={project.name} jp />
        <div className="muted">{project.work || "作品名未設定"} <span className="dim mono small">· {project.source || "原稿未設定"}</span></div>
      </header>

      <nav className="tabs">
        {TABS.map(([key, label]) => (
          <button key={key} className={tab === key ? "active" : ""} onClick={() => go("p", project.id, key)}>{label}</button>
        ))}
      </nav>

      {job.review && tab !== "pipeline" ? (
        <div className="banner">
          <span className="mono">REVIEW</span>
          <span>人物表の確認待ちです。内容を確認したら続行してください。</span>
          <span className="spacer" />
          <button className="btn sm lime" onClick={ctx.resume}>OK、続ける ▶</button>
        </div>
      ) : null}
      {runError ? <ErrorBox error={runError} /> : null}

      {tab === "pipeline" ? <PipelineTab ctx={ctx} /> : null}
      {tab === "cast" ? <CastTab ctx={ctx} /> : null}
      {tab === "translate" ? <TranslateTab ctx={ctx} /> : null}
      {tab === "voice" ? <VoiceTab ctx={ctx} /> : null}
      {tab === "config" ? <ConfigTab ctx={ctx} /> : null}

      {tab !== "pipeline" && tab !== "voice" && jobId ? (
        <JobConsole job={job} title={jobType ?? ""} onCancel={ctx.cancel} />
      ) : null}
    </div>
  );
}
