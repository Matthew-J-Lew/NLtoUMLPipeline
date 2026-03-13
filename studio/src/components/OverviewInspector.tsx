import { useMemo, useState } from "react";
import type { Diagnostic, ProjectSnapshot, Revision } from "../types";
import SectionCard from "./SectionCard";
import StatusBadge from "./StatusBadge";

function statusForProject(project?: ProjectSnapshot | null) {
  if (!project) return { label: "Idle", tone: "neutral" as const };
  if (project.summary.ok === true) return { label: "Verified", tone: "success" as const };
  const diagnostics = project.current.validation?.diagnostics ?? [];
  if (diagnostics.length > 0) return { label: "Needs review", tone: "warning" as const };
  return { label: "In progress", tone: "accent" as const };
}

function formatDate(value?: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function toneForRevision(revision: Revision): "accent" | "success" | "warning" | "neutral" {
  if (revision.kind === "agent_refine" && revision.ok === true) return "success";
  if (revision.kind === "edit") return "accent";
  if (revision.ok === false) return "warning";
  return "neutral";
}

function severityTone(severity?: string): "danger" | "warning" | "neutral" {
  if (severity === "error") return "danger";
  if (severity === "warning") return "warning";
  return "neutral";
}

export default function OverviewInspector({
  project,
  loading,
  error,
  notice,
}: {
  project?: ProjectSnapshot | null;
  loading: string | null;
  error: string | null;
  notice: string | null;
}) {
  const [showValidation, setShowValidation] = useState(false);
  const [showHistory, setShowHistory] = useState(false);

  const diagnostics = useMemo<Diagnostic[]>(() => project?.current.validation?.diagnostics ?? [], [project]);
  const recentRevisions = useMemo(() => [...(project?.revisions ?? [])].reverse().slice(0, 3), [project]);
  const status = statusForProject(project);
  const summaryText = project
    ? project.summary.ok === true
      ? "The current canonical IR passed validation."
      : diagnostics.length > 0
        ? `${diagnostics.length} diagnostic${diagnostics.length === 1 ? "" : "s"} need review.`
        : "No validation summary available yet."
    : "Select or create a bundle to populate the inspector.";

  const stats = [
    { label: "States", value: project?.summary.states ?? 0 },
    { label: "Transitions", value: project?.summary.transitions ?? 0 },
    { label: "Issues", value: diagnostics.length },
    { label: "Revisions", value: project?.summary.revision_count ?? 0 },
  ];

  return (
    <SectionCard
      title="Inspector"
      subtitle="The most important bundle health and activity at a glance."
      action={<StatusBadge label={status.label} tone={status.tone} />}
    >
      <div className="space-y-4">
        <div>
          <div className="text-xl font-semibold text-slate-50">{project?.bundle_name ?? "No bundle selected"}</div>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-slate-400">
            <span>Updated {formatDate(project?.summary.updated_at)}</span>
            {project?.summary.current_pointer ? <span>• {project.summary.current_pointer}</span> : null}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          {stats.map((stat) => (
            <div key={stat.label} className="rounded-2xl border border-slate-800 bg-slate-950/70 px-4 py-3">
              <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">{stat.label}</div>
              <div className="mt-2 text-2xl font-semibold text-slate-50">{stat.value}</div>
            </div>
          ))}
        </div>

        {error ? (
          <div className="rounded-2xl border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">{error}</div>
        ) : null}
        {notice ? (
          <div className="rounded-2xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-100">{notice}</div>
        ) : null}

        <div className="rounded-2xl border border-slate-800 bg-slate-950/65 p-4">
          <div className="text-sm font-medium text-slate-100">Validation</div>
          <div className="mt-1 text-sm text-slate-400">{summaryText}</div>
        </div>

        <div className="grid gap-2 sm:grid-cols-2">
          <button
            type="button"
            onClick={() => setShowValidation((value) => !value)}
            className="rounded-full border border-slate-700 bg-slate-900/70 px-3 py-2 text-xs font-medium text-slate-200 transition hover:border-slate-600 hover:text-slate-50"
          >
            {showValidation ? "Hide validation" : `Show validation${diagnostics.length ? ` (${diagnostics.length})` : ""}`}
          </button>
          <button
            type="button"
            onClick={() => setShowHistory((value) => !value)}
            className="rounded-full border border-slate-700 bg-slate-900/70 px-3 py-2 text-xs font-medium text-slate-200 transition hover:border-slate-600 hover:text-slate-50"
          >
            {showHistory ? "Hide history" : `Show history${recentRevisions.length ? ` (${recentRevisions.length})` : ""}`}
          </button>
        </div>

        {showValidation ? (
          <div className="space-y-3 border-t border-slate-800 pt-4">
            {diagnostics.length === 0 ? (
              <div className="rounded-2xl border border-slate-800 bg-slate-950/60 px-4 py-4 text-sm text-slate-400">
                No diagnostics recorded for the current canonical IR.
              </div>
            ) : (
              diagnostics.map((diag, index) => (
                <div key={`${diag.code ?? "diag"}-${index}`} className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
                  <div className="mb-2 flex items-center justify-between gap-3">
                    <StatusBadge label={(diag.severity ?? "info").toUpperCase()} tone={severityTone(diag.severity)} />
                    {diag.code ? <span className="font-mono text-xs text-slate-500">{diag.code}</span> : null}
                  </div>
                  <p className="text-sm text-slate-100">{diag.message ?? "No message provided."}</p>
                  {diag.path ? <p className="mt-2 font-mono text-xs text-slate-500">{diag.path}</p> : null}
                </div>
              ))
            )}
          </div>
        ) : null}

        {showHistory ? (
          <div className="space-y-3 border-t border-slate-800 pt-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-2xl border border-slate-800 bg-slate-950/60 px-4 py-3 text-sm text-slate-300">
                <div className="text-slate-400">Execution</div>
                <div className="mt-1 flex items-center justify-between gap-3">
                  <span>Studio status</span>
                  <StatusBadge label={loading ? loading : "Ready"} tone={loading ? "accent" : "neutral"} />
                </div>
              </div>
              <div className="rounded-2xl border border-slate-800 bg-slate-950/60 px-4 py-3 text-sm text-slate-300">
                <div className="text-slate-400">Recommended path</div>
                <div className="mt-1 font-medium text-slate-100">PlantUML → Round-trip → Canonical IR</div>
              </div>
            </div>

            {recentRevisions.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-slate-700 px-4 py-5 text-sm text-slate-400">
                No revisions recorded yet for the active bundle.
              </div>
            ) : (
              <div className="space-y-3">
                {recentRevisions.map((revision, index) => (
                  <div key={`${revision.dir ?? "revision"}-${index}`} className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="truncate text-sm font-medium capitalize text-slate-100">{revision.kind ?? "revision"}</div>
                        <div className="mt-1 truncate font-mono text-[11px] text-slate-500">{revision.dir ?? "(no directory)"}</div>
                      </div>
                      <StatusBadge
                        label={revision.ok === false ? "FAILED" : revision.ok === true ? "OK" : "RECORDED"}
                        tone={toneForRevision(revision)}
                      />
                    </div>
                    {revision.created_at ? <div className="mt-2 text-xs text-slate-400">{new Date(revision.created_at).toLocaleString()}</div> : null}
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : null}
      </div>
    </SectionCard>
  );
}
