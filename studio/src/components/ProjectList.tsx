import type { ProjectSummary } from "../types";
import cls from "../utils";
import SectionCard from "./SectionCard";
import StatusBadge from "./StatusBadge";

type Props = {
  projects: ProjectSummary[];
  selectedBundle?: string;
  onSelect: (bundleName: string) => void;
};

export default function ProjectList({ projects, selectedBundle, onSelect }: Props) {
  return (
    <SectionCard title="Projects" subtitle="Saved bundles discovered in the outputs directory.">
      <div className="space-y-2">
        {projects.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-slate-700 px-4 py-6 text-sm text-slate-400">
            No bundles found yet. Start from the composer below to create your first baseline run.
          </div>
        ) : (
          projects.map((project) => {
            const isSelected = project.bundle_name === selectedBundle;
            return (
              <button
                key={project.bundle_name}
                type="button"
                onClick={() => onSelect(project.bundle_name)}
                className={cls(
                  "w-full rounded-2xl border px-4 py-3 text-left transition",
                  isSelected ? "border-indigo-500/60 bg-indigo-500/10" : "border-slate-800 bg-slate-950/60 hover:border-slate-700",
                )}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-medium text-slate-100">{project.bundle_name}</div>
                    <div className="mt-1 text-xs text-slate-400">
                      {project.states} states · {project.transitions} transitions
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
    </SectionCard>
  );
}
