import type { Revision } from "../types";
import SectionCard from "./SectionCard";
import StatusBadge from "./StatusBadge";

function toneForRevision(revision: Revision): "accent" | "success" | "warning" | "neutral" {
  if (revision.kind === "agent_refine" && revision.ok === true) return "success";
  if (revision.kind === "edit") return "accent";
  return "neutral";
}

type Props = {
  revisions: Revision[];
};

export default function RevisionHistory({ revisions }: Props) {
  return (
    <SectionCard title="Revision history" subtitle="Bundles remain inspectable through successive edit and repair passes.">
      {revisions.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-slate-700 px-4 py-6 text-sm text-slate-400">
          No revisions yet. Generate a baseline run or submit an edit request to begin a provenance trail.
        </div>
      ) : (
        <div className="space-y-3">
          {revisions.map((revision, index) => (
            <div key={`${revision.dir ?? "revision"}-${index}`} className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
              <div className="mb-2 flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-medium text-slate-100">{revision.kind ?? "revision"}</div>
                  <div className="font-mono text-xs text-slate-500">{revision.dir ?? "(no directory)"}</div>
                </div>
                <StatusBadge label={revision.ok === false ? "FAILED" : revision.ok === true ? "OK" : "RECORDED"} tone={toneForRevision(revision)} />
              </div>
              {revision.created_at ? <div className="text-xs text-slate-400">{new Date(revision.created_at).toLocaleString()}</div> : null}
              {typeof revision.iterations === "number" ? <div className="mt-2 text-xs text-slate-400">Iterations: {revision.iterations}</div> : null}
              {revision.stop_reason ? <div className="mt-2 text-sm text-slate-300">{revision.stop_reason}</div> : null}
            </div>
          ))}
        </div>
      )}
    </SectionCard>
  );
}
