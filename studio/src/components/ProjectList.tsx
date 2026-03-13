import type { ProjectSummary, Revision } from "../types";
import cls from "../utils";
import SectionCard from "./SectionCard";
import StatusBadge from "./StatusBadge";

type Props = {
  projects: ProjectSummary[];
  selectedBundle?: string;
  revisions?: Revision[];
  onSelect: (bundleName: string) => void;
};

function toneForRevision(revision: Revision): "accent" | "success" | "warning" | "neutral" {
  if (revision.kind === "agent_refine" && revision.ok === true) return "success";
  if (revision.kind === "edit") return "accent";
  if (revision.ok === false) return "warning";
  return "neutral";
}

export default function ProjectList({ projects, selectedBundle, revisions = [], onSelect }: Props) {
  const recentRevisions = [...revisions].reverse().slice(0, 4);

  return (
    <SectionCard title="Projects" subtitle="Switch bundles and inspect the latest revision trail for the selected one.">
      <div className="space-y-5">
        <div className="space-y-3">
          {projects.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-slate-700 px-4 py-6 text-sm text-slate-400">
              No bundles discovered yet. Generate a baseline run to seed the studio.
            </div>
          ) : (
            projects.map((project) => {
              const isSelected = selectedBundle === project.bundle_name;
              return (
                <button
                  key={project.bundle_name}
                  type="button"
                  onClick={() => onSelect(project.bundle_name)}
                  className={cls(
                    "w-full rounded-2xl border px-4 py-3 text-left transition",
                    isSelected
                      ? "border-indigo-500/60 bg-indigo-500/10"
                      : "border-slate-800 bg-slate-950/60 hover:border-slate-700",
                  )}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-medium text-slate-100">{project.bundle_name}</div>
                      <div className="mt-1 text-xs text-slate-400">
                        {project.states} states · {project.transitions} transitions · {project.revision_count} revisions
                      </div>
                    </div>
                    <StatusBadge
                      label={project.ok === true ? "OK" : project.ok === false ? "CHECK" : "NEW"}
                      tone={project.ok === true ? "success" : project.ok === false ? "warning" : "neutral"}
                    />
                  </div>
                </button>
              );
            })
          )}
        </div>

        <div className="border-t border-slate-800 pt-4">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <div className="text-sm font-medium text-slate-100">Selected bundle history</div>
              <div className="mt-1 text-xs text-slate-500">Most recent revisions for {selectedBundle ?? "the current selection"}</div>
            </div>
            <StatusBadge label={`${revisions.length} total`} tone="accent" />
          </div>

          {recentRevisions.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-slate-700 px-4 py-5 text-sm text-slate-400">
              No revisions recorded yet for the selected bundle.
            </div>
          ) : (
            <div className="space-y-3">
              {recentRevisions.map((revision, index) => (
                <div key={`${revision.dir ?? "revision"}-${index}`} className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-medium capitalize text-slate-100">{revision.kind ?? "revision"}</div>
                      <div className="mt-1 font-mono text-[11px] text-slate-500">{revision.dir ?? "(no directory)"}</div>
                    </div>
                    <StatusBadge
                      label={revision.ok === false ? "FAILED" : revision.ok === true ? "OK" : "RECORDED"}
                      tone={toneForRevision(revision)}
                    />
                  </div>
                  {revision.created_at ? (
                    <div className="mt-2 text-xs text-slate-400">{new Date(revision.created_at).toLocaleString()}</div>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </SectionCard>
  );
}
