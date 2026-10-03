import { useState } from "react";
import { api } from "../../lib/api";
import { go, useAsync } from "../../lib/hooks";
import { ErrorBox, EstimateTable, JobConsole, Pill, Sticker } from "../../components/ui";
import type { ProjectCtx } from "../Project";

const TARGET_LANGS = ["en", "zh", "ko", "fr", "es", "de", "ja"];

export function PipelineTab({ ctx }: { ctx: ProjectCtx }) {
  const { project, job } = ctx;
  const cast = useAsync(() => api.cast(project.id).catch(() => null), [project.id, job.status]);
  const characters: { label: string; importance: string }[] =
    (cast.data?.data?.characters || []).map((c: any) => ({ label: c.label, importance: c.importance }));
  const mains = characters.filter((c) => c.importance === "main").map((c) => c.label);

  const [selected, setSelected] = useState<string[] | null>(null);
  const [showMinor, setShowMinor] = useState(false);
  const chosen = selected ?? mains;
  const [langs, setLangs] = useState<string[]>(["en"]);
  const [review, setReview] = useState(project.review_cast);
  const [estimate, setEstimate] = useState<Awaited<ReturnType<typeof api.estimate>> | null>(null);
  const [estimating, setEstimating] = useState(false);
  const [estError, setEstError] = useState<string | null>(null);

  const tr = useAsync(() => (langs[0] ? api.translations(project.id, langs[0]) : Promise.resolve(null)),
    [project.id, langs[0], job.status]);

  const status = project.status;
  const personaDone = chosen.filter((l) => status?.personas[l]).length;
  const episodeDone = chosen.filter((l) => status?.episodes[l]).length;
  const chapters = tr.data?.chapters || [];
  const chDone = chapters.filter((c) => c.status === "done").length;
  const busy = job.status === "queued" || job.status === "running" || job.status === "awaiting_review";

  const toggle = (list: string[], v: string) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

  const runEstimate = async () => {
    setEstimating(true);
    setEstError(null);
    try {
      setEstimate(await api.estimate(project.id, {
        steps: [...(status?.cast ? [] : ["cast"]), "persona", "episode", "translate"],
        characters: chosen,
        langs,
      }));
    } catch (e: any) {
      setEstError(e.message);
    } finally {
      setEstimating(false);
    }
  };

  const steps = [
    { n: "01", key: "cast", title: "CAST", jp: "人物表", done: status?.cast ? 1 : 0, total: 1,
      note: "誰がいて、本文でどう呼ばれているか", run: () => ctx.run("cast") },
    { n: "02", key: "persona", title: "PERSONA", jp: "ペルソナ", done: personaDone, total: chosen.length,
      note: "この人は誰か（話し方・核・葛藤）", run: () => ctx.run("persona", { characters: chosen }) },
    { n: "03", key: "episode", title: "EPISODE", jp: "エピソード", done: episodeDone, total: chosen.length,
      note: "この人は何を経験したか（原文照合つき）", run: () => ctx.run("episode", { characters: chosen }) },
    { n: "04", key: "translate", title: "TRANSLATE", jp: `翻訳 ${langs[0] ?? ""}`, done: chDone, total: chapters.length,
      note: "章ごとに資料＋訳語表＋前章を渡して翻訳", run: () => ctx.run("translate", { lang: langs[0] }) },
  ];

  return (
    <>
      {!project.source ? (
        <div className="banner cyan">
          <span className="mono">NO SOURCE</span>
          <span>原稿フォルダが未設定です。抽出と翻訳には原稿が必要です（Web 生成とボイスはこのまま使えます）。</span>
          <span className="spacer" />
          <button className="btn sm yellow" onClick={() => go("p", project.id, "config")}>設定タブで指定する</button>
          <button className="btn sm ghost" onClick={() => go("p", project.id, "generate")}>Web 生成へ</button>
        </div>
      ) : null}
      <div className="grid c4">
        {steps.map((s) => {
          const complete = s.total > 0 && s.done >= s.total;
          const active = busy && (ctx.jobType === s.key || (ctx.jobType === "pipeline" && job.progress?.step === s.key));
          return (
            <div key={s.key} className={`card step${active ? " cool" : complete ? "" : ""}`}>
              <div className="row between">
                <span className="num">{s.n}</span>
                {active ? <Pill status="running" /> : complete ? <Pill status="done" /> : <Pill status="pending" label="todo" />}
              </div>
              <div>
                <div className="mono small dim">{s.title}</div>
                <h3>{s.jp}</h3>
              </div>
              <div className="count">{s.done}<small> / {s.total || "—"}</small></div>
              <div className="small muted" style={{ flex: 1 }}>{s.note}</div>
              <button className="btn sm ghost" disabled={busy || (s.key !== "cast" && !status?.cast && chosen.length === 0)} onClick={s.run}>
                このステップだけ実行
              </button>
            </div>
          );
        })}
      </div>

      <div className="card hot">
        <div className="card-head">
          <div className="row"><Sticker color="pink">RUN</Sticker><h2>一気通貫で実行</h2></div>
          <span className="small dim">作成済みの資料・訳済みの章はスキップ（中断しても再実行で続きから）</span>
        </div>
        <div className="grid c2">
          <div className="stack">
            <h3>対象キャラクター</h3>
            {characters.length ? (
              <div className="row" style={{ gap: 8 }}>
                {characters.filter((c) => showMinor || c.importance !== "minor" || chosen.includes(c.label)).map((c) => (
                  <button key={c.label} className={`chip${chosen.includes(c.label) ? " on" : ""}`}
                          onClick={() => setSelected(toggle(chosen, c.label))}>
                    {c.label}{c.importance === "main" ? " ★" : ""}
                  </button>
                ))}
                {characters.some((c) => c.importance === "minor") ? (
                  <button className="chip" style={{ borderStyle: "dashed" }} onClick={() => setShowMinor(!showMinor)}>
                    {showMinor ? "端役を隠す" : `+ 端役 ${characters.filter((c) => c.importance === "minor").length}人`}
                  </button>
                ) : null}
              </div>
            ) : (
              <span className="small muted">人物表ができると選べます（未指定なら人物表の main を自動で対象にします）</span>
            )}
          </div>
          <div className="stack">
            <h3>翻訳先の言語</h3>
            <div className="row" style={{ gap: 8 }}>
              {TARGET_LANGS.map((l) => (
                <button key={l} className={`chip${langs.includes(l) ? " on" : ""}`} onClick={() => setLangs(toggle(langs, l))}>{l}</button>
              ))}
            </div>
            <label className="row small" style={{ gap: 8 }}>
              <input type="checkbox" checked={review} onChange={(e) => setReview(e.target.checked)} />
              人物表ができたら一度止めて確認する
            </label>
          </div>
        </div>
        <div className="row" style={{ marginTop: 20 }}>
          <button className="btn yellow" onClick={runEstimate} disabled={estimating}>{estimating ? "計算中…" : "$ 見積もる"}</button>
          <button className="btn big" disabled={busy}
                  onClick={() => ctx.run("pipeline", { characters: selected ?? undefined, translate_langs: langs, review_cast: review })}>
            ▶ パイプライン実行
          </button>
        </div>
        {estError ? <div style={{ marginTop: 14 }}><ErrorBox error={estError} /></div> : null}
        {estimate ? <div style={{ marginTop: 20 }}><EstimateTable rows={estimate.rows} total={estimate.total_cost_usd} allFit={estimate.all_fit} /></div> : null}
      </div>

      {job.review ? (
        <div className="banner">
          <span className="mono">REVIEW</span>
          <span>人物表ができました。名前の付け方や同一人物の判定を確認してから続行してください。</span>
          <span className="spacer" />
          <button className="btn sm cyan" onClick={() => go("p", project.id, "cast")}>人物表を開く</button>
          <button className="btn sm lime" onClick={ctx.resume}>OK、続ける ▶</button>
        </div>
      ) : null}

      {ctx.jobId ? <JobConsole job={job} title={ctx.jobType ?? ""} onCancel={ctx.cancel} /> : null}
    </>
  );
}
