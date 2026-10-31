# -*- coding: utf-8 -*-
# Add drag & resize to #frame in dump_webcam.html
import io

PATH = r"D:\Виджет OBS\dump_webcam.html"
with io.open(PATH, "r", encoding="utf-8") as f:
    src = f.read()

if 'drag-resize-v1' in src:
    print("already patched")
    raise SystemExit

# ---------- 1. CSS ----------
css_old = "*{box-sizing:border-box}html,body{width:100%;height:100%;margin:0;overflow:hidden;background:transparent;color:#f4f6fb;font:14px Segoe UI,Arial,sans-serif}#frame{position:absolute;inset:0;overflow:hidden;border-radius:var(--radius,18px);border:var(--bw,0px) solid #5dd6c0;box-shadow:0 0 var(--glow,0px) #5dd6c0}"
css_new = (
    "*{box-sizing:border-box}html,body{width:100%;height:100%;margin:0;overflow:hidden;background:transparent;color:#f4f6fb;font:14px Segoe UI,Arial,sans-serif}"
    "#frame{position:absolute;overflow:hidden;border-radius:var(--radius,18px);border:var(--bw,0px) solid #5dd6c0;box-shadow:0 0 var(--glow,0px) #5dd6c0}"
    "/* drag-resize-v1 */#frame{cursor:grab}#frame.dragging{cursor:grabbing}"
)
assert css_old in src, "CSS anchor not found"
src = src.replace(css_old, css_new, 1)

# ---------- 2. Body: handles inside #frame ----------
body_old = '<div id="frame" class="" style="--bw: 0px; --glow: 0px; border-radius: 24px;">'
assert body_old in src, "BODY anchor not found"

# ---------- 3. JS ----------
iife_old = "let settings={},stream=null,timer=0;try{settings=JSON.parse(localStorage.getItem(key)||'{}')}catch(_){}"
iife_new = iife_old + """
/* drag-resize-v1: JS-driven edge/corner detection (works despite rounded clip) */
const MIN_W=160,MIN_H=120;
const EDGE=14,CORNER=18;
let dragging=false,resizing=null,dragStart=null,edgeDir=null;
function setGeom(g){frame.style.left=g.x+'px';frame.style.top=g.y+'px';frame.style.width=g.w+'px';frame.style.height=g.h+'px'}
function initGeom(){
  let g=null;
  try{if(settings.geom&&settings.geom.w)g=settings.geom}catch(_){}
  if(!g){const W=window.innerWidth,H=window.innerHeight;g={x:0,y:0,w:Math.round(W*0.25),h:Math.round(H*0.45)}}
  setGeom(g);
}
function geomNow(){const r=frame.getBoundingClientRect();return{x:Math.round(r.left),y:Math.round(r.top),w:Math.round(r.width),h:Math.round(r.height)}}
function saveGeom(){try{settings.geom=geomNow();localStorage.setItem(key,JSON.stringify(settings))}catch(_){}}
function dirAt(px,py){
  const r=frame.getBoundingClientRect(),lx=px-r.left,ly=py-r.top;
  const nearW=(lx<=EDGE),nearE=((r.width-lx)<=EDGE),nearT=(ly<=EDGE),nearB=((r.height-ly)<=EDGE);
  if(nearW&&nearT)return'nw';if(nearE&&nearT)return'ne';if(nearW&&nearB)return'sw';if(nearE&&nearB)return'se';
  let d='';
  if(nearT)d+='n';if(nearB)d+='s';if(nearW)d+='w';if(nearE)d+='e';
  return d||null;
}
initGeom();
frame.addEventListener('pointermove',e=>{
  if(dragging||resizing)return;
  edgeDir=dirAt(e.clientX,e.clientY);
  frame.dataset.rz=edgeDir||'';
  frame.style.cursor=edgeDir
    ?(edgeDir.length===2
      ?((edgeDir==='nw'||edgeDir==='se')?'nwse-resize':'nesw-resize')
      :(edgeDir==='n'||edgeDir==='s')?'ns-resize':(edgeDir==='w'||edgeDir==='e')?'ew-resize':'grab')
    :'grab';
});
frame.addEventListener('pointerleave',()=>{if(!dragging&&!resizing){frame.dataset.rz='';frame.style.cursor='grab';edgeDir=null}});
frame.addEventListener('pointerdown',e=>{
  if(e.target.closest('#panel')||e.target.closest('#settings'))return;
  const d=dirAt(e.clientX,e.clientY);
  dragStart={mx:e.clientX,my:e.clientY,g:geomNow()};
  if(d){resizing=d;frame.style.cursor='grabbing'}
  else{dragging=true;frame.classList.add('dragging');frame.style.cursor='grabbing'}
  frame.setPointerCapture(e.pointerId);e.preventDefault();
});
window.addEventListener('pointermove',e=>{
  if(!dragging&&!resizing)return;
  if(!dragStart)return;
  if(dragging){
    setGeom({x:dragStart.g.x+(e.clientX-dragStart.mx),y:dragStart.g.y+(e.clientY-dragStart.my),w:dragStart.g.w,h:dragStart.g.h});
  }else{
    const g=dragStart.g,dx=e.clientX-dragStart.mx,dy=e.clientY-dragStart.my;
    let{x,y,w,h}=g;
    if(resizing.includes('e'))w=g.w+dx;
    if(resizing.includes('s'))h=g.h+dy;
    if(resizing.includes('w')){x=g.x+dx;w=g.w-dx}
    if(resizing.includes('n')){y=g.y+dy;h=g.h-dy}
    if(w<MIN_W){if(resizing.includes('w'))x-=(MIN_W-w);w=MIN_W}
    if(h<MIN_H){if(resizing.includes('n'))y-=(MIN_H-h);h=MIN_H}
    setGeom({x,y,w,h});
  }
});
window.addEventListener('pointerup',()=>{
  if(dragging||resizing){dragging=false;dragStart=null;frame.classList.remove('dragging');frame.style.cursor='grab';resizing=null;saveGeom();}
});
window.__rz=()=>({dragging,resizing,hasStart:!!dragStart});window.__rzOn=1;"""
assert iife_old in src, "IIFE anchor not found"
src = src.replace(iife_old, iife_new, 1)

with io.open(PATH, "w", encoding="utf-8") as f:
    f.write(src)
print("patched OK")
