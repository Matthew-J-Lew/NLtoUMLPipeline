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
  const [showDiagnostics, setShowDiagnostics] = useState(false);

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
    { label: "Revisions", value: project?.summary.revision_count ?? 0 },
    { label: "Issues", value: diagnostics.length },
  ];

  return (
    <div className="space-y-5">
      <SectionCard
        title="Overview"
        subtitle="Current bundle status, quick metrics, and validation summary."
        action={<StatusBadge label={status.label} tone={status.tone} />}
      >
        <div className="space-y-5">
          <div>
            <div className="text-xl font-semibold text-slate-50">{project?.bundle_name ?? "No bundle selected"}</div>
            <div className="mt-1 text-sm text-slate-400">
              {project?.summary.current_pointer
                ? `Current pointer: ${project.summary.current_pointer}`
                : "Select a bundle or generate a new baseline model to populate the workspace."}
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
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-sm font-medium text-slate-100">Validation summary</div>
                <div className="mt-1 text-sm text-slate-400">{summaryText}</div>
              </div>
              <StatusBadge
                label={project?.summary.ok === true ? "PASS" : diagnostics.length ? "REVIEW" : "PENDING"}
                tone={project?.summary.ok === true ? "success" : diagnostics.length ? "warning" : "neutral"}
              />
            </div>

            {diagnostics.length > 0 ? (
              <button
                type="button"
                onClick={() => setShowDiagnostics((value) => !value)}
                className="mt-4 rounded-full border border-slate-700 bg-slate-900/70 px-3 py-2 text-xs font-medium text-slate-200 transition hover:border-slate-600 hover:text-slate-50"
              >
                {showDiagnostics ? "Hide validation details" : `Show validation details (${diagnostics.length})`}
              </button>
            ) : null}

            {showDiagnostics ? (
              <div className="mt-4 space-y-3 border-t border-slate-800 pt-4">
                {diagnostics.map((diag, index) => (
                  <div key={`${diag.code ?? "diag"}-${index}`} className="rounded-2xl border border-slate-800 bg-slate-900/80 p-4">
                    <div className="mb-2 flex items-center justify-between gap-3">
                      <StatusBadge
                        label={(diag.severity ?? "info").toUpperCase()}
                        tone={
                          diag.severity === "error"
                            ? "danger"
                            : diag.severity === "warning"
                              ? "warning"
                              : "neutral"
                        }
                      />
                      {diag.code ? <span className="font-mono text-xs text-slate-500">{diag.code}</span> : null}
                    </div>
                    <p className="text-sm text-slate-100">{diag.message ?? "No message provided."}</p>
                    {diag.path ? <p className="mt-2 font-mono text-xs text-slate-500">{diag.path}</p> : null}
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        </div>
      </SectionCard>

      <SectionCard title="Current context" subtitle="Small details for the active bundle and recent revision trail.">
        <div className="space-y-3 text-sm text-slate-300">
          <div className="flex items-center justify-between gap-3 rounded-2xl border border-slate-800 bg-slate-950/60 px-4 py-3">
            <span className="text-slate-400">Last updated</span>
            <span className="text-right text-slate-100">{formatDate(project?.summary.updated_at)}</span>
          </div>
          <div className="flex items-center justify-between gap-3 rounded-2xl border border-slate-800 bg-slate-950/60 px-4 py-3">
            <span className="text-slate-400">Execution mode</span>
            <StatusBadge label={loading ? loading : "Ready"} tone={loading ? "accent" : "neutral"} />
          </div>
          <div className="rounded-2xl border border-slate-800 bg-slate-950/60 px-4 py-3">
            <div className="text-slate-400">Recommended edit path</div>
            <div className="mt-1 font-medium text-slate-100">PlantUML → Round-trip → Canonical IR</div>
          </div>

          <div className="border-t border-slate-800 pt-3">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium text-slate-100">Recent revisions</div>
                <div className="mt-1 text-xs text-slate-500">Only the latest activity for the active bundle.</div>
              </div>
              <StatusBadge label={`${recentRevisions.length}`} tone="accent" />
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
    </div>
  );
}
