import type { ValidationReport } from "../types";
import SectionCard from "./SectionCard";
import StatusBadge from "./StatusBadge";

const toneMap: Record<string, "success" | "warning" | "danger" | "neutral"> = {
  error: "danger",
  warning: "warning",
  info: "neutral",
};

type Props = {
  report?: ValidationReport | null;
};

export default function ValidationPanel({ report }: Props) {
  const diagnostics = report?.diagnostics ?? [];
  const ok = report?.ok === true;

  return (
    <SectionCard
      title="Validation"
      subtitle="Deterministic checks, typed diagnostics, and repair visibility."
      action={<StatusBadge label={ok ? "PASS" : diagnostics.length ? "REVIEW" : "PENDING"} tone={ok ? "success" : diagnostics.length ? "warning" : "neutral"} />}
    >
      {diagnostics.length === 0 ? (
        <div className="rounded-2xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-4 text-sm text-emerald-100">
          No current diagnostics. The current canonical IR passed the deterministic validator.
        </div>
      ) : (
        <div className="space-y-3">
          {diagnostics.map((diag, index) => (
            <div key={`${diag.code ?? "diag"}-${index}`} className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
              <div className="mb-2 flex items-center justify-between gap-3">
                <StatusBadge label={(diag.severity ?? "info").toUpperCase()} tone={toneMap[diag.severity ?? "info"]} />
                {diag.code ? <span className="font-mono text-xs text-slate-500">{diag.code}</span> : null}
              </div>
              <p className="text-sm text-slate-100">{diag.message ?? "No message provided."}</p>
              {diag.path ? <p className="mt-2 font-mono text-xs text-slate-500">{diag.path}</p> : null}
            </div>
          ))}
        </div>
      )}
    </SectionCard>
  );
}
