import {useEffect,useRef} from 'react';

const MAX_POINTS=6000;
const FADE_IN_MS=1100; // a freshly captured point glows, then settles to a dim resting dot

type Dot={p:number[],t:number};

export default function TrackVisualizer({active,newPoints,complete,retakeId}:{active:boolean,newPoints:number[][],complete:boolean,retakeId?:number}){
 const canvasRef=useRef<HTMLCanvasElement>(null);
 const pointsRef=useRef<Dot[]>([]);
 const wasActiveRef=useRef(false);
 const completeAtRef=useRef<number|null>(null);
 const startRef=useRef(performance.now());
 const retakeRef=useRef(retakeId);

 useEffect(()=>{
  if(active&&!wasActiveRef.current){pointsRef.current=[];completeAtRef.current=null;startRef.current=performance.now()}
  wasActiveRef.current=active;
 },[active]);

 // A retried lap has no boundary of its own in this live preview, so the
 // point cloud can't drop just its points - clear the whole display instead.
 useEffect(()=>{
  if(retakeId!=null&&retakeId!==retakeRef.current){pointsRef.current=[];completeAtRef.current=null}
  retakeRef.current=retakeId;
 },[retakeId]);

 useEffect(()=>{
  if(newPoints&&newPoints.length){
   const t=performance.now();
   for(const p of newPoints)pointsRef.current.push({p,t});
   if(pointsRef.current.length>MAX_POINTS)pointsRef.current.splice(0,pointsRef.current.length-MAX_POINTS);
  }
 },[newPoints]);

 useEffect(()=>{if(complete&&completeAtRef.current==null)completeAtRef.current=performance.now();if(!complete)completeAtRef.current=null},[complete]);

 useEffect(()=>{
  const canvas=canvasRef.current;if(!canvas)return;
  const ctx=canvas.getContext('2d');if(!ctx)return;
  let raf=0;
  const draw=()=>{
   raf=requestAnimationFrame(draw);
   const w=canvas.width,h=canvas.height,dots=pointsRef.current;
   ctx.fillStyle='rgba(0,0,0,0.32)';ctx.fillRect(0,0,w,h);
   if(!dots.length)return;
   const cx=w/2,cy=h/2,pad=28;
   let minX=Infinity,maxX=-Infinity,minZ=Infinity,maxZ=-Infinity;
   for(const d of dots){const p=d.p;if(p[0]<minX)minX=p[0];if(p[0]>maxX)maxX=p[0];if(p[2]<minZ)minZ=p[2];if(p[2]>maxZ)maxZ=p[2]}
   const spanX=Math.max(1,maxX-minX),spanZ=Math.max(1,maxZ-minZ);
   const scale=Math.min((w-pad*2)/spanX,(h-pad*2)/spanZ),midX=(minX+maxX)/2,midZ=(minZ+maxZ)/2;
   const project=(p:number[]):[number,number]=>[cx+(p[0]-midX)*scale,cy+(p[2]-midZ)*scale];
   const t=performance.now();
   if(completeAtRef.current==null){
    for(const d of dots){
     const [x,y]=project(d.p);
     const age=t-d.t,fresh=Math.max(0,1-age/FADE_IN_MS);
     const core=1.1+fresh*2.2,glow=core*(2.4+fresh*1.6);
     if(fresh>0.05){
      const g=ctx.createRadialGradient(x,y,0,x,y,glow);
      g.addColorStop(0,`rgba(120,255,200,${0.35*fresh})`);
      g.addColorStop(1,'rgba(120,255,200,0)');
      ctx.beginPath();ctx.fillStyle=g;ctx.arc(x,y,glow,0,Math.PI*2);ctx.fill();
     }
     ctx.beginPath();
     ctx.fillStyle=`rgba(${37+fresh*70},${229},${139+fresh*50},${0.45+fresh*0.55})`;
     ctx.arc(x,y,core,0,Math.PI*2);ctx.fill();
    }
   }else{
    const elapsed=t-completeAtRef.current,revealFrac=Math.min(1,elapsed/1800);
    const count=Math.max(2,Math.floor(dots.length*revealFrac));
    for(const d of dots){const [x,y]=project(d.p);ctx.beginPath();ctx.fillStyle='rgba(37,229,139,0.22)';ctx.arc(x,y,1,0,Math.PI*2);ctx.fill()}
    ctx.save();ctx.shadowColor='rgba(37,229,139,0.95)';ctx.shadowBlur=16;ctx.strokeStyle='#25e58b';ctx.lineWidth=2.6;
    ctx.beginPath();
    for(let i=0;i<count;i++){const [x,y]=project(dots[i].p);if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y)}
    ctx.stroke();ctx.restore();
    if(revealFrac>=1){
     const pulse=0.5+0.5*Math.sin((t-completeAtRef.current)/220);
     ctx.font='700 16px Inter, sans-serif';ctx.textAlign='center';
     ctx.fillStyle=`rgba(37,229,139,${0.65+pulse*0.35})`;
     ctx.fillText('TRACK MAPPED',cx,h-14);
    }
   }
  };
  draw();
  return ()=>cancelAnimationFrame(raf);
 },[]);

 return <canvas ref={canvasRef} width={520} height={420} className="lidar-canvas" aria-label="Live point-cloud scan of captured track positions"/>;
}
