export function saggingString(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
): { path: string; midX: number; midY: number } {
  const dist = Math.hypot(x2 - x1, y2 - y1);
  const sag = Math.min(64, Math.max(18, dist * 0.2));
  const cx = (x1 + x2) / 2;
  const cy = (y1 + y2) / 2 + sag;
  return {
    path: `M ${x1} ${y1} Q ${cx} ${cy} ${x2} ${y2}`,
    midX: cx,
    midY: (y1 + y2) / 2 + sag / 2,
  };
}
