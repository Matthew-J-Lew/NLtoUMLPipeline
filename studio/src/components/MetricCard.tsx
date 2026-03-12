import cls from "../utils";

type Props = {
  label: string;
  value: string | number;
  hint?: string;
  tone?: "default" | "success" | "danger" | "accent";
};

const toneClasses = {
  default: "from-slate-900 to-slate-900/60 border-slate-800",
  success: "from-emerald-500/10 to-slate-900/80 border-emerald-500/30",
  danger: "from-rose-500/10 to-slate-900/80 border-rose-500/30",
  accent: "from-indigo-500/10 to-slate-900/80 border-indigo-500/30",
};

export default function MetricCard({ label, value, hint, tone = "default" }: Props) {
  return (
    <div className={cls("rounded-2xl border bg-gradient-to-b p-4", toneClasses[tone])}>
      <div className="text-[11px] uppercase tracking-[0.18em] text-slate-400">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-slate-50">{value}</div>
      {hint ? <div className="mt-2 text-sm text-slate-400">{hint}</div> : null}
    </div>
  );
}
