import { useEffect, useMemo, useState } from "react";
import ArtifactTabs from "./components/ArtifactTabs";
import DiagramCanvas from "./components/DiagramCanvas";
import MetricCard from "./components/MetricCard";
import PipelineStepper from "./components/PipelineStepper";
import ProjectList from "./components/ProjectList";
import RevisionHistory from "./components/RevisionHistory";
import SectionCard from "./components/SectionCard";
import StatusBadge from "./components/StatusBadge";
import ValidationPanel from "./components/ValidationPanel";
import { agentEdit, fetchProject, fetchProjects, refine, roundTrip, runPipeline } from "./lib/api";
import type { ProjectSnapshot, ProjectSummary } from "./types";

const EXAMPLE_SPEC =
  'When motion is detected, turn on the hallway light. When motion stops for 5 minutes, turn it off.';

export default function App() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [selectedBundle, setSelectedBundle] = useState<string | undefined>();
  const [project, setProject] = useState<ProjectSnapshot | null>(null);
  const [specText, setSpecText] = useState(EXAMPLE_SPEC);
  const [bundleName, setBundleName] = useState("StudioMotionLight");
  const [agentRequest, setAgentRequest] = useState(
    "Rename Idle to LightOff and reduce the timeout from 300 seconds to 120 seconds.",
  );
  const [useMock, setUseMock] = useState(true);
  const [pumlDraft, setPumlDraft] = useState("");
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function refreshProjects(preferredBundle?: string) {
    const items = await fetchProjects();
    setProjects(items);
    const nextBundle = preferredBundle ?? selectedBundle ?? items[0]?.bundle_name;
    if (nextBundle) {
      setSelectedBundle(nextBundle);
      const snapshot = await fetchProject(nextBundle);
      setProject(snapshot);
      setPumlDraft(snapshot.current.puml ?? "");
    }
  }

  useEffect(() => {
    refreshProjects().catch((err: unknown) => {
      setError(err instanceof Error ? err.message : "Failed to load studio state.");
    });
  }, []);

  const diagnosticCounts = project?.summary.diagnostic_counts ?? { error: 0, warning: 0, info: 0 };
  const totalDiagnostics = (diagnosticCounts.error ?? 0) + (diagnosticCounts.warning ?? 0) + (diagnosticCounts.info ?? 0);

  const projectStatusTone = useMemo(() => {
    if (project?.summary.ok === true) return "success" as const;
    if (project?.summary.ok === false) return "warning" as const;
    return "neutral" as const;
  }, [project?.summary.ok]);

  async function withAction(label: string, action: () => Promise<void>) {
    try {
      setError(null);
      setNotice(null);
      setLoading(label);
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : `Failed to ${label.toLowerCase()}.`);
    } finally {
      setLoading(null);
    }
  }

  async function loadBundle(bundleNameToLoad: string) {
    await withAction("Load bundle", async () => {
      const snapshot = await fetchProject(bundleNameToLoad);
      setSelectedBundle(bundleNameToLoad);
      setProject(snapshot);
      setPumlDraft(snapshot.current.puml ?? "");
    });
  }

  async function handleRunPipeline() {
    await withAction("Run pipeline", async () => {
      const snapshot = await runPipeline({
        text: specText,
        bundle_name: bundleName,
        use_mock: useMock,
        max_repairs: 1,
      });
      setProject(snapshot);
      setSelectedBundle(snapshot.bundle_name);
      setPumlDraft(snapshot.current.puml ?? "");
      await refreshProjects(snapshot.bundle_name);
      setNotice(`Generated baseline artifacts for ${snapshot.bundle_name}.`);
    });
  }

  async function handleAgentEdit() {
    if (!project) return;
    await withAction("Apply agent edit", async () => {
      const snapshot = await agentEdit(project.bundle_name, {
        request: agentRequest,
        use_mock: useMock,
        max_repairs: 1,
      });
      setProject(snapshot);
      setPumlDraft(snapshot.current.puml ?? "");
      await refreshProjects(snapshot.bundle_name);
      setNotice(`Applied agent edit to ${snapshot.bundle_name}.`);
    });
  }

  async function handleRoundTrip() {
    if (!project) return;
    await withAction("Round-trip editor", async () => {
      const snapshot = await roundTrip(project.bundle_name, pumlDraft);
      setProject(snapshot);
      setPumlDraft(snapshot.current.puml ?? pumlDraft);
      await refreshProjects(snapshot.bundle_name);
      setNotice(`Round-tripped the edited PlantUML for ${snapshot.bundle_name}.`);
    });
  }

  async function handleRefine() {
    if (!project) return;
    await withAction("Run refine loop", async () => {
      const snapshot = await refine(project.bundle_name, {
        use_mock: useMock,
        max_iters: 4,
        max_patch_repairs: 2,
      });
      setProject(snapshot);
      setPumlDraft(snapshot.current.puml ?? "");
      await refreshProjects(snapshot.bundle_name);
      setNotice(`Completed the refine loop for ${snapshot.bundle_name}.`);
    });
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-50">
      <div className="mx-auto max-w-[1720px] px-4 py-6 sm:px-6 lg:px-8">
        <header className="mb-6 rounded-[2rem] border border-indigo-500/20 bg-gradient-to-r from-slate-900 via-slate-900 to-indigo-950/40 px-6 py-5 shadow-panel">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <div className="mb-3 flex flex-wrap items-center gap-3">
                <StatusBadge label="MVP Studio" tone="accent" />
                <StatusBadge label="Verification-first" tone="success" />
                <StatusBadge label={useMock ? "Demo mode" : "LLM mode"} tone={useMock ? "warning" : "neutral"} />
              </div>
              <h1 className="text-3xl font-semibold tracking-tight text-slate-50 sm:text-4xl">
                NL→UML Research Studio
              </h1>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-300 sm:text-base">
                A modern academic workbench for generating, validating, editing, and refining platform-neutral state
                machine models from natural language requirements.
              </p>
            </div>
            <div className="max-w-lg rounded-3xl border border-slate-800 bg-slate-950/60 px-5 py-4 text-sm text-slate-300">
              <div className="mb-2 text-xs uppercase tracking-[0.22em] text-slate-500">What this screen optimizes for</div>
              <p>
                Traceability, human-editable checkpoints, visible diagnostics, and fast iteration between baseline runs,
                round-trips, and agentic repairs.
              </p>
            </div>
          </div>
        </header>

        <div className="grid gap-6 xl:grid-cols-[340px_minmax(0,1fr)_360px]">
          <div className="space-y-6">
            <ProjectList projects={projects} selectedBundle={selectedBundle} onSelect={loadBundle} />

            <SectionCard title="Composer" subtitle="Start a new run from natural language.">
              <div className="space-y-4">
                <label className="block text-sm text-slate-300">
                  Bundle name
                  <input
                    value={bundleName}
                    onChange={(event) => setBundleName(event.target.value)}
                    className="mt-2 w-full rounded-2xl border border-slate-800 bg-slate-950/80 px-4 py-3 text-sm text-slate-100 outline-none transition focus:border-indigo-500/60"
                  />
                </label>
                <label className="block text-sm text-slate-300">
                  Requirement specification
                  <textarea
                    value={specText}
                    onChange={(event) => setSpecText(event.target.value)}
                    className="mt-2 h-40 w-full rounded-2xl border border-slate-800 bg-slate-950/80 px-4 py-3 text-sm text-slate-100 outline-none transition focus:border-indigo-500/60"
                  />
                </label>
                <label className="flex items-center gap-3 rounded-2xl border border-slate-800 bg-slate-950/60 px-4 py-3 text-sm text-slate-300">
                  <input
                    type="checkbox"
                    checked={useMock}
                    onChange={(event) => setUseMock(event.target.checked)}
                    className="h-4 w-4 rounded border-slate-700 bg-slate-950 text-indigo-500"
                  />
                  Use deterministic mock generation for demos and UI testing
                </label>
                <button
                  type="button"
                  onClick={handleRunPipeline}
                  disabled={loading !== null}
                  className="w-full rounded-2xl bg-indigo-500 px-4 py-3 text-sm font-semibold text-white transition hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {loading === "Run pipeline" ? "Running pipeline…" : "Generate baseline model"}
                </button>
              </div>
            </SectionCard>

            <SectionCard title="AI change request" subtitle="Apply an agent edit against the current canonical IR.">
              <div className="space-y-4">
                <textarea
                  value={agentRequest}
                  onChange={(event) => setAgentRequest(event.target.value)}
                  className="h-32 w-full rounded-2xl border border-slate-800 bg-slate-950/80 px-4 py-3 text-sm text-slate-100 outline-none transition focus:border-indigo-500/60"
                  placeholder="Describe a change to the current model…"
                />
                <div className="grid gap-3 sm:grid-cols-2">
                  <button
                    type="button"
                    onClick={handleAgentEdit}
                    disabled={!project || loading !== null}
                    className="rounded-2xl border border-indigo-500/50 bg-indigo-500/10 px-4 py-3 text-sm font-medium text-indigo-100 transition hover:bg-indigo-500/20 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {loading === "Apply agent edit" ? "Applying…" : "Apply edit"}
                  </button>
                  <button
                    type="button"
                    onClick={handleRefine}
                    disabled={!project || loading !== null}
                    className="rounded-2xl border border-emerald-500/40 bg-emerald-500/10 px-4 py-3 text-sm font-medium text-emerald-100 transition hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {loading === "Run refine loop" ? "Refining…" : "Run refine loop"}
                  </button>
                </div>
              </div>
            </SectionCard>
          </div>

          <div className="space-y-6">
            <SectionCard
              title="Studio status"
              subtitle="The current bundle remains fully inspectable across baseline, edit, and refine stages."
              action={
                <StatusBadge
                  label={project?.summary.ok === true ? "Verified" : project?.summary.ok === false ? "Needs review" : "Idle"}
                  tone={projectStatusTone}
                />
              }
            >
              <div className="mb-5 flex flex-wrap items-center gap-3">
                <div>
                  <div className="text-xl font-semibold text-slate-50">{project?.bundle_name ?? "No bundle selected"}</div>
                  <div className="mt-1 text-sm text-slate-400">
                    {project?.summary.current_pointer ? `Current pointer: ${project.summary.current_pointer}` : "Start with a baseline run to populate the studio."}
                  </div>
                </div>
              </div>
              <PipelineStepper activeIndex={3} ok={project?.summary.ok} />
            </SectionCard>

            <div className="grid gap-4 md:grid-cols-4">
              <MetricCard label="States" value={project?.summary.states ?? 0} hint="Canonical state count" />
              <MetricCard label="Transitions" value={project?.summary.transitions ?? 0} hint="Current IR graph edges" />
              <MetricCard
                label="Diagnostics"
                value={totalDiagnostics}
                hint={`${diagnosticCounts.error ?? 0} errors · ${diagnosticCounts.warning ?? 0} warnings`}
                tone={totalDiagnostics > 0 ? "danger" : "success"}
              />
              <MetricCard
                label="Revisions"
                value={project?.summary.revision_count ?? 0}
                hint="Manifest-backed provenance"
                tone="accent"
              />
            </div>

            {error ? (
              <div className="rounded-2xl border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">{error}</div>
            ) : null}
            {notice ? (
              <div className="rounded-2xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-100">{notice}</div>
            ) : null}

            <DiagramCanvas ir={project?.current.ir} />
            <ArtifactTabs
              project={project}
              pumlDraft={pumlDraft}
              onPumlDraftChange={setPumlDraft}
              onRoundTrip={handleRoundTrip}
              roundTripDisabled={!project || loading !== null}
            />
          </div>

          <div className="space-y-6">
            <ValidationPanel report={project?.current.validation} />

            <SectionCard title="Research lens" subtitle="A lightweight explanation layer for demos, advisors, and reviewers.">
              <div className="space-y-3 text-sm text-slate-300">
                <p>
                  The studio treats every stage as an inspectable artifact boundary: baseline generation, typed
                  validation, human-editable PlantUML, round-trip recompilation, and agentic repair.
                </p>
                <p>
                  This makes the UI suitable both for product demos and for presenting the verification-first research
                  story behind the pipeline.
                </p>
              </div>
            </SectionCard>

            <RevisionHistory revisions={project?.revisions ?? []} />
          </div>
        </div>
      </div>
    </div>
  );
}
