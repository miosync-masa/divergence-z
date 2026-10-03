import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { useAsync } from "../../lib/hooks";
import { Empty, ErrorBox, Pill, Sticker } from "../../components/ui";
import type { ProjectCtx } from "../Project";

const LANGS = ["en", "zh", "ko", "fr", "es", "de", "ja"];

export function TranslateTab({ ctx }: { ctx: ProjectCtx }) {
  const { project, job } = ctx;
  const [lang, setLang] = useState("en");
  const [chapter, setChapter] = useState<string | null>(null);
  const [view, setView] = useState<"text" | "notes">("text");
  const list = useAsync(() => api.translations(project.id, lang), [project.id, lang, job.status]);
  const seg = useAsync(() => (chapter ? api.chapter(project.id, lang, chapter) : Promise.resolve(null)),
    [project.id, lang, chapter, job.status]);
  const notes = useAsync(() => api.notes(project.id, lang), [project.id, lang, job.status]);
  const busy = job.status === "queued" || job.status === "running";

  const chapters = list.data?.chapters || [];
  // 開いたときは訳し済みの最初の章を表示する
  useEffect(() => {
    if (!chapter && chapters.length) setChapter((chapters.find((c) => c.status === "done") || chapters[0]).chapter);
  }, [chapters.length]);
  const done = chapters.filter((c) => c.status === "done").length;
  const idx = chapter ? chapters.findIndex((c) => c.chapter === chapter) : -1;

  return (
    <div className="grid" style={{ gridTemplateColumns: "280px 1fr", alignItems: "start" }}>
      <div className="card flat stack" style={{ position: "sticky", top: 0 }}>
        <div className="row between">
          <Sticker color="lime">{lang.toUpperCase()}</Sticker>
          <span className="mono small">{done} / {chapters.length}</span>
        </div>
        <select value={lang} onChange={(e) => { setLang(e.target.value); setChapter(null); }}>
          {LANGS.map((l) => <option key={l}>{l}</option>)}
        </select>
        <div className="stack" style={{ gap: 4, maxHeight: 520, overflow: "auto" }}>
          {chapters.map((c) => (
            <button key={c.chapter} className={`chip${chapter === c.chapter ? " on" : ""}`}
                    style={{ justifyContent: "space-between", width: "100%", padding: "6px 10px" }}
                    onClick={() => { setChapter(c.chapter); setView("text"); }}>
              <span>{c.chapter}</span>
              <Pill status={c.status} />
            </button>
          ))}
        </div>
        <button className="btn sm" disabled={busy || !chapters.length} onClick={() => ctx.run("translate", { lang })}>
          未翻訳の章をすべて訳す
        </button>
        <button className={`btn sm ${view === "notes" ? "cyan" : "ghost"}`} onClick={() => setView("notes")}>訳語表</button>
      </div>

      <div className="stack">
        {view === "notes" ? (
          <div className="card">
            <div className="card-head"><div className="row"><Sticker>GLOSSARY</Sticker><h2>訳語表</h2></div><span className="dim small">章ごとに追記され、次の章へ引き継がれます</span></div>
            {notes.error ? <ErrorBox error={notes.error} /> : null}
            {!notes.data?.yaml ? <Empty title="EMPTY">まだ訳語の決定はありません</Empty> : (
              <>
                <h3 style={{ marginBottom: 8 }}>用語</h3>
                <table className="t">
                  <thead><tr><th>SOURCE</th><th>TARGET</th><th>NOTE</th><th>SINCE</th></tr></thead>
                  <tbody>
                    {(notes.data.data?.glossary || []).map((g: any, i: number) => (
                      <tr key={i}><td><b>{g.source}</b></td><td style={{ color: "var(--cyan)" }}>{g.target}</td><td className="small muted">{g.note}</td><td className="mono small dim">{g.since}</td></tr>
                    ))}
                  </tbody>
                </table>
                <h3 style={{ margin: "18px 0 8px" }}>人物の声</h3>
                <table className="t">
                  <tbody>
                    {(notes.data.data?.voice || []).map((v: any, i: number) => (
                      <tr key={i}><td style={{ width: 180 }}><b>{v.character}</b><div className="small dim">{v.aspect}</div></td><td className="small">{v.decision}</td></tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>
        ) : !chapter ? (
          <div className="card"><Empty title="SELECT">左から章を選ぶと、原文と訳文を並べて表示します</Empty></div>
        ) : (
          <div className="card">
            <div className="card-head">
              <div className="row"><Sticker color="pink">BITEXT</Sticker><h2>{chapter}</h2></div>
              <div className="row">
                <button className="btn ghost sm" disabled={idx <= 0} onClick={() => setChapter(chapters[idx - 1].chapter)}>←</button>
                <button className="btn ghost sm" disabled={idx < 0 || idx >= chapters.length - 1} onClick={() => setChapter(chapters[idx + 1].chapter)}>→</button>
                <button className="btn sm cyan" disabled={busy} onClick={() => ctx.run("translate", { lang, chapters: String(idx), force: true })}>
                  この章を{seg.data ? "再" : ""}翻訳
                </button>
              </div>
            </div>
            {seg.error ? <Empty title="NOT YET">この章はまだ訳されていません</Empty> : null}
            {seg.data ? (
              <div className="bitext">
                {seg.data.segments.map((s) => (
                  <div className="seg" key={s.id}>
                    <div><span className="sid">{s.id}</span>{s.source}</div>
                    <div><span className="sid">{s.id}</span>{s.target || <span style={{ color: "var(--red)" }}>[missing]</span>}</div>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}
