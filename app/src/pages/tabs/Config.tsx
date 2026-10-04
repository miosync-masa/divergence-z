import { useState } from "react";
import { api, STEPS, StepName } from "../../lib/api";
import { useAsync } from "../../lib/hooks";
import { ErrorBox, Pill, Sticker } from "../../components/ui";
import type { ProjectCtx } from "../Project";

const STEP_LABEL: Record<StepName, string> = {
  cast: "人物表", persona: "ペルソナ", episode: "エピソード", translate: "翻訳", localize: "ローカライズ", voice: "ボイス", generate: "Web 生成",
};

export function ConfigTab({ ctx }: { ctx: ProjectCtx }) {
  const { project } = ctx;
  const models = useAsync(api.models, []);
  const [cfg, setCfg] = useState({
    name: project.name, work: project.work, source: project.source,
    output_lang: project.output_lang, review_cast: project.review_cast,
    models: structuredClone(project.models),
  });
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setError(null);
    try {
      await api.patchProject(project.id, cfg);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
      ctx.reload();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const specOf = (id: string) => models.data?.find((m) => m.id === id);

  return (
    <>
      <div className="card">
        <div className="card-head">
          <div className="row"><Sticker>PROJECT</Sticker><h2>プロジェクト</h2></div>
          {saved ? <Pill status="done" label="SAVED" /> : null}
        </div>
        <div className="grid c2">
          <label className="field">プロジェクト名<input value={cfg.name} onChange={(e) => setCfg({ ...cfg, name: e.target.value })} /></label>
          <label className="field">作品名<input value={cfg.work} onChange={(e) => setCfg({ ...cfg, work: e.target.value })} /></label>
          <label className="field">原稿フォルダ
            <div className="row" style={{ flexWrap: "nowrap" }}>
              <input value={cfg.source} onChange={(e) => setCfg({ ...cfg, source: e.target.value })} />
              <button className="btn sm yellow" onClick={async () => {
                const s = await window.dz.pickFolder("原稿フォルダを選ぶ");
                if (s) setCfg({ ...cfg, source: s });
              }}>選ぶ</button>
            </div>
          </label>
          <label className="field">資料の説明文の言語
            <select value={cfg.output_lang} onChange={(e) => setCfg({ ...cfg, output_lang: e.target.value })}>
              {["ja", "en", "zh", "ko", "fr", "es", "de"].map((l) => <option key={l}>{l}</option>)}
            </select>
          </label>
        </div>
      </div>

      <div className="card cool">
        <div className="card-head">
          <div className="row"><Sticker color="cyan">MODELS</Sticker><h2>ステップごとのモデル</h2></div>
          <span className="small dim">重い抽出は大きいモデル、試し訳は軽いモデル、のように使い分けられます</span>
        </div>
        <table className="t">
          <thead><tr><th>STEP</th><th>MODEL</th><th>EFFORT</th><th>CONTEXT</th><th>$ / 1M</th></tr></thead>
          <tbody>
            {STEPS.map((step) => {
              const cur = cfg.models[step] || { model: "" };
              const spec = specOf(cur.model);
              return (
                <tr key={step}>
                  <td><b>{STEP_LABEL[step]}</b><div className="mono small dim">{step}</div></td>
                  <td>
                    <select value={cur.model} onChange={(e) => {
                      const s = specOf(e.target.value);
                      setCfg({ ...cfg, models: { ...cfg.models, [step]: { model: e.target.value, effort: s?.default_effort || undefined } } });
                    }}>
                      {models.data?.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
                    </select>
                  </td>
                  <td>
                    <select value={cur.effort || ""} disabled={!spec?.efforts.length}
                            onChange={(e) => setCfg({ ...cfg, models: { ...cfg.models, [step]: { ...cur, effort: e.target.value } } })}>
                      {(spec?.efforts || []).map((ef) => <option key={ef}>{ef}</option>)}
                    </select>
                  </td>
                  <td className="mono small">{spec?.context_window ? spec.context_window.toLocaleString() : "?"}</td>
                  <td className="mono small">{spec?.price_in != null ? `$${spec.price_in} / $${spec.price_out}` : "?"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="row">
        <label className="row small" style={{ gap: 8 }}>
          <input type="checkbox" checked={cfg.review_cast} onChange={(e) => setCfg({ ...cfg, review_cast: e.target.checked })} />
          パイプラインで人物表の確認待ちを挟む（既定）
        </label>
        <span className="spacer" />
        <button className="btn big" onClick={save}>保存</button>
      </div>
      {error ? <ErrorBox error={error} /> : null}
    </>
  );
}
