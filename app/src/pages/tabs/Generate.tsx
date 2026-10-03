import { useEffect, useMemo, useState } from "react";
import { api } from "../../lib/api";
import { useAsync } from "../../lib/hooks";
import { ErrorBox, Pill, Sticker } from "../../components/ui";
import type { ProjectCtx } from "../Project";

const LANGS = ["ja", "en", "zh", "ko", "fr", "es", "de"];

// 原作テキストが無い作品でも、キャラ名と作品名から Web 検索で persona / episode を作る
// （persona_generator.py → episode_generator.py）
export function GenerateTab({ ctx }: { ctx: ProjectCtx }) {
  const { project, job } = ctx;
  const models = useAsync(api.models, []);
  const cast = useAsync(() => api.cast(project.id).catch(() => null), [project.id]);
  const personas = useAsync(() => api.personas(project.id), [project.id, job.status]);
  const episodes = useAsync(() => api.episodes(project.id), [project.id, job.status]);
  const labels: string[] = (cast.data?.data?.characters || []).map((c: any) => c.label);

  const [name, setName] = useState("");
  const [work, setWork] = useState(project.work || project.name);
  const [desc, setDesc] = useState("");
  const [lang, setLang] = useState(project.output_lang || "ja");
  const [webSearch, setWebSearch] = useState(true);
  const [makePersona, setMakePersona] = useState(true);
  const [makeEpisodes, setMakeEpisodes] = useState(true);
  const [sequel, setSequel] = useState(false);
  const [maxEpisodes, setMaxEpisodes] = useState(20);
  const [force, setForce] = useState(false);
  const [model, setModel] = useState("");
  const [effort, setEffort] = useState("");

  // Web 検索をするなら、検索に対応したモデルだけを選べるようにする
  const choices = useMemo(
    () => (models.data || []).filter((m) => !webSearch || m.web_search),
    [models.data, webSearch],
  );
  useEffect(() => {
    if (!choices.length) return;
    const preferred = project.models.generate?.model;
    const pick = choices.find((m) => m.id === model) || choices.find((m) => m.id === preferred) || choices[0];
    if (pick.id !== model) {
      setModel(pick.id);
      setEffort((pick.id === preferred && project.models.generate?.effort) || pick.default_effort || "");
    }
  }, [choices]);
  const spec = choices.find((m) => m.id === model);

  const busy = job.status === "queued" || job.status === "running";
  const mine = ctx.jobType === "generate_character" ? job : null;
  const res = mine?.result;
  const inCast = name && labels.includes(name);

  const run = () =>
    ctx.run("generate_character", {
      name, source: work, desc, lang, web_search: webSearch,
      persona: makePersona, episodes: makeEpisodes, sequel, max_episodes: maxEpisodes, force,
      models: { generate: { model, effort: effort || undefined } },
    });

  return (
    <div className="grid" style={{ gridTemplateColumns: "1.3fr 1fr", alignItems: "start" }}>
      <div className="card hot stack">
        <div className="row">
          <Sticker color="pink">WEB</Sticker>
          <h2>名前から資料を作る</h2>
        </div>
        <p className="small muted" style={{ margin: 0 }}>
          原作テキストが手元に無いキャラクターでも、Web 検索で公式設定・あらすじ・台詞を調べて
          ペルソナとエピソードを作ります。原文がある作品は「パイプライン」の抽出の方が正確です。
        </p>

        <div className="grid c2">
          <label className="field">キャラクター名
            <input list="dz-cast-labels" value={name} onChange={(e) => setName(e.target.value)} placeholder="例: 牧瀬紅莉栖" />
            <datalist id="dz-cast-labels">{labels.map((l) => <option key={l} value={l} />)}</datalist>
          </label>
          <label className="field">作品名
            <input value={work} onChange={(e) => setWork(e.target.value)} placeholder="例: Steins;Gate" />
          </label>
        </div>
        {name ? (
          <div className="small" style={{ color: inCast ? "var(--lime)" : "var(--yellow)" }}>
            {inCast
              ? "✓ 人物表のラベルと一致。翻訳ではこの資料がこの人物に使われます"
              : labels.length
                ? "人物表に無い名前です。翻訳で使うなら、人物表のラベルと同じ名前にしてください"
                : "人物表はまだありません（ボイスではそのまま使えます）"}
          </div>
        ) : null}
        <label className="field">説明（任意・同名キャラとの区別や、狙ってほしい時期など）
          <input value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="例: ツンデレの天才脳科学者。0ではなく無印の時点" />
        </label>

        <div className="grid c2">
          <label className="field">モデル{webSearch ? "（Web 検索対応のみ）" : ""}
            <select value={model} onChange={(e) => {
              const m = choices.find((x) => x.id === e.target.value);
              setModel(e.target.value);
              setEffort(m?.default_effort || "");
            }}>
              {choices.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
            </select>
          </label>
          <label className="field">推論の強さ
            <select value={effort} disabled={!spec?.efforts.length} onChange={(e) => setEffort(e.target.value)}>
              {(spec?.efforts || []).map((ef) => <option key={ef}>{ef}</option>)}
            </select>
          </label>
          <label className="field">資料の説明文の言語
            <select value={lang} onChange={(e) => setLang(e.target.value)}>
              {LANGS.map((l) => <option key={l}>{l}</option>)}
            </select>
          </label>
          <label className="field">エピソードの最大数
            <input type="number" min={5} max={30} value={maxEpisodes}
                   onChange={(e) => setMaxEpisodes(Math.max(5, Math.min(30, Number(e.target.value) || 20)))} />
          </label>
        </div>

        <div className="row" style={{ gap: 18 }}>
          <label className="row small" style={{ gap: 6 }}>
            <input type="checkbox" checked={makePersona} onChange={(e) => setMakePersona(e.target.checked)} />ペルソナ
          </label>
          <label className="row small" style={{ gap: 6 }}>
            <input type="checkbox" checked={makeEpisodes} onChange={(e) => setMakeEpisodes(e.target.checked)} />エピソード
          </label>
          <label className="row small" style={{ gap: 6 }}>
            <input type="checkbox" checked={webSearch} onChange={(e) => setWebSearch(e.target.checked)} />Web 検索する
          </label>
          <label className="row small" style={{ gap: 6 }}>
            <input type="checkbox" checked={sequel} onChange={(e) => setSequel(e.target.checked)} />続編・スピンオフも含める
          </label>
          <label className="row small" style={{ gap: 6 }}>
            <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} />既存を作り直す
          </label>
        </div>
        {!webSearch ? (
          <div className="small" style={{ color: "var(--yellow)" }}>
            Web 検索なしではモデルの知識だけで作るため、台詞が実在しない「それっぽい」ものになりやすくなります。
          </div>
        ) : null}

        <div className="row">
          <button className="btn big" disabled={busy || !name || !work || !model || (!makePersona && !makeEpisodes)}
                  onClick={run}>
            {busy && mine ? "作成中…" : "▶ 資料を作る"}
          </button>
          <span className="dim small mono">{model} · {effort || "—"}</span>
        </div>
        {ctx.runError ? <ErrorBox error={ctx.runError} /> : null}

        {res ? (
          <div className="card flat stack" style={{ marginTop: 6 }}>
            <div className="row"><Sticker color="lime">DONE</Sticker><b>{res.name}</b></div>
            {(["persona", "episodes"] as const).map((k) => res[k] ? (
              <div key={k} className="row small" style={{ gap: 10 }}>
                <span className="mono" style={{ width: 70 }}>{k}</span>
                {res[k].skipped ? <Pill status="pending" label="SKIPPED" /> :
                  res[k].valid ? <Pill status="done" label="VALID" /> : <Pill status="failed" label="ISSUES" />}
                <span className="mono dim">{res[k].path}</span>
                {res[k].searches != null ? <span className="dim">🔍 {res[k].searches}</span> : null}
                {res[k].count != null ? <span className="dim">{res[k].count} episodes</span> : null}
              </div>
            ) : null)}
          </div>
        ) : null}
      </div>

      <div className="card flat stack">
        <div className="row between">
          <div className="row"><Sticker>FILES</Sticker><h3>このプロジェクトの資料</h3></div>
          <button className="btn ghost sm" onClick={() => window.dz.reveal(project.root + "/personas")}>フォルダを表示</button>
        </div>
        <h3 className="small muted" style={{ margin: 0 }}>personas</h3>
        <div className="stack" style={{ gap: 4 }}>
          {(personas.data || []).map((f) => <span key={f} className="mono small">{f}</span>)}
          {personas.data && !personas.data.length ? <span className="dim small">—</span> : null}
        </div>
        <h3 className="small muted" style={{ margin: "8px 0 0" }}>episodes</h3>
        <div className="stack" style={{ gap: 4 }}>
          {(episodes.data || []).map((f) => <span key={f} className="mono small">{f}</span>)}
          {episodes.data && !episodes.data.length ? <span className="dim small">—</span> : null}
        </div>
      </div>
    </div>
  );
}
