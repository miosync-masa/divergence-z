// サイドカー API の型と呼び出し（すべて Electron main 経由。トークン・キーはレンダラーに来ない）

export type JobStatus = "queued" | "running" | "awaiting_review" | "succeeded" | "failed" | "cancelled";

export interface DzEvent {
  jobId: string;
  id?: number;
  type: "status" | "progress" | "artifact" | "done" | "stream_error";
  data: Record<string, any>;
}

export interface KeyStatus { openai: boolean; anthropic: boolean; openai_base_url: string }

declare global {
  interface Window {
    dz: {
      sidecar(): Promise<{ ready: boolean; error: string | null }>;
      onSidecar(cb: (s: { ready: boolean; error: string | null }) => void): () => void;
      api(method: string, path: string, body?: unknown): Promise<{ status: number; ok: boolean; data: any }>;
      subscribe(jobId: string, lastEventId?: number): Promise<boolean>;
      unsubscribe(jobId: string): Promise<boolean>;
      onEvent(cb: (ev: DzEvent) => void): () => void;
      keys: {
        status(): Promise<KeyStatus>;
        save(update: Partial<{ openai: string; anthropic: string; openai_base_url: string }>): Promise<KeyStatus>;
      };
      pickFolder(title?: string): Promise<string | null>;
      reveal(path: string): Promise<void>;
    };
  }
}

export interface ModelSpec {
  id: string;
  provider: "anthropic" | "openai";
  label: string;
  context_window: number | null;
  max_output: number | null;
  reasoning: string;
  efforts: string[];
  default_effort: string | null;
  background: boolean;
  web_search: string | null;
  price_in: number | null;
  price_out: number | null;
}

export type StepName = "cast" | "persona" | "episode" | "translate" | "voice" | "generate";
export const STEPS: StepName[] = ["cast", "persona", "episode", "translate", "voice", "generate"];

export interface Project {
  id: string;
  root: string;
  name: string;
  work: string;
  source: string;
  output_lang: string;
  cast_file: string;
  review_cast: boolean;
  models: Record<StepName, { model: string; effort?: string }>;
  status?: { cast: boolean; personas: Record<string, boolean>; episodes: Record<string, boolean> };
}

export interface Job {
  id: string;
  type: string;
  project_id: string;
  params: Record<string, any>;
  status: JobStatus;
  error: { code: string; message: string } | null;
  result: any;
  usage: { input_tokens?: number; output_tokens?: number; calls?: number };
  last_event_id: number;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  display?: string;
  time: number;
  model?: string;
  usage?: Record<string, any>;
}

export interface Chat {
  id: string;
  title: string;
  character: string;
  model: string;
  effort: string | null;
  user_profile: string;
  created: number;
  updated: number;
  messages: ChatMessage[];
  system_chars?: number;
  system_tokens?: number;
}

export interface ChatSummary {
  id: string;
  title: string;
  character: string;
  model: string;
  updated: number;
  messages: number;
  preview: string;
}

export interface CharacterInfo { label: string; persona: string; episode: string | null; in_cast: boolean }

export interface EstimateRow {
  step: string;
  target: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  context_window: number | null;
  fits: boolean | null;
  cost_usd: number | null;
  message: string;
}

