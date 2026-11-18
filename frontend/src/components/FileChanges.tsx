import type { FileChange } from "../types";

function shortPath(path: string): string {
  const parts = path.split("/").filter(Boolean);
  if (parts.length <= 2) return path;
  return parts.slice(-2).join("/");
}

export function FileChanges({ files, dark = false }: { files: FileChange[]; dark?: boolean }) {
  if (!files.length) return null;
  const added = files.reduce((sum, file) => sum + (file.added || 0), 0);
  const removed = files.reduce((sum, file) => sum + (file.removed || 0), 0);
  const label = files.length === 1 ? "1 File" : `${files.length} Files`;
  const shown = files.slice(0, 6);
  const extra = files.length - shown.length;
  return (
    <div className={dark ? "rounded-lg border border-[#3a3f4b] bg-[#12141a] px-2 py-1.5" : "rounded border border-line bg-panel2 px-2 py-1.5"}>
      <div className="flex items-center justify-between gap-2 font-mono text-[10px]">
        <span className={dark ? "text-[#d7dbe3]" : "text-paper"}>{label}</span>
        <span>
          <span className="text-mint">+{added}</span>
          <span className="text-coral"> −{removed}</span>
        </span>
      </div>
      <div className="mt-1 space-y-0.5">
        {shown.map((file) => (
          <div key={file.path} className="flex items-center gap-2 font-mono text-[10px]" title={file.path}>
            <span className={`min-w-0 flex-1 truncate ${dark ? "text-[#c5ccd6]" : "text-paper/90"}`}>{shortPath(file.path)}</span>
            <span className="shrink-0 text-mint">+{file.added || 0}</span>
            <span className="shrink-0 text-coral">−{file.removed || 0}</span>
          </div>
        ))}
        {extra > 0 && <div className="font-mono text-[10px] text-muted">+{extra} more</div>}
      </div>
    </div>
  );
}
