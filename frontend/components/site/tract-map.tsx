"use client";

import { geoCircle, geoMercator, geoPath } from "d3-geo";
import { select } from "d3-selection";
import { zoom as d3zoom, zoomIdentity, type ZoomBehavior } from "d3-zoom";
import { Minus, Plus } from "lucide-react";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { displayName } from "@/lib/format";
import { classify, type ShadeMode } from "@/lib/shading";
import type { Row } from "@/lib/derived";
import type { Tier, TractsFile } from "@/lib/types";

const W = 800;
const H = 1000;
const MILE_DEG = (1609.344 / 6371008.8) * (180 / Math.PI); // 1 mile as degrees of arc on the sphere

const DOT: Record<Tier | "none", { fill: string; stroke: string; r: number }> = {
  high: { fill: "#b23a12", stroke: "#7a2509", r: 7 },
  medium: { fill: "#d9a441", stroke: "#8a5a06", r: 6 },
  low: { fill: "#fffdf7", stroke: "#4a5a50", r: 5 },
  none: { fill: "#e1dbcf", stroke: "#6f7d73", r: 5 },
};

interface Props {
  tracts: TractsFile;
  mode: ShadeMode;
  rows?: Row[];
  selectedId?: string | null;
  /** record ids that match the current search; others are dimmed. undefined = no filter */
  matchIds?: Set<string>;
  onSelect?: (id: string) => void;
  /** hero: a decorative, non-interactive backdrop cropped to fill its box */
  decorative?: boolean;
  className?: string;
}

