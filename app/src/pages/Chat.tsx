import { useEffect, useRef, useState } from "react";
import { api, Chat, ChatMessage } from "../lib/api";
import { go, useAsync, useJob } from "../lib/hooks";
import { Empty, ErrorBox, Glitch, Pill, Sticker } from "../components/ui";

// キャラクターとの会話。システム指示 = 共通テンプレート ＋ ペルソナ ＋ エピソード（省略なし）
// ログはプロジェクトフォルダの chats/ に保存される（手元の PC だけ）
export function ChatPage({ projectId, chatId }: { projectId?: string; chatId?: string }) {
  const projects = useAsync(api.projects, []);
  const pid = projectId || projects.data?.[0]?.id || "";
  const characters = useAsync(() => (pid ? api.characters(pid) : Promise.resolve([])), [pid]);
  const chats = useAsync(() => (pid ? api.chats(pid) : Promise.resolve([])), [pid]);
  const [showNew, setShowNew] = useState(false);
  const [showTemplate, setShowTemplate] = useState(false);

  return (
    <div className="page" style={{ maxWidth: 1320 }}>
      <div className="row between">
        <div className="stack" style={{ gap: 4 }}>
          <span className="eyebrow">persona × episode chat · logs stay on this PC</span>
          <Glitch text="AI CHAT" />
        </div>
        <button className="btn ghost sm" onClick={() => setShowTemplate(!showTemplate)}>
          {showTemplate ? "閉じる" : "共通システム指示を編集"}
        </button>
      </div>

      {showTemplate ? <TemplateEditor /> : null}

      <div className="grid" style={{ gridTemplateColumns: "300px 1fr", alignItems: "start" }}>
        <aside className="card flat stack" style={{ position: "sticky", top: 0 }}>
          <label className="field">プロジェクト
            <select value={pid} onChange={(e) => go("chat", e.target.value)}>
              {projects.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </label>
          <button className="btn" disabled={!pid || !characters.data?.length} onClick={() => setShowNew(!showNew)}>
            ＋ 新しい会話
          </button>
          {pid && characters.data && !characters.data.length ? (
            <span className="small muted">このプロジェクトにはペルソナがまだありません。パイプラインか Web 生成で作ってください。</span>
          ) : null}
          {showNew && pid ? (
            <NewChat projectId={pid} characters={characters.data?.map((c) => c.label) || []}
                     onCreated={(c) => { setShowNew(false); chats.reload(); go("chat", pid, c.id); }} />
          ) : null}
          <div className="stack" style={{ gap: 6, maxHeight: 520, overflow: "auto" }}>
            {chats.data?.map((c) => (
              <button key={c.id} className={`chip${c.id === chatId ? " on" : ""}`}
                      style={{ flexDirection: "column", alignItems: "flex-start", borderRadius: 12, padding: "8px 12px", textAlign: "left" }}
                      onClick={() => go("chat", pid, c.id)}>
                <b>{c.title}</b>
                <span style={{ fontSize: 11, opacity: 0.8 }}>{c.preview || `${c.messages} messages`}</span>
              </button>
            ))}
          </div>
        </aside>

        {pid && chatId ? (
          <Conversation key={chatId} projectId={pid} chatId={chatId} onChanged={chats.reload} />
        ) : (
          <div className="card flat"><Empty title="SAY HI">左で会話を選ぶか、新しい会話を始めてください</Empty></div>
        )}
      </div>
    </div>
  );
}

function NewChat({ projectId, characters, onCreated }: {
  projectId: string; characters: string[]; onCreated: (c: Chat) => void;
}) {
  const models = useAsync(api.models, []);
  const project = useAsync(() => api.project(projectId), [projectId]);
  const [character, setCharacter] = useState(characters[0] || "");
  const [model, setModel] = useState("");
  const [effort, setEffort] = useState("");
  const [profile, setProfile] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const v = project.data?.models.voice;
    if (v && !model) { setModel(v.model); setEffort(v.effort || ""); }
  }, [project.data]);
  const spec = models.data?.find((m) => m.id === model);

  const create = async () => {
    setError(null);
    try {
      onCreated(await api.createChat(projectId, { character, model, effort: effort || undefined, user_profile: profile }));
    } catch (e: any) {
      setError(e.message);
    }
  };

  return (
    <div className="stack" style={{ gap: 10 }}>
      <label className="field">話す相手
        <select value={character} onChange={(e) => setCharacter(e.target.value)}>
          {characters.map((c) => <option key={c}>{c}</option>)}
        </select>
      </label>
      <label className="field">モデル
        <select value={model} onChange={(e) => {
          const m = models.data?.find((x) => x.id === e.target.value);
          setModel(e.target.value); setEffort(m?.default_effort || "");
        }}>
          {models.data?.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
        </select>
      </label>
      <label className="field">推論の強さ
        <select value={effort} disabled={!spec?.efforts.length} onChange={(e) => setEffort(e.target.value)}>
          {(spec?.efforts || []).map((ef) => <option key={ef}>{ef}</option>)}
        </select>
      </label>
      <label className="field">あなたについて（任意・関係性など）
        <textarea value={profile} onChange={(e) => setProfile(e.target.value)} style={{ minHeight: 64 }}
                  placeholder="例: 地球の高校生。船の修理を手伝っている仲間の一人" />
      </label>
      <button className="btn cyan sm" disabled={!character || !model} onClick={create}>始める</button>
      {error ? <ErrorBox error={error} /> : null}
    </div>
  );
}

