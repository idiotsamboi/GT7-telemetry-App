// JS-side mirror of tokens.css, for code that needs numeric values (gsap durations,
// canvas drawing) rather than CSS custom properties. Keep values identical to
// tokens.css - that file is the source of truth for anything CSS can read directly.
export const duration={instant:60,fast:100,base:140,slow:180,fade:1200} as const
export const easing={standard:'cubic-bezier(.2,.8,.2,1)',press:'cubic-bezier(.3,0,.5,1)'} as const

export const driverColor={
 accent:'#4D9BFF',accentGlow:'rgba(77,155,255,.35)',
 throttle:'#2FD26B',brake:'#FF4D5E',clutch:'#9EDBFF',fastest:'#B36BFF',otherLap:'#F4D34E',
 warning:'#FFB020',reference:'#35D0E6',comparison:'#F2F5F8',stale:'#5B6675',
} as const

export const broadcastColor={
 program:'#E5322D',preview:'#2FBF4F',selection:'#3D8BFD',tool:'#F28C28',warning:'#F2B600',
} as const

export type Motion='full'|'data'|'off'

export function applyMotionSetting(mode:Motion):void{
 document.documentElement.dataset.motion=mode
}

export function preferredMotion():Motion{
 try{
  const saved=localStorage.getItem('ui:v1:motion') as Motion|null
  if(saved==='full'||saved==='data'||saved==='off')return saved
 }catch{}
 return matchMedia('(prefers-reduced-motion: reduce)').matches?'off':'data'
}