export function TractMap({ tracts, mode, rows = [], selectedId, matchIds, onSelect, decorative, className }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const zoomRef = useRef<ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const [t, setT] = useState({ k: 1, x: 0, y: 0 });
  const hatchId = useId().replace(/:/g, "");

  const projection = useMemo(() => geoMercator().fitExtent([[12, 12], [W - 12, H - 12]], tracts as never), [tracts]);
  const pathGen = useMemo(() => geoPath(projection), [projection]);
  const paths = useMemo(
    () =>
      tracts.features.map((f) => ({
        id: f.properties.geoid,
        d: pathGen(f as never) ?? "",
        cls: classify(f.properties, mode),
        name: f.properties.name,
      })),
    [tracts, pathGen, mode],
  );
  const pts = useMemo(
    () =>
      rows
        .filter((r) => r.store.lat != null && r.store.lon != null)
        .map((r) => {
          const [x, y] = projection([r.store.lon!, r.store.lat!]) ?? [0, 0];
          return { r, x, y };
        }),
    [rows, projection],
  );
  const selected = pts.find((p) => p.r.store.record_id === selectedId);
  const ring = useMemo(() => {
    if (!selected) return null;
    const c = geoCircle().center([selected.r.store.lon!, selected.r.store.lat!]).radius(MILE_DEG).precision(2)();
    return pathGen(c as never);
  }, [selected, pathGen]);

  useEffect(() => {
    if (decorative || !svgRef.current) return;
    const svg = select(svgRef.current);
    const z = d3zoom<SVGSVGElement, unknown>()
      .scaleExtent([1, 14])
      .translateExtent([[0, 0], [W, H]])
      .on("zoom", (e) => setT({ k: e.transform.k, x: e.transform.x, y: e.transform.y }));
    svg.call(z);
    svg.on("dblclick.zoom", null);
    zoomRef.current = z;
    return () => {
      svg.on(".zoom", null);
    };
  }, [decorative]);

  const zoomBy = useCallback((f: number) => {
    if (svgRef.current && zoomRef.current) select(svgRef.current).call(zoomRef.current.scaleBy, f);
  }, []);

  // keep the selected store in view when it changes (e.g. picked from the list)
  useEffect(() => {
    if (!selected || !svgRef.current || !zoomRef.current) return;
    const sx = selected.x * t.k + t.x;
    const sy = selected.y * t.k + t.y;
    if (sx < 60 || sx > W - 60 || sy < 60 || sy > H - 60) {
      const k = Math.max(t.k, 3);
      select(svgRef.current).call(zoomRef.current.transform, zoomIdentity.translate(W / 2 - selected.x * k, H / 2 - selected.y * k).scale(k));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  const tf = `translate(${t.x} ${t.y}) scale(${t.k})`;
  const pos = selected ? { left: ((selected.x * t.k + t.x) / W) * 100, top: ((selected.y * t.k + t.y) / H) * 100 } : null;

  return (
    <div className={`relative ${className ?? ""}`}>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio={decorative ? "xMidYMid slice" : "xMidYMid meet"}
        className={`h-full w-full ${decorative ? "" : "cursor-grab touch-none active:cursor-grabbing"}`}
        role={decorative ? "presentation" : "img"}
        aria-hidden={decorative || undefined}
        aria-label={decorative ? undefined : "Map of Mecklenburg County census tracts with SNAP grocery stores. Use the store list for keyboard access."}
      >
        <defs>
          {/* "not enough data" tracts: a light hatch, so they read as unknown rather than as a low value */}
          <pattern id={hatchId} width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="7" height="7" fill="#f4efe3" />
            <line x1="0" y1="0" x2="0" y2="7" stroke="#cfc6b0" strokeWidth="2" />
          </pattern>
        </defs>
        <g transform={tf}>
          {paths.map((p) => (
            <path key={p.id} d={p.d} fill={p.cls.kind === "low_data" ? `url(#${hatchId})` : p.cls.color} stroke="#fffdf7" strokeWidth={0.8 / t.k} vectorEffect="non-scaling-stroke">
              {!decorative && <title>{`${p.name}: ${p.cls.label}`}</title>}
            </path>
          ))}
          {!decorative && ring && <path d={ring} fill="none" stroke="#1c2b22" strokeWidth={1.5} strokeDasharray="5 4" vectorEffect="non-scaling-stroke" />}
          {!decorative &&
            pts.map(({ r, x, y }) => {
              const d = DOT[r.pred?.tier ?? "none"];
              const dim = matchIds && !matchIds.has(r.store.record_id);
              const isSel = r.store.record_id === selectedId;
              return (
                <g key={r.store.record_id} opacity={dim ? 0.25 : 1}>
                <circle cx={x} cy={y} r={((isSel ? d.r + 2 : d.r) + 2.5) / Math.sqrt(t.k)} fill="#fffdf7" opacity={0.9} onClick={() => onSelect?.(r.store.record_id)} className="cursor-pointer" aria-hidden />
                <circle
                  cx={x}
                  cy={y}
                  r={(isSel ? d.r + 2 : d.r) / Math.sqrt(t.k)}
                  fill={d.fill}
                  stroke={isSel ? "#1c2b22" : d.stroke}
                  strokeWidth={(isSel ? 2.5 : 1.5) / Math.sqrt(t.k)}
                  strokeDasharray={r.pred ? undefined : "2 2"}
                  className="cursor-pointer"
                  onClick={() => onSelect?.(r.store.record_id)}
                  aria-hidden
                />
                </g>
              );
            })}
        </g>
      </svg>
      {!decorative && selected && pos && (
        <div
          className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-[150%] whitespace-nowrap rounded-sm bg-ink px-2 py-1 text-xs text-paper-light"
          style={{ left: `${pos.left}%`, top: `${pos.top}%` }}
        >
          {displayName(selected.r.store.name)}
          {selected.r.pred ? ` · ${Math.round(selected.r.pred.probability * 100 * 10) / 10}%` : " · not scored"}
        </div>
      )}
      {!decorative && (
        <div className="absolute right-3 top-3 flex flex-col border border-rule bg-paper-light">
          <button type="button" aria-label="Zoom in" className="grid size-11 place-items-center border-b border-rule hover:bg-paper" onClick={() => zoomBy(1.6)}>
            <Plus className="size-4" aria-hidden />
          </button>
          <button type="button" aria-label="Zoom out" className="grid size-11 place-items-center hover:bg-paper" onClick={() => zoomBy(1 / 1.6)}>
            <Minus className="size-4" aria-hidden />
          </button>
        </div>
      )}
    </div>
  );
}
