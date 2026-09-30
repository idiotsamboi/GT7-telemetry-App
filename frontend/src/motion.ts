import {gsap} from 'gsap';
// Small shared motion vocabulary so every page moves the same way — the app
// should read as one deliberately-designed product, not a pile of screens.
gsap.defaults({ease:'power2.out',duration:.35});

export function enter(container:Element|null){
 if(!container)return;
 const items=container.querySelectorAll('.card,.rc-alarm,.rc-setup,.rc-session-bar,.atem-bank,.atem-bus,.davinci-page>*');
 if(!items.length)return;
 gsap.fromTo(items,{opacity:0,y:14},{opacity:1,y:0,duration:.4,stagger:.045,ease:'power2.out',overwrite:true});
}

export function crossfade(container:Element|null){
 if(!container)return;
 gsap.fromTo(container,{opacity:0,y:10},{opacity:1,y:0,duration:.32,ease:'power2.out',overwrite:true});
}

export function pulse(el:Element|null){
 if(!el)return;
 gsap.fromTo(el,{scale:1.03},{scale:1,duration:.5,ease:'elastic.out(1,.5)'});
}

export function press(el:Element){
 gsap.fromTo(el,{scale:.94},{scale:1,duration:.4,ease:'elastic.out(1,.4)'});
}

export function flash(el:Element|null,color='#ffffff'){
 if(!el)return;
 gsap.fromTo(el,{boxShadow:`0 0 0 0 ${color}`},{boxShadow:'0 0 0 0 transparent',duration:.8,ease:'power2.out'});
}

/** Animates a numeric text readout from its previous value to the next; skips
 * the tween entirely when the element is off-screen or the delta is huge
 * (a source/session change), so it never fights fast telemetry updates. */
export function countTo(el:HTMLElement|null,value:number,decimals=0){
 if(!el)return;
 const from=Number(el.dataset.v)||0;
 if(!isFinite(value)){el.textContent='—';return}
 if(Math.abs(value-from)>500){el.dataset.v=String(value);el.textContent=value.toFixed(decimals);return}
 const obj={v:from};
 gsap.to(obj,{v:value,duration:.28,ease:'power1.out',onUpdate:()=>{el.textContent=obj.v.toFixed(decimals)}});
 el.dataset.v=String(value);
}

// One delegated listener gives every button in the app the same tactile
// press-bounce, without wiring a handler onto each one individually.
if(typeof document!=='undefined'){
 document.addEventListener('pointerdown',e=>{
  const target=e.target as HTMLElement;
  const btn=target?.closest?.('button,.button,a.button') as HTMLButtonElement|null;
  if(btn&&!btn.disabled)press(btn);
 },{passive:true});
}

export {gsap};
