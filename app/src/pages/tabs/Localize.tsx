import { useEffect, useMemo, useState } from "react";
import { api, Ledger, LocalizeAction, LocalizeEdit } from "../../lib/api";
import { useAsync } from "../../lib/hooks";
import { Empty, ErrorBox, Sticker } from "../../components/ui";
import type { ProjectCtx } from "../Project";

const LANGS = ["en", "zh", "ko", "fr", "es", "de", "ja"];

const actionOf = (v: any): LocalizeAction => (typeof v === "string" ? v : v?.action) || "keep";

// 修正の種類ごとの色。緩和（強度を下げる）は目立たせる
const LEVEL_COLOR: Record<string, string> = { L1: "var(--dim)", L2: "var(--cyan)", L3: "var(--lime)", "緩和": "var(--pink)" };

export function LocalizeTab({ ctx }: { ctx: ProjectCtx }) {
  const { project, job } = ctx;
  const [lang, setLang] = useState("en");
  const [selected, setSelected] = useState<string[]>([]);              // 選んだ順（後ろが優先）
  const [overrides, setOverrides] = useState<Record<string, LocalizeAction>>({});
  const [name, setName] = useState("");
  const [force, setForce] = useState(false);
  const [variant, setVariant] = useState<string | null>(null);
  const [chapter, setChapter] = useState<string | null>(null);
  const [view, setView] = useState<"edits" | "text" | "diagnosis">("edits");
  const [ledger, setLedger] = useState<Ledger | null>(null);
  const [error, setError] = useState<string | null>(null);
  const busy = job.status === "queued" || job.status === "running";

  const meta = useAsync(() => api.localizePresets(project.id), [project.id]);
  const variants = useAsync(() => api.localizations(project.id, lang), [project.id, lang, job.status]);
  const l0 = useAsync(() => api.translations(project.id, lang), [project.id, lang, job.status]);
  const l0Done = (l0.data?.chapters || []).filter((c) => c.status === "done").length;

  const presets = meta.data?.presets || [];
  const domains = meta.data?.domains || [];
  const actions = meta.data?.actions || [];

  // プリセットを選んだ順に重ね、手動の調整を最後に重ねる（サーバーと同じ規則）
  const merged = useMemo(() => {
    const out: Record<string, LocalizeAction> = {};
    for (const id of selected) {
      const p = presets.find((x) => x.id === id);
      for (const [d, v] of Object.entries(p?.domains || {})) out[d] = actionOf(v);
    }
    return out;
  }, [selected, presets]);
  const effective = (d: string): LocalizeAction => overrides[d] ?? merged[d] ?? "keep";
  const active = domains.filter((d) => effective(d.id) !== "keep");
  const defaultName = [...selected, ...(Object.keys(overrides).length ? ["custom"] : [])].join("+") || "custom";

  const toggle = (id: string) =>
    setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));

  // ジョブが終わったら、そのバリアントを開く
  useEffect(() => {
    if (job.status === "succeeded" && job.result?.variant) {
      setVariant(job.result.variant);
      const first = job.result.chapters?.find((c: any) => !c.skipped) || job.result.chapters?.[0];
      if (first) setChapter(first.chapter);
    }
  }, [job.status]);

  const current = variants.data?.find((v) => v.variant === variant) || null;
  useEffect(() => {
    if (!variant && variants.data?.length) setVariant(variants.data[0].variant);
  }, [variants.data]);
  useEffect(() => {
    if (current && (!chapter || !current.chapters.some((c) => c.chapter === chapter))) {
      setChapter(current.chapters[0]?.chapter || null);
    }
  }, [current?.variant, current?.chapters.length]);

  useEffect(() => {
    setLedger(null);
    if (!variant || !chapter) return;
    api.ledger(project.id, lang, variant, chapter).then(setLedger).catch((e) => setError(e.message));
  }, [project.id, lang, variant, chapter, job.status]);

  const run = () => {
    const domainsOverride = Object.fromEntries(Object.entries(overrides).map(([d, a]) => [d, { action: a }]));
    ctx.run("localize", { lang, presets: selected, domains: domainsOverride, variant: name || defaultName, force });
  };

  const setStatus = async (e: LocalizeEdit, status: "applied" | "reverted") => {
    if (!variant || !chapter) return;
    setError(null);
    try {
      setLedger(await api.setEdit(project.id, lang, variant, chapter, e.id, status));
      variants.reload();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const label = (d?: string) => domains.find((x) => x.id === d)?.label || d || "";

  return (
    <div className="grid" style={{ gridTemplateColumns: "340px 1fr", alignItems: "start" }}>
      <div className="stack">
        <div className="card flat stack">
          <div className="row between">
            <Sticker color="lime">LOCALIZE</Sticker>
            <span className="mono small">L0 {l0Done} 章</span>
          </div>
          <select value={lang} onChange={(e) => { setLang(e.target.value); setVariant(null); setChapter(null); }}>
            {LANGS.map((l) => <option key={l}>{l}</option>)}
          </select>
          <div className="small muted">訳し上がった訳文（L0）はそのまま残し、調整した版を別に作ります。</div>

          <h3 style={{ margin: "6px 0 0" }}>宗教・性表現などを調整しますか？</h3>
          {meta.error ? <ErrorBox error={meta.error} /> : null}
          <div className="stack" style={{ gap: 6 }}>
            {presets.map((p) => (
              <label key={p.id} className="row small" style={{ gap: 8, alignItems: "flex-start", cursor: "pointer" }}>
                <input type="checkbox" checked={selected.includes(p.id)} onChange={() => toggle(p.id)} style={{ marginTop: 3 }} />
                <span className="stack" style={{ gap: 2 }}>
                  <b>{p.name}{p.origin === "project" ? <span className="dim mono"> · project</span> : null}</b>
                  {p.description ? <span className="dim">{p.description}</span> : null}
                </span>
              </label>
            ))}
          </div>

          <details open={Object.keys(overrides).length > 0}>
            <summary className="small" style={{ cursor: "pointer" }}>領域ごとに微調整</summary>
            <table className="t" style={{ marginTop: 6 }}>
              <tbody>
                {domains.map((d) => (
                  <tr key={d.id}>
                    <td title={d.scope}><b className="small">{d.label}</b></td>
                    <td>
                      <select value={effective(d.id)} style={{ color: overrides[d.id] ? "var(--yellow)" : undefined }}
                              onChange={(e) => {
                                const a = e.target.value as LocalizeAction;
                                setOverrides((o) => {
                                  const next = { ...o };
                                  if (a === (merged[d.id] ?? "keep")) delete next[d.id]; else next[d.id] = a;
                                  return next;
                                });
                              }}>
                        {actions.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>

          <input placeholder={`版の名前（${defaultName}）`} value={name} onChange={(e) => setName(e.target.value)} />
          <label className="row small" style={{ gap: 8 }}>
            <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} />
            作成済みの章も作り直す
          </label>
          <button className="btn" disabled={busy || !active.length || !l0Done} onClick={run}>
            {active.length ? `${active.length} 領域を調整する` : "領域を選んでください"}
          </button>
        </div>

        {variants.data?.length ? (
          <div className="card flat stack">
            <h3 style={{ margin: 0 }}>作成済みの版</h3>
            <div className="row" style={{ flexWrap: "wrap", gap: 6 }}>
              {variants.data.map((v) => (
                <button key={v.variant} className={`chip${variant === v.variant ? " on" : ""}`} onClick={() => { setVariant(v.variant); setChapter(null); }}>
                  {lang}@{v.variant}
                </button>
              ))}
            </div>
            <div className="stack" style={{ gap: 4, maxHeight: 360, overflow: "auto" }}>
              {current?.chapters.map((c) => (
                <button key={c.chapter} className={`chip${chapter === c.chapter ? " on" : ""}`}
                        style={{ justifyContent: "space-between", width: "100%", padding: "6px 10px" }}
                        onClick={() => setChapter(c.chapter)}>
                  <span>{c.chapter}</span>
                  <span className="mono small">✏️{c.applied}{c.reverted ? ` ↩${c.reverted}` : ""} 🩺{c.diagnoses}</span>
                </button>
              ))}
            </div>
            <button className="btn ghost sm" onClick={() => window.dz.reveal(`${project.root}/${current?.path || ""}`)}>フォルダを表示</button>
          </div>
        ) : null}
      </div>

      <div className="stack">
        {error ? <ErrorBox error={error} /> : null}
        {!ledger ? (
          <div className="card">
            <Empty title={variants.data?.length ? "SELECT" : "NO VARIANT"}>
              {variants.data?.length ? "左から章を選ぶと、変更の一覧を表示します"
                : "プリセットを選んで実行すると、調整した版ができます。変更はすべて一覧に残り、1件ずつ戻せます"}
            </Empty>
          </div>
        ) : (
          <div className="card">
            <div className="card-head">
              <div className="row"><Sticker color="pink">{ledger.policy.name}</Sticker><h2>{ledger.chapter}</h2></div>
              <div className="row">
                {(["edits", "text", "diagnosis"] as const).map((v) => (
                  <button key={v} className={`btn sm ${view === v ? "cyan" : "ghost"}`} onClick={() => setView(v)}>
                    {v === "edits" ? `変更 ${ledger.edits.filter((e) => e.status !== "rejected").length}` :
                     v === "text" ? "本文" : `診断 ${ledger.diagnoses.length}`}
                  </button>
                ))}
              </div>
            </div>
            {ledger.errors?.length ? <ErrorBox error={ledger.errors.join(" / ")} /> : null}
            {view === "edits" ? <EditList ledger={ledger} label={label} onSet={setStatus} /> : null}
            {view === "text" ? <AnnotatedText ledger={ledger} label={label} /> : null}
            {view === "diagnosis" ? (
              ledger.diagnoses.length ? (
                <table className="t">
                  <thead><tr><th>SEG</th><th>領域</th><th>指摘（本文は変えていません）</th></tr></thead>
                  <tbody>
                    {ledger.diagnoses.map((d, i) => (
                      <tr key={i}><td className="mono small">{d.seg}</td><td className="small">{label(d.domain)}</td><td className="small">{d.note}</td></tr>
                    ))}
                  </tbody>
                </table>
              ) : <Empty title="CLEAR">指摘はありません</Empty>
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}

function EditList({ ledger, label, onSet }: { ledger: Ledger; label: (d?: string) => string;
                                              onSet: (e: LocalizeEdit, s: "applied" | "reverted") => void }) {
  if (!ledger.edits.length) return <Empty title="NO EDITS">この章に変更はありません</Empty>;
  return (
    <table className="t">
      <thead><tr><th>SEG</th><th>種類</th><th>L0 → 調整後</th><th></th></tr></thead>
      <tbody>
        {ledger.edits.map((e) => (
          <tr key={e.id} style={{ opacity: e.status === "applied" ? 1 : 0.55 }}>
            <td className="mono small">{e.seg}<div className="dim">{e.id}</div></td>
            <td className="small">
              <b style={{ color: LEVEL_COLOR[e.level] || "var(--yellow)" }}>{e.level}</b>
              <div>{label(e.domain)}</div>
            </td>
            <td className="small">
              <span style={{ textDecoration: e.status === "applied" ? "line-through" : undefined }} className="dim">{e.before}</span>
              {" → "}
              <span style={{ color: "var(--cyan)", textDecoration: e.status !== "applied" ? "line-through" : undefined }}>{e.after}</span>
              {e.note ? <div className="dim">{e.note}</div> : null}
              {e.status === "rejected" ? <div style={{ color: "var(--red)" }}>適用せず: {e.reason}</div> : null}
            </td>
            <td>
              {e.status === "applied" ? <button className="btn ghost sm" onClick={() => onSet(e, "reverted")}>↩ 戻す</button> : null}
              {e.status === "reverted" ? <button className="btn sm" onClick={() => onSet(e, "applied")}>再適用</button> : null}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** 段落ごとに、適用中の修正を色付きで表示する（変更のある段落だけ） */
function AnnotatedText({ ledger, label }: { ledger: Ledger; label: (d?: string) => string }) {
  const bySeg: Record<string, LocalizeEdit[]> = {};
  for (const e of ledger.edits) {
    if (e.status === "applied" && e.pos != null) (bySeg[e.seg] ||= []).push(e);
  }
  const changed = ledger.segments.filter((s) => bySeg[s.id]);
  if (!changed.length) return <Empty title="UNCHANGED">適用中の変更はありません（本文は L0 のまま）</Empty>;
  return (
    <div className="bitext">
      {changed.map((s) => {
        const parts: (string | JSX.Element)[] = [];
        let at = 0;
        for (const e of [...bySeg[s.id]].sort((a, b) => a.pos! - b.pos!)) {
          parts.push(s.target.slice(at, e.pos));
          parts.push(
            <mark key={e.id} title={`${e.level}・${label(e.domain)}: ${e.before}`}
                  style={{ background: "transparent", color: LEVEL_COLOR[e.level] || "var(--yellow)", borderBottom: "1.5px dashed currentColor" }}>
              {e.after}
            </mark>);
          at = e.pos! + e.before.length;
        }
        parts.push(s.target.slice(at));
        return (
          <div className="seg" key={s.id}>
            <div><span className="sid">{s.id}</span>{s.target}</div>
            <div><span className="sid">{s.id}</span>{parts}</div>
          </div>
        );
      })}
    </div>
  );
}