export class ApiError extends Error {
  constructor(public status: number, public detail: any) {
    super(typeof detail === "string" ? detail : detail?.detail || detail?.error || `HTTP ${status}`);
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await window.dz.api(method, path, body);
  if (!r.ok) throw new ApiError(r.status, r.data);
  return r.data as T;
}

const enc = encodeURIComponent;

export const api = {
  models: () => call<{ models: ModelSpec[] }>("GET", "/models").then((r) => r.models),
  projects: () => call<{ projects: Project[] }>("GET", "/projects").then((r) => r.projects),
  openProject: (body: Partial<Project> & { root: string }) => call<Project>("POST", "/projects", body),
  project: (id: string) => call<Project>("GET", `/projects/${id}`),
  patchProject: (id: string, body: Partial<Project>) => call<Project>("PATCH", `/projects/${id}`, body),
  closeProject: (id: string) => call("DELETE", `/projects/${id}`),

  cast: (id: string) => call<{ path: string; yaml: string; data: any }>("GET", `/projects/${id}/cast`),
  putCast: (id: string, yaml: string) => call("PUT", `/projects/${id}/cast`, { yaml }),
  personas: (id: string) => call<{ files: string[] }>("GET", `/projects/${id}/personas`).then((r) => r.files),
  episodes: (id: string) => call<{ files: string[] }>("GET", `/projects/${id}/episodes`).then((r) => r.files),

  translations: (id: string, lang: string) =>
    call<{ lang: string; notes: boolean; chapters: { chapter: string; file: string; status: string }[] }>(
      "GET", `/projects/${id}/translations/${enc(lang)}`),
  chapter: (id: string, lang: string, chapter: string) =>
    call<{ segments: { id: string; source: string; target: string }[] }>(
      "GET", `/projects/${id}/translations/${enc(lang)}/${enc(chapter)}`),
  notes: (id: string, lang: string) =>
    call<{ yaml: string; data: any }>("GET", `/projects/${id}/translations/${enc(lang)}/notes`),

  estimate: (id: string, body: { steps: string[]; characters?: string[]; langs?: string[]; chapters?: string }) =>
    call<{ rows: EstimateRow[]; total_input_tokens: number; total_output_tokens: number;
           total_cost_usd: number | null; all_fit: boolean | null; characters: string[];
           source: { files: number; chars: number } }>("POST", `/projects/${id}/estimate`, body),

  characters: (id: string) =>
    call<{ characters: CharacterInfo[] }>("GET", `/projects/${id}/characters`).then((r) => r.characters),
  chatTemplate: () => call<{ text: string; path: string; custom: boolean }>("GET", "/chat/template"),
  putChatTemplate: (text: string) => call("PUT", "/chat/template", { text }),
  chats: (id: string) => call<{ chats: ChatSummary[] }>("GET", `/projects/${id}/chats`).then((r) => r.chats),
  createChat: (id: string, body: { character: string; model?: string; effort?: string; user_profile?: string; title?: string }) =>
    call<Chat>("POST", `/projects/${id}/chats`, body),
  chat: (id: string, chatId: string) => call<Chat>("GET", `/projects/${id}/chats/${chatId}`),
  chatSystem: (id: string, chatId: string) =>
    call<{ text: string }>("GET", `/projects/${id}/chats/${chatId}/system`).then((r) => r.text),
  deleteChat: (id: string, chatId: string) => call("DELETE", `/projects/${id}/chats/${chatId}`),

  jobs: (projectId?: string) =>
    call<{ jobs: Job[] }>("GET", `/jobs${projectId ? `?project_id=${projectId}` : ""}`).then((r) => r.jobs),
  submit: (type: string, projectId: string, params: Record<string, any> = {}) =>
    call<Job>("POST", "/jobs", { type, project_id: projectId, params }),
  job: (id: string) => call<Job>("GET", `/jobs/${id}`),
  cancel: (id: string) => call<Job>("POST", `/jobs/${id}/cancel`),
  resume: (id: string) => call<Job>("POST", `/jobs/${id}/resume`),
};

export const ERROR_HINTS: Record<string, string> = {
  auth_missing: "このモデルのプロバイダの API キーが未設定です。設定画面で入力してください。",
  auth_invalid: "API キーが無効か、権限がありません。",
  rate_limited: "レート制限に達しました。少し待ってから再実行してください。",
  context_too_large: "入力がモデルのコンテキストに収まりません。より大きいモデルを選んでください。",
  refusal: "モデルがこのリクエストを断りました。チャットではシステム指示（テンプレート）の内容が原因のこともあります。",
  invalid_input: "入力やプロジェクトの設定を確認してください。",
  provider_error: "プロバイダ側でエラーが起きました。再実行してください。",
  internal_error: "アプリ内部のエラーです。",
};
