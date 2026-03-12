import cls from "../utils";

type Props = {
  label: string;
  tone?: "neutral" | "success" | "warning" | "danger" | "accent";
};

const toneMap = {
  neutral: "border-slate-700 bg-slate-900 text-slate-200",
  success: "border-emerald-500/40 bg-emerald-500/10 text-emerald-200",
  warning: "border-amber-500/40 bg-amber-500/10 text-amber-200",
  danger: "border-rose-500/40 bg-rose-500/10 text-rose-200",
  accent: "border-indigo-500/40 bg-indigo-500/10 text-indigo-200",
};

export default function StatusBadge({ label, tone = "neutral" }: Props) {
  return (
    <span
      className={cls(
        "inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-medium tracking-wide",
        toneMap[tone],
      )}
    >
      {label}
    </span>
  );
}
