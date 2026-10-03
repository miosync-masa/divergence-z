import { Fragment, useEffect, useState } from "react";
import { dump as dumpYaml } from "js-yaml";
import { api } from "../../lib/api";
import { useAsync } from "../../lib/hooks";
import { Empty, ErrorBox, Pill, Sticker } from "../../components/ui";
import type { ProjectCtx } from "../Project";

interface Character {
  label: string;
  id?: string;
  proper_names?: string[];
  references?: { expr: string; where?: string }[];
  role?: string;
  importance?: string;
  is_same_person_as_note?: string;
  disambiguation?: string;
  appears_in?: string[];
  [k: string]: any;
}

export function CastTab({ ctx }: { ctx: ProjectCtx }) {
  const { project } = ctx;
  const { data, error, reload } = useAsync(() => api.cast(project.id), [project.id, ctx.job.status]);
  const [doc, setDoc] = useState<any>(null);
  const [raw, setRaw] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [saveState, setSaveState] = useState<"idle" | "saved" | "error">("idle");
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    if (data) setDoc(structuredClone(data.data));
  }, [data]);

  if (error) {
    return (
      <div className="card">
        <Empty title="NO CAST">
          まだ人物表がありません。
          <div className="row" style={{ justifyContent: "center", marginTop: 14 }}>
            <button className="btn" onClick={() => ctx.run("cast")}>人物表を作る</button>
          </div>
        </Empty>
      </div>
    );
  }
  if (!doc) return <span className="mono dim">LOADING…</span>;

  const chars: Character[] = doc.characters || [];
  const update = (i: number, patch: Partial<Character>) => {
    const next = { ...doc, characters: chars.map((c, j) => (j === i ? { ...c, ...patch } : c)) };
    setDoc(next);
    setSaveState("idle");
  };

  const save = async (text?: string) => {
    setSaveError(null);
    try {
      const body = text ?? dumpYaml(doc, { lineWidth: 1000, noRefs: true });
      await api.putCast(project.id, body);
      setSaveState("saved");
      setRaw(null);
      reload();
      ctx.reload();
    } catch (e: any) {
      setSaveState("error");
      setSaveError(e.message);
    }
  };

  return (
    <>
      <div className="card">
        <div className="card-head">
          <div className="row">
            <Sticker>CAST</Sticker>
            <h2>人物表</h2>
            <span className="dim small mono">{data?.path}</span>
          </div>
          <div className="row">
            {saveState === "saved" ? <Pill status="done" label="SAVED" /> : null}
            <button className="btn ghost sm" onClick={() => setRaw(raw == null ? data?.yaml ?? "" : null)}>
              {raw == null ? "YAML を直接編集" : "表で編集"}
            </button>
            <button className="btn cyan sm" onClick={() => save(raw ?? undefined)}>保存</button>
          </div>
        </div>
        <p className="small muted" style={{ marginTop: 0 }}>
          ラベルが persona / episode のファイル名と翻訳時の呼び名になります。「彼女」「搭乗者」などの呼ばれ方と、
          同一人物の判定が正しいか確認してください。
        </p>
        {saveError ? <ErrorBox error={saveError} /> : null}

        {raw != null ? (
          <textarea className="code" value={raw} onChange={(e) => setRaw(e.target.value)} spellCheck={false} />
        ) : (
          <table className="t">
            <thead>
              <tr><th style={{ width: 210 }}>LABEL</th><th style={{ width: 170 }}>IMPORTANCE</th><th>REFERENCES</th><th style={{ width: 80 }}>FILES</th></tr>
            </thead>
            <tbody>
              {chars.map((c, i) => (
                <Fragment key={i}>
                  <tr onClick={() => setOpen(open === i ? null : i)} style={{ cursor: "pointer" }}>
                    <td onClick={(e) => e.stopPropagation()}>
                      <input value={c.label} onChange={(e) => update(i, { label: e.target.value })} />
                      {project.status?.personas[c.label] ? <span className="chip on" style={{ marginTop: 6 }}>persona</span> : null}{" "}
                      {project.status?.episodes[c.label] ? <span className="chip on" style={{ marginTop: 6 }}>episode</span> : null}
                    </td>
                    <td onClick={(e) => e.stopPropagation()}>
                      <select value={c.importance || "minor"} onChange={(e) => update(i, { importance: e.target.value })}>
                        <option value="main">main ★</option>
                        <option value="supporting">supporting</option>
                        <option value="minor">minor</option>
                      </select>
                    </td>
                    <td>
                      <div className="row" style={{ gap: 6 }}>
                        {(c.references || []).slice(0, 14).map((r, k) => <span key={k} className="chip" title={r.where}>{r.expr}</span>)}
                        {(c.references?.length || 0) > 14 ? <span className="dim small">+{(c.references?.length || 0) - 14}</span> : null}
                      </div>
                    </td>
                    <td className="mono small">{c.appears_in?.length ?? "—"}</td>
                  </tr>
                  {open === i ? (
                    <tr>
                      <td colSpan={4}>
                        <dl className="kv">
                          <dt>役割</dt><dd>{c.role || "—"}</dd>
                          <dt>同一人物の根拠</dt><dd>{c.is_same_person_as_note || "—"}</dd>
                          <dt>見分け方</dt><dd>{c.disambiguation || "—"}</dd>
                          <dt>台詞の手がかり</dt><dd>{c.dialogue_markers || "—"}</dd>
                        </dl>
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {doc.narration?.length ? (
        <div className="card flat">
          <div className="card-head"><div className="row"><Sticker color="cyan">NARRATION</Sticker><h3>語り手</h3></div></div>
          <table className="t">
            <tbody>
              {doc.narration.map((n: any, i: number) => (
                <tr key={i}>
                  <td style={{ width: 200 }}><b>{n.narrator}</b><div className="small dim">{n.style}</div></td>
                  <td className="small">{n.notes}</td>
                  <td className="mono small dim" style={{ width: 90 }}>{n.files?.length} files</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </>
  );
}
