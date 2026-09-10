import json
import shutil
import subprocess
import unittest
from pathlib import Path
from eog_automation.rendered import CONTROL_SCRIPT

class MaskGeometryTests(unittest.TestCase):
    def test_rectangular_clips_exclude_hidden_and_partial_controls(self):
        node=shutil.which('node')
        if not node:
            try:
                import playwright
                candidate=Path(playwright.__file__).parent/'driver'/'node.exe'
                if candidate.exists():node=str(candidate)
            except ImportError:pass
        if not node:self.skipTest('Node runtime unavailable')
        fixture=r"""
const text=(label,x,y,w=20)=>({text:label,getBounds:()=>({x,y,width:w,height:10})});
const matrix={a:1,b:0,c:0,d:1,tx:40,ty:30};
const mask={context:{instructions:[{action:'fill',data:{path:{instructions:[{action:'rect',data:[0,0,100,80]}]}}}]},getGlobalTransform:()=>matrix};
const group={mask,children:[text('inside',60,50),text('outside',200,50),text('partial',130,50),{mask:{},children:[text('unknown',60,50)]},{mask:{...mask,getGlobalTransform:()=>({...matrix,b:1})},children:[text('rotated',60,50)]}]};
globalThis.__PIXI_DEVTOOLS__={app:{stage:{children:[group,text('unmasked',200,200)]},renderer:{tick:1,canvas:{isConnected:true,getBoundingClientRect:()=>({left:0,top:0,width:470,height:912})},screen:{x:0,y:0,width:470,height:912}}}};
"""
        source=fixture+'\nconst read='+CONTROL_SCRIPT+';console.log(JSON.stringify(read({x:0,y:0,width:470,height:912})));'
        result=subprocess.run([node,'-e',source],capture_output=True,text=True,check=True,timeout=10)
        self.assertEqual([r['text'] for r in json.loads(result.stdout)['rows']],['inside','unmasked'])
