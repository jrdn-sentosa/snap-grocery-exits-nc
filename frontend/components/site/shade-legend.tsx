import { LOW_DATA_COLOR, MODE_TITLE, NO_SNAP_COLOR, SCALE_LABELS, SHADE_COLORS, type ShadeMode } from "@/lib/shading";

export function ShadeLegend({ mode, className }: { mode: ShadeMode; className?: string }) {
  return (
    <div className={`border border-ink bg-paper-light px-3 py-2 ${className ?? ""}`}>
      <p className="label-mono text-[0.625rem] text-ink-2">{MODE_TITLE[mode]}</p>
      <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
        <span className="flex items-center gap-1.5">
          Fewer
          <span className="flex" role="img" aria-label={`Scale from fewer to more: ${SCALE_LABELS[mode].join(", ")}`}>
            {SHADE_COLORS.map((c, i) => (
              <span key={c} title={SCALE_LABELS[mode][i]} className="h-3.5 w-6 border border-paper-light" style={{ background: c }} />
            ))}
          </span>
          More
        </span>
        {mode === "exits" && (
          <>
            <span className="flex items-center gap-1.5">
              <span className="size-3.5 border border-rule" style={{ background: NO_SNAP_COLOR }} /> No SNAP grocery
            </span>
            <span className="flex items-center gap-1.5">
              <span className="size-3.5 border border-rule" style={{ background: `repeating-linear-gradient(45deg, ${LOW_DATA_COLOR} 0 3px, #cfc6b0 3px 5px)` }} /> Not enough data
            </span>
          </>
        )}
      </div>
    </div>
  );
}
