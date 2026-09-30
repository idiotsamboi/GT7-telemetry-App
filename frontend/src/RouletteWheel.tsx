type Candidate={id:string,name:string};

export default function RouletteWheel({list,rotation,spinning,winnerIndex}:{list:Candidate[],rotation:number,spinning:boolean,winnerIndex:number|null}){
 const n=Math.max(1,list.length);
 const seg=360/n;
 const stops=Array.from({length:n},(_,i)=>{
  const isWinner=!spinning&&winnerIndex===i;
  const color=isWinner?'#25e58b':(i%2===0?'#123023':'#161c27');
  return `${color} ${i*seg}deg ${(i+1)*seg}deg`;
 }).join(',');
 return <div className="roulette-wrap">
  <div className="roulette-pointer"/>
  <div className="roulette-wheel" style={{transform:`rotate(${rotation}deg)`,backgroundImage:`conic-gradient(${stops})`}}>
   {Array.from({length:n},(_,i)=><span key={i} className="roulette-tick" style={{transform:`rotate(${i*seg}deg)`}}/>)}
  </div>
  <div className="roulette-hub"/>
 </div>;
}
