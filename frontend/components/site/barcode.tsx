/** Decorative receipt barcode drawn from the digits of the Record ID (not a scannable code). */
export function Barcode({ value, className }: { value: string; className?: string }) {
  const bars: { x: number; w: number }[] = [];
  let x = 4;
  const seed = [...value].map((c) => c.charCodeAt(0));
  const pattern = [2, 1, 3, 1, 2, 2, 1, 3, 2, 1, 1, 3];
  for (let i = 0; i < 30; i++) {
    const w = pattern[(seed[i % seed.length] + i * 7) % pattern.length];
    if (i % 2 === 0) bars.push({ x, w });
    x += w + 1;
  }
  return (
    <svg viewBox={`0 0 ${x + 4} 40`} className={className} aria-hidden preserveAspectRatio="none">
      {bars.map((b, i) => (
        <rect key={i} x={b.x} y={0} width={b.w} height={40} fill="#1c2b22" />
      ))}
    </svg>
  );
}
