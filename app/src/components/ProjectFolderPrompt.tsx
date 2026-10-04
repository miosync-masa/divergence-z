import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { go } from "../lib/hooks";

/**
 * 原稿フォルダとして選んだフォルダが、実はプロジェクト（project.yaml がある）だったときに
 * 「プロジェクトとして開きますか？」と聞く。原稿だけ読まれて、人物表や訳文が読まれない取り違えを防ぐ
 */
export function ProjectFolderPrompt({ path, currentRoot }: { path: string; currentRoot?: string }) {
  const [info, setInfo] = useState<Awaited<ReturnType<typeof api.inspectFolder>> | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setInfo(null);
    setDismissed(false);
    if (!path.trim()) return;
    api.inspectFolder(path).then(setInfo).catch(() => setInfo(null));
  }, [path]);

  if (!info?.is_project || dismissed || info.path === currentRoot) return null;

  const open = async () => {
    setError(null);
    try {
      const id = info.registered_id || (await api.openProject({ root: info.path })).id;
      go("p", id, "pipeline");
    } catch (e: any) {
      setError(e.message);
    }
  };

  return (
    <div className="banner">
      <span className="mono">PROJECT?</span>
      <div className="stack" style={{ gap: 2 }}>
        <span>このフォルダは既存のプロジェクト「{info.name}」{info.work ? `（${info.work}）` : ""}です。プロジェクトとして開きますか？</span>
        <span className="small" style={{ fontWeight: 400 }}>
          原稿フォルダにすると原稿だけが読まれ、人物表・ペルソナ・訳文は読まれません。
        </span>
        {error ? <span className="small" style={{ color: "var(--red)" }}>{error}</span> : null}
      </div>
      <span className="spacer" />
      <button className="btn sm lime" onClick={open}>プロジェクトとして開く</button>
      <button className="btn sm ghost" onClick={() => setDismissed(true)}>原稿フォルダとして使う</button>
    </div>
  );
}
