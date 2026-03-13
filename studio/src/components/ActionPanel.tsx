import { useState } from "react";
import SectionCard from "./SectionCard";
import StatusBadge from "./StatusBadge";
import cls from "../utils";

type Mode = "new" | "edit" | "refine";

type Props = {
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
};

const modes: Array<{ id: Mode; label: string; hint: string }> = [
  { id: "new", label: "New model", hint: "Create a baseline bundle from natural language." },
  { id: "edit", label: "Edit model", hint: "Request a targeted change against the current model." },
  { id: "refine", label: "Refine", hint: "Run the repair loop on the currently selected bundle." },
];

export default function ActionPanel({
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
}: Props) {
  const [mode, setMode] = useState<Mode>("new");

  return (
    <SectionCard
      title="Actions"
      subtitle="Create, adjust, or refine a bundle from one place."
      action={<StatusBadge label={useMock ? "Demo mode" : "LLM mode"} tone={useMock ? "warning" : "accent"} />}
    >
      <div className="space-y-4">
        <div className="grid grid-cols-3 gap-2 rounded-2xl border border-slate-800 bg-slate-950/70 p-1.5">
          {modes.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setMode(item.id)}
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

        <div className="rounded-2xl border border-slate-800 bg-slate-950/55 px-4 py-3 text-sm text-slate-300">
          <div className="font-medium text-slate-100">{modes.find((item) => item.id === mode)?.label}</div>
          <div className="mt-1 text-slate-400">{modes.find((item) => item.id === mode)?.hint}</div>
        </div>

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

        <label className="flex items-center gap-3 rounded-2xl border border-slate-800 bg-slate-950/60 px-4 py-3 text-sm text-slate-300">
          <input
            type="checkbox"
            checked={useMock}
            onChange={(event) => onUseMockChange(event.target.checked)}
            className="h-4 w-4 rounded border-slate-700 bg-slate-950 text-indigo-500"
          />
          Use deterministic mock generation for demos and UI testing
        </label>
      </div>
    </SectionCard>
  );
}
