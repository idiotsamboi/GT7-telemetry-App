import React,{useEffect,useRef} from 'react';
import uPlot from 'uplot';
import 'uplot/dist/uPlot.min.css';
import {channelColor} from './colors';
export default function Chart({rows,channels=['speed'],labels=['Speed · km/h'],height=240}:{rows:any[],channels?:string[],labels?:string[],height?:number}){
 const box=useRef<HTMLDivElement>(null), plot=useRef<uPlot|null>(null);
 const data=()=>[rows.map(r=>r.t??r.mono),...channels.map(c=>rows.map(r=>r[c]??r.values?.[c]??null))] as uPlot.AlignedData;
 useEffect(()=>{if(!box.current)return;const colors=['#ed6571','#59dfad','#fa9d75','#ba9bff'];plot.current=new uPlot({width:box.current.clientWidth||600,height,series:[{},...channels.map((c,i)=>({label:labels[i]||c,stroke:channelColor(c),width:2}))],axes:[{stroke:'#8290a5',grid:{stroke:'#202936'}},{stroke:'#8290a5',grid:{stroke:'#202936'}}],scales:{x:{time:false}},cursor:{sync:{key:'telemetry'}},legend:{show:true}},data(),box.current);const observer=new ResizeObserver(()=>plot.current?.setSize({width:box.current?.clientWidth||300,height}));observer.observe(box.current);return()=>{observer.disconnect();plot.current?.destroy();plot.current=null}},[channels.join(),height]);
 useEffect(()=>{plot.current?.setData(data())},[rows]);return <div ref={box} className="chart" aria-label={`Telemetry chart: ${labels.join(', ')}`}/>;
}
