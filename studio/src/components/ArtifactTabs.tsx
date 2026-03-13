import { useMemo, useState } from "react";
import type { ProjectSnapshot } from "../types";
import DiagramCanvas from "./DiagramCanvas";
import PlantUMLPreview from "./PlantUMLPreview";
import SectionCard from "./SectionCard";

type Props = {
  project?: ProjectSnapshot | null;
  pumlDraft: string;
  onPumlDraftChange: (value: string) => void;
  onRoundTrip: () => void;
  roundTripDisabled?: boolean;
};

const tabs = ["Diagram", "IR Graph", "PlantUML", "Current IR", "Diff"] as const;
type Tab = (typeof tabs)[number];

export default function ArtifactTabs({
  project,
  pumlDraft,
  onPumlDraftChange,
  onRoundTrip,
  roundTripDisabled,
}: Props) {
  const [activeTab, setActiveTab] = useState<Tab>("Diagram");

  const tabBody = useMemo(() => {
    if (!project) return "";
    if (activeTab === "PlantUML") return pumlDraft;
    if (activeTab === "Current IR") return JSON.stringify(project.current.ir ?? {}, null, 2);
    return JSON.stringify(project.current.diff ?? {}, null, 2);
  }, [activeTab, project, pumlDraft]);

  return (
    <SectionCard
      title="Model workspace"
      subtitle="Render the actual PlantUML artifact, keep the IR graph as a fallback, and inspect the canonical outputs."
      action={
        activeTab === "PlantUML" ? (
          <button
            type="button"
            onClick={onRoundTrip}
            disabled={roundTripDisabled}
            className="rounded-full border border-indigo-500/50 bg-indigo-500/10 px-4 py-2 text-xs font-medium text-indigo-100 transition hover:bg-indigo-500/20 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Round-trip PlantUML
          </button>
        ) : null
      }
    >
      <div className="mb-4 flex flex-wrap gap-2">
        {tabs.map((tab) => (
          <button
            key={tab}
            type="button"
            onClick={() => setActiveTab(tab)}
            className={`rounded-full px-3 py-2 text-sm transition ${
              activeTab === tab ? "bg-indigo-500/15 text-indigo-100" : "bg-slate-950/70 text-slate-400 hover:text-slate-200"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {activeTab === "Diagram" ? (
        <PlantUMLPreview puml={pumlDraft} bundleName={project?.bundle_name} active={activeTab === "Diagram"} />
      ) : null}

      {activeTab === "IR Graph" ? <DiagramCanvas ir={project?.current.ir} /> : null}

      {activeTab === "PlantUML" ? (
        <textarea
          value={pumlDraft}
          onChange={(event) => onPumlDraftChange(event.target.value)}
          className="h-[620px] w-full rounded-2xl border border-slate-800 bg-slate-950/80 p-4 font-mono text-sm text-slate-100 outline-none transition focus:border-indigo-500/60"
          spellCheck={false}
        />
      ) : null}

      {activeTab === "Current IR" || activeTab === "Diff" ? (
        <pre className="h-[620px] overflow-auto rounded-2xl border border-slate-800 bg-slate-950/80 p-4 font-mono text-sm text-slate-100">
          {tabBody || "{}"}
        </pre>
      ) : null}
    </SectionCard>
  );
}
