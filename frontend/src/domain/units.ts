// Mirror of backend/app/telemetry/units.py. Canonical (internal) units are m/s, m, degC, L, bar;
// conversion to the user's preferred units happens at the display edge. null/undefined pass
// through as null so callers never guard missing channels. The preference itself is VIEW state
// (unitsStore below), not domain data.
import {createStore,useStore,shallowEqual} from '../app/store'
import type {Units} from './types'

export type {Units}
export type UnitKind='speed'|'temperature'|'fuel'|'distance'|'pressure'
type Num=number|null|undefined

export const DEFAULT_UNITS:Units={speed:'kmh',temperature:'C',fuel:'L',distance:'m',pressure:'bar'}

const MS_TO_KMH=3.6
const MS_TO_MPH=2.2369362920544
const FUEL:Record<Units['fuel'],number>={L:1,gal_us:3.785411784,gal_uk:4.54609}
const DISTANCE:Record<Units['distance'],number>={m:1,km:1000,mi:1609.344}
const PSI_BAR=14.503773773

function bad(kind:string,unit:string):never{throw new Error(`unknown ${kind} unit '${unit}'`)}

export function speed(ms:Num,unit:Units['speed']='kmh'):number|null{
 if(unit!=='kmh'&&unit!=='mph')bad('speed',unit)
 return ms==null?null:ms*(unit==='kmh'?MS_TO_KMH:MS_TO_MPH)
}
export function speedToMs(v:Num,unit:Units['speed']='kmh'):number|null{
 if(unit!=='kmh'&&unit!=='mph')bad('speed',unit)
 return v==null?null:v/(unit==='kmh'?MS_TO_KMH:MS_TO_MPH)
}
export function temp(c:Num,unit:Units['temperature']='C'):number|null{
 if(unit!=='C'&&unit!=='F')bad('temperature',unit)
 return c==null?null:unit==='C'?c:c*9/5+32
}
export function tempToC(v:Num,unit:Units['temperature']='C'):number|null{
 if(unit!=='C'&&unit!=='F')bad('temperature',unit)
 return v==null?null:unit==='C'?v:(v-32)*5/9
}
export function fuel(litres:Num,unit:Units['fuel']='L'):number|null{
 if(!(unit in FUEL))bad('fuel',unit)
 return litres==null?null:litres/FUEL[unit]
}
export function fuelToL(v:Num,unit:Units['fuel']='L'):number|null{
 if(!(unit in FUEL))bad('fuel',unit)
 return v==null?null:v*FUEL[unit]
}
export function distance(m:Num,unit:Units['distance']='m'):number|null{
 if(!(unit in DISTANCE))bad('distance',unit)
 return m==null?null:m/DISTANCE[unit]
}
export function distanceToM(v:Num,unit:Units['distance']='m'):number|null{
 if(!(unit in DISTANCE))bad('distance',unit)
 return v==null?null:v*DISTANCE[unit]
}
export function pressure(bar:Num,unit:Units['pressure']='bar'):number|null{
 if(unit!=='bar'&&unit!=='psi')bad('pressure',unit)
 return bar==null?null:unit==='bar'?bar:bar*PSI_BAR
}
export function pressureToBar(v:Num,unit:Units['pressure']='bar'):number|null{
 if(unit!=='bar'&&unit!=='psi')bad('pressure',unit)
 return v==null?null:unit==='bar'?v:v/PSI_BAR
}

const LABELS={
 speed:{kmh:'km/h',mph:'mph'},
 temperature:{C:'°C',F:'°F'},
 fuel:{L:'L',gal_us:'gal',gal_uk:'gal (UK)'},
 distance:{m:'m',km:'km',mi:'mi'},
 pressure:{bar:'bar',psi:'psi'},
} as const

export function label<K extends UnitKind>(kind:K,unit:Units[K]):string{
 const l=(LABELS[kind] as Record<string,string>)[unit]
 if(!l)bad(kind,unit)
 return l
}

const num=(v:number|null,digits:number)=>v==null||!Number.isFinite(v)?'—':v.toFixed(digits)

// Formatters take CANONICAL inputs and the chosen units; missing values render as an em dash,
// matching the existing `fmt()` helpers in the components.
export const format={
 speed:(ms:Num,u:Units=DEFAULT_UNITS,digits=0)=>{const v=speed(ms,u.speed);return v==null?'—':`${num(v,digits)} ${label('speed',u.speed)}`},
 temperature:(c:Num,u:Units=DEFAULT_UNITS,digits=0)=>{const v=temp(c,u.temperature);return v==null?'—':`${num(v,digits)}${label('temperature',u.temperature)}`},
 fuel:(l:Num,u:Units=DEFAULT_UNITS,digits=1)=>{const v=fuel(l,u.fuel);return v==null?'—':`${num(v,digits)} ${label('fuel',u.fuel)}`},
 distance:(m:Num,u:Units=DEFAULT_UNITS,digits=u.distance==='m'?0:2)=>{const v=distance(m,u.distance);return v==null?'—':`${num(v,digits)} ${label('distance',u.distance)}`},
 pressure:(bar:Num,u:Units=DEFAULT_UNITS,digits=u.pressure==='bar'?2:1)=>{const v=pressure(bar,u.pressure);return v==null?'—':`${num(v,digits)} ${label('pressure',u.pressure)}`},
}

export function spokenSpeed(ms:Num,unit:Units['speed']='kmh'):string|null{
 const v=speed(ms,unit)
 return v==null?null:`${Math.round(v)} ${unit==='kmh'?'kilometres per hour':'miles per hour'}`
}

export function isUnits(v:unknown):v is Units{
 if(typeof v!=='object'||v===null)return false
 const u=v as Record<string,unknown>
 return (u.speed==='kmh'||u.speed==='mph')&&(u.temperature==='C'||u.temperature==='F')&&typeof u.fuel==='string'&&u.fuel in FUEL&&typeof u.distance==='string'&&u.distance in DISTANCE&&(u.pressure==='bar'||u.pressure==='psi')
}

// ---- user preference (VIEW state: localStorage ui:v1:units, never domain data) ----
const UNITS_KEY='ui:v1:units'

function loadUnits():Units{
 try{
  const raw=localStorage.getItem(UNITS_KEY)
  if(raw){const v=JSON.parse(raw);if(isUnits(v))return v}
 }catch{/* private mode / blocked storage: use defaults */}
 return DEFAULT_UNITS
}

export const unitsStore=createStore<{units:Units}>({units:loadUnits()})

export function setUnits(partial:Partial<Units>):void{
 const units={...unitsStore.getState().units,...partial}
 unitsStore.setState({units})
 try{localStorage.setItem(UNITS_KEY,JSON.stringify(units))}catch{/* ignore */}
}

export const useUnits=():Units=>useStore(unitsStore,s=>s.units,shallowEqual)
