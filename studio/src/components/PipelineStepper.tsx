import cls from "../utils";

const steps = [
  "Spec",
  "NL→IR",
  "Validate",
  "Review",
  "Round-trip",
  "Refine",
  "Export",
];

type Props = {
  activeIndex?: number;
  ok?: boolean | null;
};

export default function PipelineStepper({ activeIndex = 3, ok }: Props) {
  return (
    <div className="grid gap-3 md:grid-cols-7">
      {steps.map((step, index) => {
        const isComplete = index < activeIndex;
        const isActive = index === activeIndex;
        const hasError = step === "Validate" && ok === false;

        return (
          <div
            key={step}
            className={cls(
              "rounded-2xl border px-3 py-3 text-center",
              isActive && "border-indigo-500/60 bg-indigo-500/10",
              isComplete && !isActive && "border-emerald-500/40 bg-emerald-500/10",
              !isComplete && !isActive && "border-slate-800 bg-slate-950/70",
              hasError && "border-rose-500/50 bg-rose-500/10",
            )}
          >
            <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.22em] text-slate-400">
              Stage {index + 1}
            </div>
            <div className="text-sm font-medium text-slate-100">{step}</div>
          </div>
        );
      })}
    </div>
  );
}
