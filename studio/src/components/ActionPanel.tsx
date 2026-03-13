import SectionCard from "./SectionCard";
import StatusBadge from "./StatusBadge";
import cls from "../utils";

type Mode = "new" | "edit" | "refine" | "puml";

type Props = {
  mode: Mode;
  onModeChange: (value: Mode) => void;
  currentBundle?: string;
  specText: string;
  onSpecTextChange: (value: string) => void;
  bundleName: string;
  onBundleNameChange: (value: string) => void;
  agentRequest: string;
  onAgentRequestChange: (value: string) => void;
  useMock: boolean;
  onUseMockChange: (value: boolean) => void;
  onRunPipeline: () => void;
  onAgentEdit: () => void;
  onRefine: () => void;
  loading: string | null;
  hasProject: boolean;
  pumlDraft: string;
  onPumlDraftChange: (value: string) => void;
  onRoundTrip: () => void;
  onResetPumlDraft: () => void;
  onClosePumlEditor: () => void;
  isPumlEditing: boolean;
  hasUnsavedPuml: boolean;
  error: string | null;
  notice: string | null;
};

const modes: Array<{ id: Mode; label: string; hint: string }> = [
  { id: "new", label: "New model", hint: "Create a baseline bundle from natural language." },
  { id: "edit", label: "Edit model", hint: "Request a targeted change against the current model." },
  { id: "refine", label: "Refine", hint: "Run the repair loop on the currently selected bundle." },
  { id: "puml", label: "Edit PlantUML", hint: "Enter a wider code-style editing mode while keeping the rendered model visible." },
];

