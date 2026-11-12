/** 水平滚动条把 chip 滚到可视区中间，offset 夹在 [0, contentWidth - viewportWidth]。 */
export function centerChipScrollX(opts: {
  viewportWidth: number;
  contentWidth: number;
  chipX: number;
  chipWidth: number;
}): number {
  const maxOffset = Math.max(0, opts.contentWidth - opts.viewportWidth);
  if (maxOffset <= 0) return 0;
  const chipCenter = opts.chipX + opts.chipWidth / 2;
  return Math.min(maxOffset, Math.max(0, chipCenter - opts.viewportWidth / 2));
}
