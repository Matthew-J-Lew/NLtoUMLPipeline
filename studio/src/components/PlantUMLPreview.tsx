import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { renderPlantUML } from "../lib/api";

type Props = {
  puml: string;
  bundleName?: string;
  active: boolean;
};

type ViewportSize = {
  width: number;
  height: number;
};

type SvgDimensions = {
  width: number;
  height: number;
};

const DEBOUNCE_MS = 450;
const VIEWER_PADDING = 36;
const MIN_SCALE = 0.2;
const MAX_SCALE = 6;

function parseLength(value: string | null): number | null {
  if (!value) return null;
  const match = value.match(/-?\d*\.?\d+/);
  if (!match) return null;
  const parsed = Number(match[0]);
  return Number.isFinite(parsed) ? parsed : null;
}

function parseSvgDimensions(svg: string | null): SvgDimensions | null {
  if (!svg) return null;

  try {
    const parser = new DOMParser();
    const doc = parser.parseFromString(svg, "image/svg+xml");
    const root = doc.documentElement;

    if (!root || root.tagName.toLowerCase() !== "svg") {
      return null;
    }

    const viewBox = root.getAttribute("viewBox");
    if (viewBox) {
      const parts = viewBox
        .trim()
        .split(/[\s,]+/)
        .map((value) => Number(value));

      if (parts.length === 4 && Number.isFinite(parts[2]) && Number.isFinite(parts[3]) && parts[2] > 0 && parts[3] > 0) {
        return { width: parts[2], height: parts[3] };
      }
    }

    const width = parseLength(root.getAttribute("width"));
    const height = parseLength(root.getAttribute("height"));
    if (width && height && width > 0 && height > 0) {
      return { width, height };
    }
  } catch {
    return null;
  }

  return null;
}

function clampScale(value: number): number {
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, Number(value.toFixed(3))));
}

function normalizeSvgMarkup(svg: string, dimensions: SvgDimensions): string {
  return svg.replace(/<svg\b([^>]*)>/i, (match, attrs) => {
    const cleanedAttrs = attrs
      .replace(/\swidth=("[^"]*"|'[^']*')/i, "")
      .replace(/\sheight=("[^"]*"|'[^']*')/i, "")
      .replace(/\sstyle=("[^"]*"|'[^']*')/i, "")
      .replace(/\spreserveAspectRatio=("[^"]*"|'[^']*')/i, "");

    return `<svg${cleanedAttrs} width="${dimensions.width}" height="${dimensions.height}" preserveAspectRatio="xMidYMid meet" style="display:block; width:100%; height:100%;">`;
  });
}

export default function PlantUMLPreview({ puml, active: _active }: Props) {
  const [svg, setSvg] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [viewportEl, setViewportEl] = useState<HTMLDivElement | null>(null);
  const [viewportSize, setViewportSize] = useState<ViewportSize>({ width: 0, height: 0 });
  const renderSeq = useRef(0);

  const trimmedPuml = useMemo(() => puml.trim(), [puml]);

  const renderNow = useCallback(async () => {
    if (!trimmedPuml) {
      setSvg(null);
      setError(null);
      return;
    }

    const seq = ++renderSeq.current;
    setLoading(true);
    setError(null);

    try {
      const result = await renderPlantUML(trimmedPuml);
      if (renderSeq.current !== seq) return;
      setSvg(result.svg);
      setError(null);
    } catch (err) {
      if (renderSeq.current !== seq) return;
      setError(err instanceof Error ? err.message : "Failed to render PlantUML preview.");
    } finally {
      if (renderSeq.current === seq) {
        setLoading(false);
      }
    }
  }, [trimmedPuml]);

  useEffect(() => {
    if (!trimmedPuml) {
      setSvg(null);
      setError(null);
      setLoading(false);
      return;
    }

    const timer = window.setTimeout(() => {
      renderNow().catch(() => {
        // Errors are reflected in component state.
      });
    }, DEBOUNCE_MS);

    return () => window.clearTimeout(timer);
  }, [renderNow, trimmedPuml]);

  useEffect(() => {
    if (!viewportEl) return;

    const updateViewport = () => {
      setViewportSize({
        width: viewportEl.clientWidth,
        height: viewportEl.clientHeight,
      });
    };

    updateViewport();

    const observer = new ResizeObserver(() => {
      updateViewport();
    });

    observer.observe(viewportEl);
    return () => observer.disconnect();
  }, [viewportEl, svg]);

  const svgDimensions = useMemo(() => parseSvgDimensions(svg), [svg]);

  const fittedScale = useMemo(() => {
    if (!svgDimensions || viewportSize.width <= 0 || viewportSize.height <= 0) {
      return 1;
    }

    const availableWidth = Math.max(120, viewportSize.width - VIEWER_PADDING);
    const availableHeight = Math.max(120, viewportSize.height - VIEWER_PADDING);
    return clampScale(Math.min(availableWidth / svgDimensions.width, availableHeight / svgDimensions.height));
  }, [svgDimensions, viewportSize.height, viewportSize.width]);

  const normalizedSvg = useMemo(() => {
    if (!svg || !svgDimensions) return svg;
    return normalizeSvgMarkup(svg, svgDimensions);
  }, [svg, svgDimensions]);

  const hasDiagram = Boolean(normalizedSvg && svgDimensions);

  if (!trimmedPuml) {
    return (
      <div className="rounded-3xl border border-dashed border-slate-700 bg-slate-950/50 px-6 py-16 text-center text-slate-400">
        No PlantUML is available yet. Generate a baseline model or open an existing project first.
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-3xl border border-amber-500/30 bg-amber-500/10 p-5 text-sm text-amber-100">
        <div className="text-base font-semibold text-amber-50">PlantUML preview unavailable</div>
        <p className="mt-2 leading-6">{error}</p>
        <div className="mt-4 rounded-2xl border border-amber-500/20 bg-slate-950/30 px-4 py-3 text-xs leading-6 text-amber-50/90">
          Check the PlantUML text for syntax issues. If setup is incomplete, place <span className="font-semibold">plantuml.jar</span> at
          <span className="mx-1 font-semibold">&lt;repo&gt;/tools/plantuml.jar</span>
          and ensure Java is available on PATH. Graphviz may also be required for state-diagram rendering.
        </div>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-3xl border border-slate-800 bg-slate-950/80">
      <div className="p-5">
        <div
          ref={setViewportEl}
          className="studio-preview-viewport relative overflow-hidden rounded-[2rem] border border-slate-800 bg-white"
        >
          {loading && !hasDiagram ? (
            <div className="flex h-full items-center justify-center text-sm text-slate-400">Rendering the current PlantUML diagram…</div>
          ) : null}

          {hasDiagram && svgDimensions ? (
            <div className="absolute inset-0 flex items-center justify-center p-4">
              <div
                className="shrink-0"
                style={{
                  width: `${svgDimensions.width}px`,
                  height: `${svgDimensions.height}px`,
                  transform: `scale(${fittedScale})`,
                  transformOrigin: "center center",
                  willChange: loading ? "transform" : undefined,
                }}
                dangerouslySetInnerHTML={{ __html: normalizedSvg ?? "" }}
              />
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
