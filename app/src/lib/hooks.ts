import { useCallback, useEffect, useRef, useState } from "react";
import { api, DzEvent, Job, JobStatus } from "./api";

// ---------------------------------------------------------------- hash router

export function useRoute(): string[] {
  const parse = () => (location.hash.replace(/^#\/?/, "") || "").split("/").filter(Boolean).map(decodeURIComponent);
  const [route, setRoute] = useState(parse);
  useEffect(() => {
    const h = () => setRoute(parse());
    window.addEventListener("hashchange", h);
    return () => window.removeEventListener("hashchange", h);
  }, []);
  return route;
}

export const go = (...parts: string[]) => {
  location.hash = "#/" + parts.map(encodeURIComponent).join("/");
};

// ---------------------------------------------------------------- async data

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const reload = useCallback(() => {
    setLoading(true);
    fn()
      .then((d) => { setData(d); setError(null); })
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(reload, [reload]);
  return { data, error, loading, reload, setData };
}

// ---------------------------------------------------------------- job stream

export interface JobState {
  status: JobStatus | null;
  events: DzEvent[];
  progress: { index: number; total: number; step?: string } | null;
  result: any;
  error: { code: string; message: string } | null;
  usage: { input_tokens?: number; output_tokens?: number; calls?: number };
  review: Record<string, any> | null;
}

const emptyJob: JobState = { status: null, events: [], progress: null, result: null, error: null, usage: {}, review: null };

export function useJob(jobId: string | null, onDone?: (s: JobState) => void): JobState {
  const [state, setState] = useState<JobState>(emptyJob);
  const doneRef = useRef(onDone);
  doneRef.current = onDone;

  useEffect(() => {
    setState(emptyJob);
    if (!jobId) return;
    const off = window.dz.onEvent((ev) => {
      if (ev.jobId !== jobId) return;
      setState((s) => {
        const next: JobState = { ...s, events: [...s.events, ev].slice(-400) };
        if (ev.type === "status") {
          next.status = ev.data.status;
          next.review = ev.data.status === "awaiting_review" ? ev.data : null;
        }
        if (ev.type === "progress" && typeof ev.data.total === "number") {
          next.progress = { index: ev.data.index, total: ev.data.total, step: ev.data.step };
        }
        if (ev.type === "done") {
          next.status = ev.data.status;
          next.result = ev.data.result;
          next.error = ev.data.error;
          next.usage = ev.data.usage || {};
          next.review = null;
          queueMicrotask(() => doneRef.current?.(next));
        }
        return next;
      });
    });
    window.dz.subscribe(jobId, 0);
    return () => {
      off();
      window.dz.unsubscribe(jobId);
    };
  }, [jobId]);
  return state;
}

export async function latestActiveJob(projectId: string, type?: string): Promise<Job | null> {
  const jobs = await api.jobs(projectId);
  const active = jobs
    .filter((j) => !["succeeded", "failed", "cancelled"].includes(j.status) && (!type || j.type === type))
    .sort((a, b) => (b as any).created - (a as any).created);
  return active[0] || null;
}
