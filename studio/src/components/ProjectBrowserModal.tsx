import { useEffect, useMemo, useState } from "react";
import type { ProjectSummary } from "../types";
import cls from "../utils";
import StatusBadge from "./StatusBadge";

type Props = {
  open: boolean;
  projects: ProjectSummary[];
  selectedBundle?: string;
  onClose: () => void;
  onSelect: (bundleName: string) => void;
};

export default function ProjectBrowserModal({ open, projects, selectedBundle, onClose, onSelect }: Props) {
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (!open) {
      setQuery("");
      return;
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  const filteredProjects = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return projects;
    return projects.filter((project) => project.bundle_name.toLowerCase().includes(normalized));
  }, [projects, query]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-slate-950/75 px-4 py-10 backdrop-blur-sm sm:px-6">
      <div className="w-full max-w-3xl rounded-[2rem] border border-slate-800 bg-slate-900/95 shadow-panel">
        <div className="flex items-start justify-between gap-4 border-b border-slate-800 px-6 py-5">
          <div>
            <div className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-200">Browse all projects</div>
            <p className="mt-1 text-sm text-slate-400">
              Switch between all your available projects.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-full border border-slate-700 bg-slate-950/70 px-3 py-2 text-sm text-slate-300 transition hover:border-slate-600 hover:text-slate-100"
          >
            Close
          </button>
        </div>

        <div className="space-y-4 px-6 py-5">
          <div className="rounded-2xl border border-slate-800 bg-slate-950/70 p-3">
            <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-slate-500">Search bundles</label>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search by bundle name"
              className="w-full rounded-xl border border-slate-700 bg-slate-950/70 px-3 py-2.5 text-sm text-slate-100 outline-none transition focus:border-indigo-500/60"
            />
          </div>

          <div className="max-h-[60vh] space-y-3 overflow-auto pr-1">
            {filteredProjects.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-slate-700 px-4 py-8 text-center text-sm text-slate-400">
                No bundles match that search.
              </div>
            ) : (
              filteredProjects.map((project) => {
                const isSelected = project.bundle_name === selectedBundle;
                return (
                  <button
                    key={project.bundle_name}
                    type="button"
                    onClick={() => {
                      onSelect(project.bundle_name);
                      onClose();
                    }}
                    className={cls(
                      "w-full rounded-2xl border px-4 py-4 text-left transition",
                      isSelected
                        ? "border-indigo-500/60 bg-indigo-500/10"
                        : "border-slate-800 bg-slate-950/60 hover:border-slate-700 hover:bg-slate-950/80",
                    )}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="text-base font-medium text-slate-100">{project.bundle_name}</div>
                        <div className="mt-1 text-sm text-slate-400">
                          {project.states} states · {project.transitions} transitions · {project.revision_count} revisions
                        </div>
                      </div>
                      <StatusBadge
                        label={project.ok === true ? (isSelected ? "ACTIVE · OK" : "OK") : project.ok === false ? "CHECK" : isSelected ? "ACTIVE" : "NEW"}
                        tone={project.ok === true ? "success" : project.ok === false ? "warning" : "neutral"}
                      />
                    </div>
                  </button>
                );
              })
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
