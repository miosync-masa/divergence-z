import { useState } from "react";
import { api, KeyStatus } from "../lib/api";
import { go, useAsync } from "../lib/hooks";
import { Empty, ErrorBox, Glitch, Sticker } from "../components/ui";

const LANGS = ["ja", "en", "zh", "ko", "fr", "es", "de"];

export function ProjectsPage({ keys }: { keys: KeyStatus | null }) {
  const { data: projects, error, reload } = useAsync(api.projects, []);
  const [form, setForm] = useState<null | { root: string; source: string; name: string; work: string; output_lang: string }>(null);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const openExisting = async () => {
    const root = await window.dz.pickFolder("既存のプロジェクト（または CLI の作業フォルダ）を選ぶ");
    if (!root) return;
    const p = await api.openProject({ root });
    go("p", p.id, "pipeline");
  };

  const startNew = async () => {
    const root = await window.dz.pickFolder("プロジェクトを保存するフォルダ（空のフォルダ推奨）");
    if (!root) return;
    setForm({ root, source: "", name: root.split("/").pop() || "", work: "", output_lang: "ja" });
  };

  const create = async () => {
    if (!form) return;
    setBusy(true);
    setFormError(null);
    try {
      const p = await api.openProject(form);
      go("p", p.id, "pipeline");
    } catch (e: any) {
      setFormError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const noKeys = keys && !keys.openai && !keys.anthropic;

  return (
    <div className="page">
      <section className="hero">
        <div className="stack" style={{ gap: 10 }}>
          <span className="eyebrow">character bible → translation → voice</span>
          <Glitch text="DIVERGENCE//Z" size={52} />
          <p className="muted" style={{ fontSize: 16, margin: 0 }}>
            原作から「誰が・何を経験したか」の資料を作り、<br />
            その資料で <b style={{ color: "var(--pink)" }}>翻訳</b> し、<b style={{ color: "var(--cyan)" }}>声</b> にする。
          </p>
        </div>
        <div className="card hot">
          <div className="flow">
            <Sticker>CAST</Sticker><span className="arrow">→</span>
            <Sticker color="pink">PERSONA</Sticker><span className="arrow">→</span>
            <Sticker color="cyan">EPISODE</Sticker><span className="arrow">→</span>
            <Sticker color="lime">TRANSLATE</Sticker><span className="arrow">+</span>
            <Sticker>VOICE</Sticker>
          </div>
          <div className="row" style={{ marginTop: 22 }}>
            <button className="btn big" onClick={startNew}>＋ 新しいプロジェクト</button>
            <button className="btn ghost" onClick={openExisting}>既存のプロジェクトを開く</button>
          </div>
          <p className="small dim" style={{ margin: "14px 0 0" }}>
            新規 = 資料と訳文の保存先（空のフォルダ）を選んで作成 ／ 既存 = 以前のプロジェクトや、CLI で
            casts・personas・episodes を作ったフォルダを登録（原稿フォルダは開いたあと設定タブで指定）
          </p>
        </div>
      </section>

      {noKeys ? (
        <div className="banner">
          <span className="mono">BYOK</span>
          <span>API キーがまだありません。</span>
          <span className="spacer" />
          <button className="btn sm cyan" onClick={() => go("settings")}>キーを設定する →</button>
        </div>
      ) : null}

      {form ? (
        <div className="card cool">
          <div className="card-head">
            <div className="row"><Sticker color="cyan">NEW</Sticker><h2>プロジェクトを作る</h2></div>
            <button className="btn ghost sm" onClick={() => setForm(null)}>閉じる</button>
          </div>
          <div className="grid c2">
            <label className="field">保存先フォルダ
              <input value={form.root} readOnly />
            </label>
            <label className="field">原稿フォルダ（章ごとのテキスト / PDF / EPUB。Web 生成だけなら空でも可）
              <div className="row" style={{ flexWrap: "nowrap" }}>
                <input value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })} placeholder="未選択" />
                <button className="btn sm yellow" onClick={async () => {
                  const s = await window.dz.pickFolder("原稿フォルダを選ぶ");
                  if (s) setForm({ ...form, source: s });
                }}>選ぶ</button>
              </div>
            </label>
            <label className="field">プロジェクト名
              <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </label>
            <label className="field">作品名
              <input value={form.work} onChange={(e) => setForm({ ...form, work: e.target.value })} placeholder="例: STARGAZER ≠consciousness" />
            </label>
            <label className="field">資料の説明文の言語
              <select value={form.output_lang} onChange={(e) => setForm({ ...form, output_lang: e.target.value })}>
                {LANGS.map((l) => <option key={l}>{l}</option>)}
              </select>
            </label>
          </div>
          <div className="row" style={{ marginTop: 18 }}>
            <button className="btn" disabled={busy || !form.root} onClick={create}>作成して開く →</button>
            {formError ? <ErrorBox error={formError} /> : null}
          </div>
        </div>
      ) : null}

      <section className="stack">
        <div className="row">
          <h2>PROJECTS</h2>
          <span className="dim mono small">{projects?.length ?? 0}</span>
          <span className="spacer" />
          <button className="btn ghost sm" onClick={reload}>↻</button>
        </div>
        {error ? <ErrorBox error={error} /> : null}
        {projects && projects.length === 0 ? (
          <Empty title="NO PROJECT">新しいプロジェクトを作るか、CLI で作ったフォルダを開いてください</Empty>
        ) : null}
        <div className="grid c3">
          {projects?.map((p) => (
            <div key={p.id} className="card pcard" onClick={() => go("p", p.id, "pipeline")}>
              <div className="stack" style={{ gap: 8 }}>
                <div className="row between">
                  <h2>{p.name}</h2>
                  <Sticker color="pink">{p.output_lang.toUpperCase()}</Sticker>
                </div>
                <div className="muted">{p.work || "—"}</div>
                <div className="path">{p.root}</div>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
