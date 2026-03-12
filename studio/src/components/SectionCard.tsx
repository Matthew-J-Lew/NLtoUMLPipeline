import type { ReactNode } from "react";
import cls from "../utils";

type Props = {
  title: string;
  subtitle?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
};

export default function SectionCard({ title, subtitle, action, children, className }: Props) {
  return (
    <section className={cls("rounded-3xl border border-slate-800 bg-slate-900/70 shadow-panel", className)}>
      <div className="flex items-start justify-between gap-4 border-b border-slate-800 px-5 py-4">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-200">{title}</h2>
          {subtitle ? <p className="mt-1 text-sm text-slate-400">{subtitle}</p> : null}
        </div>
        {action}
      </div>
      <div className="px-5 py-4">{children}</div>
    </section>
  );
}
