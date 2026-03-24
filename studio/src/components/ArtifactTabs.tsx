import { useEffect, useMemo, useState } from "react";
import type { ProjectSnapshot } from "../types";
import DiagramCanvas from "./DiagramCanvas";
import PlantUMLPreview from "./PlantUMLPreview";
import SectionCard from "./SectionCard";

type Props = {
  project?: ProjectSnapshot | null;
  pumlDraft: string;
  editorModeActive?: boolean;
};

const tabs = ["Diagram", "IR Graph", "Current IR", "Diff"] as const;
type Tab = (typeof tabs)[number];

export default function ArtifactTabs({ project, pumlDraft, editorModeActive = false }: Props) {
  const [activeTab, setActiveTab] = useState<Tab>("Diagram");

  useEffect(() => {
    if (editorModeActive) {
      setActiveTab("Diagram");
    }
  }, [editorModeActive]);

  const tabBody = useMemo(() => {
    if (!project) return "";
    if (activeTab === "Current IR") return JSON.stringify(project.current.ir ?? {}, null, 2);
    return JSON.stringify(project.current.diff ?? {}, null, 2);
  }, [activeTab, project]);

  return (
    <SectionCard
      title="Model workspace"
      subtitle={
        editorModeActive
          ? "Manual PlantUML edit mode is active in the left column. Your changes are automatically applied and rendered in the panel below."
          : "Inspect the rendered PlantUML diagram and canonical outputs below."
      }
      className="transition-all duration-300"
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

      {activeTab === "Current IR" || activeTab === "Diff" ? (
        <pre className="h-[620px] overflow-auto rounded-2xl border border-slate-800 bg-slate-950/80 p-4 font-mono text-sm text-slate-100">
          {tabBody || "{}"}
        </pre>
      ) : null}
    </SectionCard>
  );
}
