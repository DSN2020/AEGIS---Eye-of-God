"""Single-line visible controls; wrapped prose is not used as action evidence."""
import asyncio
import math
from ev_assistant.rendered_text import READ_SCRIPT
from .vision import TextLine

# Only plain, axis-aligned rectangular masks are supported. Text must fit
# inside every ancestor clip; unknown masks retain the OCR fallback.
CONTROL_SCRIPT = READ_SCRIPT.replace(
    'function visit(node, depth, parentAlpha = 1) {',
    'function visit(node, depth, parentAlpha = 1, area = clip) {').replace(
    'if (node.mask) return;', r"""
    if (node.mask) {
      const mask = node.mask.mask || node.mask;
      const fills = mask.context?.instructions;
      if (!Array.isArray(fills) || fills.length !== 1 || fills[0].action !== 'fill') return;
      const paths = fills[0].data?.path?.instructions;
      if (!Array.isArray(paths) || paths.length !== 1 || paths[0].action !== 'rect') return;
      const [mx,my,mw,mh,draw] = paths[0].data;
      const matrix = typeof mask.getGlobalTransform === 'function' ? mask.getGlobalTransform() : mask.worldTransform;
      const local = draw || {a:1,b:0,c:0,d:1,tx:0,ty:0};
      if (!matrix || [mx,my,mw,mh,matrix.a,matrix.b,matrix.c,matrix.d,matrix.tx,matrix.ty,local.a,local.b,local.c,local.d,local.tx,local.ty].some(v=>!Number.isFinite(v))) return;
      if (mw<=0 || mh<=0 || Math.abs(matrix.b)+Math.abs(matrix.c)+Math.abs(local.b)+Math.abs(local.c)>0.001) return;
      const x1 = rect.left+(((mx*local.a+local.tx)*matrix.a+matrix.tx)-screen.x)*sx;
      const x2 = rect.left+((((mx+mw)*local.a+local.tx)*matrix.a+matrix.tx)-screen.x)*sx;
      const y1 = rect.top+(((my*local.d+local.ty)*matrix.d+matrix.ty)-screen.y)*sy;
      const y2 = rect.top+((((my+mh)*local.d+local.ty)*matrix.d+matrix.ty)-screen.y)*sy;
      const left=Math.max(area.x,Math.min(x1,x2)),right=Math.min(area.x+area.width,Math.max(x1,x2));
      const top=Math.max(area.y,Math.min(y1,y2)),bottom=Math.min(area.y+area.height,Math.max(y1,y2));
      if(right<=left||bottom<=top)return;
      area={x:left,y:top,width:right-left,height:bottom-top};
    }
    """).replace(
    'if (b.width > 0 && b.height > 0 && x >= clip.x',
    'if (rect.left+(b.x-screen.x)*sx >= area.x-0.5 && rect.left+(b.x+b.width-screen.x)*sx <= area.x+area.width+0.5 && rect.top+(b.y-screen.y)*sy >= area.y-0.5 && rect.top+(b.y+b.height-screen.y)*sy <= area.y+area.height+0.5 && b.width > 0 && b.height > 0 && x >= clip.x').replace(
    'visit(child, depth + 1, alpha)', 'visit(child, depth + 1, alpha, area)')

async def read_controls(page):
    try:
        result=await asyncio.wait_for(page.evaluate(CONTROL_SCRIPT,{'x':0,'y':0,'width':470,'height':912}),2)
        if not isinstance(result,dict) or type(result.get('frame')) is not int or result['frame']<=0:return None
        lines=[]
        for row in result['rows']:
            value,x,y=row['text'],row['x'],row['y']
            if not isinstance(value,str) or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in (x,y)):return None
            if '\n' in value.strip() or '<' in value or '>' in value:continue
            if any(l.text==value and abs(l.x-x)<=2 and abs(l.y-y)<=2 for l in lines):continue
            lines.append(TextLine(value,1,x,y))
        return lines or None
    except Exception:return None
