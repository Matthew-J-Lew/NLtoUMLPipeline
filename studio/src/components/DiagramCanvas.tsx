import type { IR, Transition } from "../types";
import SectionCard from "./SectionCard";

const WIDTH = 920;
const HEIGHT = 420;
const NODE_RADIUS = 38;

function polar(index: number, total: number, radius: number) {
  const angle = (Math.PI * 2 * index) / Math.max(total, 1) - Math.PI / 2;
  return {
    x: WIDTH / 2 + Math.cos(angle) * radius,
    y: HEIGHT / 2 + Math.sin(angle) * radius,
  };
}

function summarizeTransition(transition: Transition): string {
  const trigger = transition.triggers?.[0] as Record<string, unknown> | undefined;
  const action = transition.actions?.[0] as Record<string, unknown> | undefined;
  const parts: string[] = [];

  if (trigger?.type === "after") {
    parts.push(`after ${trigger.seconds}s`);
  } else if (trigger?.type === "becomes") {
    const ref = trigger.ref as Record<string, unknown> | undefined;
    const value = trigger.value as Record<string, unknown> | undefined;
    parts.push(`${String(ref?.device ?? "device")}.${String(ref?.path ?? "attr")} → ${String(value?.string ?? value?.number ?? value?.bool ?? "value")}`);
  } else if (trigger?.type) {
    parts.push(String(trigger.type));
  }

  if (action?.type === "command") {
    parts.push(`${String(action.device ?? "device")}.${String(action.command ?? "cmd")}()`);
  } else if (action?.type) {
    parts.push(String(action.type));
  }

  return parts.join(" · ") || "transition";
}

type Props = {
  ir?: IR | null;
};

export default function DiagramCanvas({ ir }: Props) {
  const states = ir?.stateMachine?.states ?? [];
  const transitions = ir?.stateMachine?.transitions ?? [];
  const initial = ir?.stateMachine?.initial;
  const nodes = states.map((state, index) => ({
    state,
    ...polar(index, states.length, Math.min(WIDTH, HEIGHT) * 0.32),
  }));

  const lookup = new Map(nodes.map((node) => [node.state.id, node]));

  return (
    <SectionCard
      title="Model canvas"
      subtitle="A lightweight state-machine preview generated from the canonical IR."
    >
      {states.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-slate-700 bg-slate-950/50 px-6 py-12 text-center text-slate-400">
          Run the pipeline to render a state graph, inspect transitions, and edit the generated PlantUML.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-3xl border border-slate-800 bg-grid bg-[size:28px_28px] bg-slate-950/80 p-3">
          <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="h-[420px] min-w-[760px] w-full">
            <defs>
              <marker
                id="arrow"
                markerWidth="10"
                markerHeight="10"
                refX="9"
                refY="3"
                orient="auto"
                markerUnits="strokeWidth"
              >
                <path d="M0,0 L0,6 L9,3 z" fill="#818cf8" />
              </marker>
            </defs>

            {transitions.map((transition, index) => {
              const from = lookup.get(transition.from);
              const to = lookup.get(transition.to);
              if (!from || !to) return null;

              const dx = to.x - from.x;
              const dy = to.y - from.y;
              const len = Math.sqrt(dx * dx + dy * dy) || 1;
              const ux = dx / len;
              const uy = dy / len;
              const startX = from.x + ux * NODE_RADIUS;
              const startY = from.y + uy * NODE_RADIUS;
              const endX = to.x - ux * NODE_RADIUS;
              const endY = to.y - uy * NODE_RADIUS;
              const midX = (startX + endX) / 2 + uy * (18 + (index % 3) * 10);
              const midY = (startY + endY) / 2 - ux * (18 + (index % 3) * 10);
              const label = summarizeTransition(transition);

              return (
                <g key={`${transition.from}-${transition.to}-${index}`}>
                  <path
                    d={`M ${startX} ${startY} Q ${midX} ${midY} ${endX} ${endY}`}
                    fill="none"
                    stroke="#818cf8"
                    strokeWidth="2"
                    markerEnd="url(#arrow)"
                    opacity="0.95"
                  />
                  <rect
                    x={midX - 92}
                    y={midY - 16}
                    width="184"
                    height="32"
                    rx="12"
                    fill="rgba(15,23,42,0.92)"
                    stroke="rgba(99,102,241,0.35)"
                  />
                  <text
                    x={midX}
                    y={midY + 5}
                    fontSize="11"
                    textAnchor="middle"
                    fill="#e2e8f0"
                  >
                    {label.length > 34 ? `${label.slice(0, 31)}...` : label}
                  </text>
                </g>
              );
            })}

            {nodes.map(({ state, x, y }) => (
              <g key={state.id}>
                {state.id === initial ? (
                  <circle cx={x} cy={y} r={NODE_RADIUS + 10} fill="rgba(99,102,241,0.10)" stroke="#6366f1" strokeDasharray="5 6" />
                ) : null}
                <circle cx={x} cy={y} r={NODE_RADIUS} fill="#0f172a" stroke="#94a3b8" strokeWidth="2" />
                <text x={x} y={y + 4} fontSize="13" textAnchor="middle" fill="#f8fafc" fontWeight={600}>
                  {state.id}
                </text>
              </g>
            ))}
          </svg>
        </div>
      )}
    </SectionCard>
  );
}