function Conversation({ projectId, chatId, onChanged }: { projectId: string; chatId: string; onChanged: () => void }) {
  const chat = useAsync(() => api.chat(projectId, chatId), [projectId, chatId]);
  const [text, setText] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [sendError, setSendError] = useState<string | null>(null);
  const [system, setSystem] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const job = useJob(jobId, (s) => {
    setPending(null);
    if (s.status === "succeeded") { chat.reload(); onChanged(); }
  });
  const busy = job.status === "queued" || job.status === "running";

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth" }); }, [chat.data?.messages.length, pending]);

  const send = async () => {
    const t = text.trim();
    if (!t || busy) return;
    setSendError(null);
    setPending(t);
    setText("");
    try {
      const j = await api.submit("chat", projectId, { chat_id: chatId, text: t });
      setJobId(j.id);
    } catch (e: any) {
      setPending(null);
      setText(t);
      setSendError(e.message);
    }
  };

  if (chat.error) return <ErrorBox error={chat.error} />;
  if (!chat.data) return <span className="mono dim">LOADING…</span>;
  const c = chat.data;
  const last = [...c.messages].reverse().find((m) => m.role === "assistant");

  return (
    <div className="card stack" style={{ gap: 16, minHeight: 600 }}>
      <div className="row between">
        <div className="row">
          <Sticker color="pink">{c.character}</Sticker>
          <span className="dim mono small">{c.model} · {c.effort || "—"}</span>
        </div>
        <div className="row">
          <span className="dim mono small" title="システム指示（テンプレート＋ペルソナ＋エピソード）の大きさ">
            system ≈ {c.system_tokens?.toLocaleString()} tok
          </span>
          {last?.usage?.cache_read_input_tokens ? <Pill status="done" label="CACHE HIT" /> : null}
          <button className="btn ghost sm" onClick={async () =>
            setSystem(system ? null : await api.chatSystem(projectId, chatId))}>
            {system ? "指示を隠す" : "システム指示を見る"}
          </button>
          <button className="btn ghost sm" onClick={async () => {
            if (confirm("この会話のログを削除しますか？")) {
              await api.deleteChat(projectId, chatId); onChanged(); go("chat", projectId);
            }
          }}>削除</button>
        </div>
      </div>

      {system ? <div className="console" style={{ maxHeight: 360 }}><div className="ln">{system}</div></div> : null}

      <div className="stack" style={{ gap: 14 }}>
        {c.messages.length === 0 && !pending ? (
          <Empty title="…">{c.character} に話しかけてみてください</Empty>
        ) : null}
        {c.messages.map((m, i) => <Bubble key={i} m={m} name={c.character} />)}
        {pending ? <Bubble m={{ role: "user", content: pending, time: Date.now() / 1000 }} name={c.character} /> : null}
        {busy ? <div className="mono small dim">{c.character} が考えています…</div> : null}
        <div ref={bottom} />
      </div>

      {job.error ? <ErrorBox error={job.error} /> : null}
      {sendError ? <ErrorBox error={sendError} /> : null}

      <div className="row" style={{ alignItems: "flex-end", flexWrap: "nowrap" }}>
        <textarea value={text} onChange={(e) => setText(e.target.value)} style={{ minHeight: 70 }}
                  placeholder={`${c.character} に話しかける（⌘+Enter で送信）`}
                  onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); send(); } }} />
        <button className="btn" disabled={busy || !text.trim()} onClick={send}>送信</button>
      </div>
    </div>
  );
}

function Bubble({ m, name }: { m: ChatMessage; name: string }) {
  const mine = m.role === "user";
  return (
    <div className="stack" style={{ gap: 4, alignItems: mine ? "flex-end" : "flex-start" }}>
      <span className="mono small dim">{mine ? "YOU" : name}</span>
      <div style={{
        maxWidth: "78%", whiteSpace: "pre-wrap", padding: "12px 16px", borderRadius: 16,
        border: "2px solid #000", boxShadow: "4px 4px 0 #000", lineHeight: 1.7,
        background: mine ? "var(--cyan)" : "linear-gradient(135deg, #fff, #ffe9f5)",
        color: "#10102a", fontWeight: mine ? 700 : 500,
      }}>{mine ? m.content : (m.display || m.content)}</div>
    </div>
  );
}

function TemplateEditor() {
  const tpl = useAsync(api.chatTemplate, []);
  const [text, setText] = useState<string | null>(null);
  const [state, setState] = useState<"idle" | "saved">("idle");
  const [error, setError] = useState<string | null>(null);
  const value = text ?? tpl.data?.text ?? "";

  const save = async () => {
    setError(null);
    try {
      await api.putChatTemplate(value);
      setState("saved");
      setTimeout(() => setState("idle"), 2000);
      tpl.reload();
    } catch (e: any) {
      setError(e.message);
    }
  };

  return (
    <div className="card cool stack">
      <div className="row between">
        <div className="row"><Sticker color="cyan">TEMPLATE</Sticker><h2>共通システム指示</h2></div>
        <div className="row">
          {state === "saved" ? <Pill status="done" label="SAVED" /> : null}
          <span className="mono small dim">{tpl.data?.path}{tpl.data && !tpl.data.custom ? "（未作成・既定を表示中）" : ""}</span>
          <button className="btn cyan sm" onClick={save}>保存</button>
        </div>
      </div>
      <p className="small muted" style={{ margin: 0 }}>
        すべての会話で共通に使う指示です。<code>{"{{CHARACTER}}"}</code> にキャラクター名、
        <code>{"{{PERSONA_EPISODE}}"}</code> にそのキャラクターのペルソナとエピソード（YAML を省略せず）、
        <code>{"{{USER}}"}</code>（任意）に「あなたについて」が入ります。
      </p>
      <textarea className="code" value={value} onChange={(e) => setText(e.target.value)} spellCheck={false} />
      {error ? <ErrorBox error={error} /> : null}
    </div>
  );
}
