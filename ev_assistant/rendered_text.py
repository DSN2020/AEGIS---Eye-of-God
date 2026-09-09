"""Read displayed Pixi text; never query game state or change rendering."""
import asyncio
import math
from .vision import TextLine

READ_SCRIPT = r"""
(clip) => {
  const dev = globalThis.__PIXI_DEVTOOLS__;
  const app = dev?.app;
  const stage = app?.stage || dev?.stage, renderer = app?.renderer || dev?.renderer;
  if (!stage || !renderer || !Number.isInteger(renderer.tick) || renderer.tick <= 0) return null;
  const canvas = renderer.canvas;
  if (!canvas?.isConnected) return null;
  const rect = canvas.getBoundingClientRect(), screen = renderer.screen;
  if (rect.width <= 0 || rect.height <= 0 || screen.width <= 0 || screen.height <= 0) return null;
  const sx = rect.width / screen.width, sy = rect.height / screen.height;
  const rows = [];
  let visited = 0;
  function visit(node, depth, parentAlpha = 1) {
    if (++visited > 20000 || depth > 80) throw new Error('Scene limit');
    const alpha = parentAlpha * (typeof node.alpha === 'number' ? node.alpha : 1);
    if (node.visible === false || node.renderable === false || alpha < 0.5 || node.worldAlpha === 0) return;
    // Masked text could be outside its visible aperture; use OCR for it.
    if (node.mask) return;
    if (typeof node.text === 'string' && node.text.trim()) {
      const b = node.getBounds();
      const x = rect.left + (b.x + b.width / 2 - screen.x) * sx;
      const y = rect.top + (b.y + b.height / 2 - screen.y) * sy;
      if (b.width > 0 && b.height > 0 && x >= clip.x && x <= clip.x + clip.width && y >= clip.y && y <= clip.y + clip.height) {
        rows.push({text: node.text, x, y});
      }
    }
    for (const child of node.children || []) visit(child, depth + 1, alpha);
  }
  visit(stage, 0);
  return {frame: renderer.tick, rows};
}
"""


async def read_rendered_text(page, clip):
    try:
        result = await asyncio.wait_for(page.evaluate(READ_SCRIPT, clip), timeout=2)
        if not isinstance(result, dict) or type(result.get('frame')) is not int or result['frame'] <= 0:
            return None
        lines = []
        for row in result['rows']:
            text, x, y = row['text'], row['x'], row['y']
            if not isinstance(text, str) or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (x, y)):
                return None
            # Multi-line blocks need individual row geometry. OCR supplies it.
            if '\n' in text.strip() or '<' in text or '>' in text:
                return None
            # Pixi draws outlined labels twice at the same location.
            if any(line.text == text and abs(line.x-x) <= 2 and abs(line.y-y) <= 2 for line in lines):
                continue
            lines.append(TextLine(text, 1.0, x, y))
        return (result['frame'], lines) if lines else None
    except Exception:
        # A game update or missing renderer hook must leave OCR available.
        return None
