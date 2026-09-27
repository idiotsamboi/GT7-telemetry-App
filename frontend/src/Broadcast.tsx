import React from 'react';
import {Flag,Car} from 'lucide-react';
export function CarIdentity({car,stale}:{car:any,stale:boolean}){
 return <section className="car-identity" aria-label="Current car manufacturer"><svg width="0" height="0" aria-hidden="true" style={{position:"absolute"}}><defs><filter id="genesis-transparent" colorInterpolationFilters="sRGB"><feColorMatrix type="matrix" values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  -0.2126 -0.7152 -0.0722 0 1"/></filter></defs></svg><small>ONBOARD / {stale?'LAST RECEIVED':'LIVE'}</small><div className="manufacturer-image">{car?.logo?<img style={car.logo==="/brands/152.png"?{filter:"url(#genesis-transparent)"}:undefined} src={car.logo} alt={`${car.manufacturer} logo`}/>:<Car size={38}/>}</div><strong>{car?.manufacturer||'Awaiting manufacturer'}</strong><p>{car?.name||'Start driving to identify your car'}</p></section>
}
export function FlagIndicator({flags,stale}:{flags:number,stale:boolean}){
 const status=stale?'NO SIGNAL':flags&4?'LOADING':flags&2?'PAUSED':flags&1?'ON TRACK':'OFF TRACK';
 return <div className="flag-indicator" title="Race-control flags are not included in GT7 UDP telemetry. Status below describes only your car."><Flag size={22}/><div><strong>RACE FLAGS <b>N/A</b></strong><small>{status} · PLAYER STATUS</small></div></div>
}
export function TimingLegend(){return <div className="timing-legend"><span className="fastest">Overall fastest</span><span className="personal">Personal best</span><span className="other-lap">Other laps</span></div>}
export function DrivingLine({points=[]}:{points:number[][]}){
 if(points.length<2)return <div className="empty-trace">Waiting for a driving trace</div>;
 const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]),minX=Math.min(...xs),minY=Math.min(...ys),scale=Math.max(Math.max(...xs)-minX,Math.max(...ys)-minY,1);
 const project=(p:number[])=>[25+(p[0]-minX)/scale*310,25+(p[1]-minY)/scale*230];
 const paths:Record<string,string>={'-1':'','0':'','1':''};
 for(let i=1;i<points.length;i++){const a=project(points[i-1]),b=project(points[i]);const trend=points[i][2]||0;paths[String(trend)]+= `M${a[0]},${a[1]}L${b[0]},${b[1]}`;}
 const end=project(points[points.length-1]);
 return <svg viewBox="0 0 360 280" className="trace" aria-label="Driving line: green gaining time, red losing time, gray no reference">{Object.entries(paths).map(([key,d])=><path key={key} d={d} fill="none" stroke={key==='1'?'#25e58b':key==='-1'?'#ff354b':'#707078'} strokeWidth="3.5" strokeLinecap="round"/>)}<circle cx={end[0]} cy={end[1]} r="4" fill="white"/></svg>
}