export default function ActionPanel({
  mode,
  onModeChange,
  currentBundle,
  specText,
  onSpecTextChange,
  bundleName,
  onBundleNameChange,
  agentRequest,
  onAgentRequestChange,
  useMock,
  onUseMockChange,
  onRunPipeline,
  onAgentEdit,
  onRefine,
  loading,
  hasProject,
  pumlDraft,
  onPumlDraftChange,
  onRoundTrip,
  onResetPumlDraft,
  onClosePumlEditor,
  isPumlEditing,
  hasUnsavedPuml,
  error,
  notice,
}: Props) {
  return (
    <SectionCard
      title="Actions"
      subtitle={
        isPumlEditing
          ? "PlantUML edit mode is active. The editor expands here while the model preview stays visible in the center."
          : "Create, adjust, or refine a bundle from one place."
      }
      className={cls(
        "transition-all duration-300",
        isPumlEditing && "h-full flex flex-col [&>div:last-child]:flex-1 [&>div:last-child]:flex [&>div:last-child]:flex-col",
      )}
    >
      <div className={cls("space-y-4", isPumlEditing && "flex h-full flex-col min-h-0")}>
        <div className={cls("grid gap-2 rounded-2xl border border-slate-800 bg-slate-950/70 p-1.5", isPumlEditing ? "grid-cols-2" : "grid-cols-2")}>
          {modes.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => onModeChange(item.id)}
              className={cls(
                "rounded-xl px-3 py-2 text-sm font-medium transition",
                mode === item.id
                  ? "bg-indigo-500/15 text-indigo-100"
                  : "text-slate-400 hover:bg-slate-900/80 hover:text-slate-200",
              )}
            >
              {item.label}
            </button>
          ))}
        </div>

        {error ? (
          <div className="rounded-2xl border border-rose-500/35 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">{error}</div>
        ) : null}

        {notice ? (
          <div className="rounded-2xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-100">{notice}</div>
        ) : null}

        {mode === "new" ? (
          <div className="space-y-4">
            <label className="block text-sm text-slate-300">
              Bundle name
              <input
                value={bundleName}
                onChange={(event) => onBundleNameChange(event.target.value)}
                className="mt-2 w-full rounded-2xl border border-slate-800 bg-slate-950/80 px-4 py-3 text-sm text-slate-100 outline-none transition focus:border-indigo-500/60"
              />
            </label>
            <label className="block text-sm text-slate-300">
              Requirement specification
              <textarea
                value={specText}
                onChange={(event) => onSpecTextChange(event.target.value)}
                className="mt-2 h-44 w-full rounded-2xl border border-slate-800 bg-slate-950/80 px-4 py-3 text-sm text-slate-100 outline-none transition focus:border-indigo-500/60"
              />
            </label>
            <button
              type="button"
              onClick={onRunPipeline}
              disabled={loading !== null}
              className="w-full rounded-2xl bg-indigo-500 px-4 py-3 text-sm font-semibold text-white transition hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {loading === "Run pipeline" ? "Running pipeline…" : "Generate baseline model"}
            </button>
          </div>
        ) : null}

        {mode === "edit" ? (
          <div className="space-y-4">
            <div className="rounded-2xl border border-slate-800 bg-slate-950/55 px-4 py-3 text-sm text-slate-300">
              Editing target: <span className="font-medium text-slate-100">{currentBundle ?? "No bundle selected"}</span>
            </div>
            <textarea
              value={agentRequest}
              onChange={(event) => onAgentRequestChange(event.target.value)}
              className="h-36 w-full rounded-2xl border border-slate-800 bg-slate-950/80 px-4 py-3 text-sm text-slate-100 outline-none transition focus:border-indigo-500/60"
              placeholder="Describe a change to the current model…"
            />
            <button
              type="button"
              onClick={onAgentEdit}
              disabled={!hasProject || loading !== null}
              className="w-full rounded-2xl border border-indigo-500/50 bg-indigo-500/10 px-4 py-3 text-sm font-medium text-indigo-100 transition hover:bg-indigo-500/20 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {loading === "Apply agent edit" ? "Applying edit…" : "Apply edit request"}
            </button>
          </div>
        ) : null}

        {mode === "refine" ? (
          <div className="space-y-4">
            <div className="rounded-2xl border border-slate-800 bg-slate-950/55 px-4 py-4 text-sm text-slate-300">
              <div className="font-medium text-slate-100">Selected bundle</div>
              <div className="mt-1">{currentBundle ?? "No bundle selected yet."}</div>
              <div className="mt-3 text-slate-400">
                Runs the agentic repair loop using the current bundle as input and records a new revision if changes are applied.
              </div>
            </div>
            <button
              type="button"
              onClick={onRefine}
              disabled={!hasProject || loading !== null}
              className="w-full rounded-2xl border border-emerald-500/40 bg-emerald-500/10 px-4 py-3 text-sm font-medium text-emerald-100 transition hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {loading === "Run refine loop" ? "Refining…" : "Run refine loop"}
            </button>
          </div>
        ) : null}

        {mode === "puml" ? (
          <div className="flex h-full min-h-0 flex-col gap-4">
            <div className="flex flex-wrap items-center justify-between gap-3 px-1 text-sm">
              <div className="min-w-0">
                <div className="text-xs uppercase tracking-[0.18em] text-slate-500">Editing bundle</div>
                <div className="truncate text-sm font-medium text-slate-100">{currentBundle ?? "No bundle selected"}</div>
              </div>
              <StatusBadge label={hasUnsavedPuml ? "Unsaved changes" : "Draft synced"} tone={hasUnsavedPuml ? "warning" : "success"} />
            </div>

            <textarea
              value={pumlDraft}
              onChange={(event) => onPumlDraftChange(event.target.value)}
              className="min-h-0 flex-1 w-full rounded-2xl border border-slate-800 bg-slate-950/90 px-4 py-4 font-mono text-sm leading-6 text-slate-100 outline-none transition focus:border-indigo-500/60"
              spellCheck={false}
              placeholder="No PlantUML is available yet. Generate or load a bundle first."
            />

            <div className="grid gap-3 sm:grid-cols-2">
              <button
                type="button"
                onClick={onRoundTrip}
                disabled={!hasProject || loading !== null}
                className="rounded-2xl border border-indigo-500/50 bg-indigo-500/10 px-4 py-3 text-sm font-medium text-indigo-100 transition hover:bg-indigo-500/20 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {loading === "Round-trip editor" ? "Round-tripping…" : "Round-trip PlantUML"}
              </button>
              <button
                type="button"
                onClick={onResetPumlDraft}
                disabled={!hasProject || loading !== null || !hasUnsavedPuml}
                className="rounded-2xl border border-slate-700 bg-slate-950/70 px-4 py-3 text-sm font-medium text-slate-200 transition hover:border-slate-600 hover:text-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Revert to saved PlantUML
              </button>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <button
                type="button"
                onClick={onClosePumlEditor}
                className="rounded-2xl border border-slate-700 bg-slate-950/70 px-4 py-3 text-sm font-medium text-slate-200 transition hover:border-slate-600 hover:text-slate-50"
              >
                Done editing
              </button>
              <button
                type="button"
                onClick={() => {
                  onResetPumlDraft();
                  onClosePumlEditor();
                }}
                className="rounded-2xl border border-rose-500/35 bg-rose-500/8 px-4 py-3 text-sm font-medium text-rose-100 transition hover:bg-rose-500/15"
              >
                Cancel edit mode
              </button>
            </div>
          </div>
        ) : null}

        {mode !== "puml" ? (
          <label className="flex items-center gap-3 rounded-2xl border border-slate-800 bg-slate-950/60 px-4 py-3 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={useMock}
              onChange={(event) => onUseMockChange(event.target.checked)}
              className="h-4 w-4 rounded border-slate-700 bg-slate-950 text-indigo-500"
            />
            Use deterministic mock generation for demos and UI testing
          </label>
        ) : null}
      </div>
    </SectionCard>
  );
}
