import { useEffect, useMemo, useState } from "react";
import ActionPanel from "./components/ActionPanel";
import ArtifactTabs from "./components/ArtifactTabs";
import OverviewInspector from "./components/OverviewInspector";
import ProjectBrowserModal from "./components/ProjectBrowserModal";
import StatusBadge from "./components/StatusBadge";
import { agentEdit, fetchProject, fetchProjects, refine, roundTrip, runPipeline } from "./lib/api";
import type { ProjectSnapshot, ProjectSummary } from "./types";

const EXAMPLE_SPEC =
  "When motion is detected, turn on the hallway light. When motion stops for 5 minutes, turn it off.";

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
  const [browserOpen, setBrowserOpen] = useState(false);

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

  const modeBadge = useMemo(() => (useMock ? "Demo mode" : "LLM mode"), [useMock]);
  const activeSummary = useMemo(
    () => projects.find((item) => item.bundle_name === selectedBundle),
    [projects, selectedBundle],
  );

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
      <ProjectBrowserModal
        open={browserOpen}
        projects={projects}
        selectedBundle={selectedBundle}
        onClose={() => setBrowserOpen(false)}
        onSelect={(bundle) => {
          loadBundle(bundle).catch(() => {
            // Errors are already handled in loadBundle.
          });
        }}
      />

      <div className="mx-auto max-w-[1800px] px-4 py-5 sm:px-6 lg:px-8">
        <header className="mb-5 rounded-[2rem] border border-indigo-500/20 bg-gradient-to-r from-slate-900 via-slate-900 to-indigo-950/30 px-5 py-4 shadow-panel">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
            <div className="min-w-0">
              <div className="mb-3 flex flex-wrap items-center gap-3">
                <StatusBadge label="MVP Studio" tone="accent" />
                <StatusBadge label={modeBadge} tone={useMock ? "warning" : "neutral"} />
                <StatusBadge label={project?.summary.ok === true ? "Verified bundle" : "Editable workflow"} tone={project?.summary.ok === true ? "success" : "neutral"} />
              </div>
              <h1 className="text-3xl font-semibold tracking-tight text-slate-50 sm:text-4xl">NL→UML Studio</h1>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-300 sm:text-base">
                A cleaner verification-first workspace for generating, reviewing, rendering, and refining platform-neutral state machines.
              </p>
            </div>

            <div className="grid gap-3 xl:min-w-[520px] xl:max-w-[620px] xl:grid-cols-[minmax(0,1fr)_auto]">
              <div className="rounded-2xl border border-slate-800 bg-slate-950/70 px-4 py-3">
                <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Current project</div>
                <div className="mt-1 flex flex-wrap items-center gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-base font-semibold text-slate-100">
                      {project?.bundle_name ?? selectedBundle ?? "No bundle selected"}
                    </div>
                    <div className="mt-0.5 text-sm text-slate-400">
                      {activeSummary
                        ? `${activeSummary.states} states · ${activeSummary.transitions} transitions · ${activeSummary.revision_count} revisions`
                        : "Select a bundle or create a new one to start working."}
                    </div>
                  </div>
                  {activeSummary ? (
                    <StatusBadge
                      label={activeSummary.ok === true ? "OK" : activeSummary.ok === false ? "CHECK" : "NEW"}
                      tone={activeSummary.ok === true ? "success" : activeSummary.ok === false ? "warning" : "neutral"}
                    />
                  ) : null}
                </div>
              </div>

              <div className="flex items-center gap-2 xl:justify-end">
                <button
                  type="button"
                  onClick={() => setBrowserOpen(true)}
                  className="rounded-full border border-slate-700 bg-slate-950/70 px-4 py-2.5 text-sm font-medium text-slate-200 transition hover:border-slate-600 hover:text-slate-50"
                >
                  Browse all projects
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setBundleName(project?.bundle_name ? `${project.bundle_name}Copy` : "StudioMotionLight");
                  }}
                  className="rounded-full border border-indigo-500/50 bg-indigo-500/10 px-4 py-2.5 text-sm font-medium text-indigo-100 transition hover:bg-indigo-500/20"
                >
                  New project
                </button>
              </div>
            </div>
          </div>
        </header>

        <div className="grid gap-5 xl:grid-cols-[300px_minmax(0,1fr)_320px]">
          <div className="xl:sticky xl:top-5 xl:self-start">
            <ActionPanel
              currentBundle={project?.bundle_name}
              specText={specText}
              onSpecTextChange={setSpecText}
              bundleName={bundleName}
              onBundleNameChange={setBundleName}
              agentRequest={agentRequest}
              onAgentRequestChange={setAgentRequest}
              useMock={useMock}
              onUseMockChange={setUseMock}
              onRunPipeline={handleRunPipeline}
              onAgentEdit={handleAgentEdit}
              onRefine={handleRefine}
              loading={loading}
              hasProject={Boolean(project)}
            />
          </div>

          <div className="min-w-0">
            <ArtifactTabs
              project={project}
              pumlDraft={pumlDraft}
              onPumlDraftChange={setPumlDraft}
              onRoundTrip={handleRoundTrip}
              roundTripDisabled={!project || loading !== null}
            />
          </div>

          <div className="xl:sticky xl:top-5 xl:self-start">
            <OverviewInspector project={project} loading={loading} error={error} notice={notice} />
          </div>
        </div>
      </div>
    </div>
  );
}
