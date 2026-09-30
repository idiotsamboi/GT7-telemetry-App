// Telemetry channel registry types + helpers. The data lives in channels.generated.ts (generated
// from the backend registry); this file only adds lookup helpers, so it stays valid while the
// generated list is empty.
import {CHANNELS} from './channels.generated'
import type {UnitKind} from './units'

export type ChannelDef={
 id:string
 label:string
 /** Canonical unit family, if the value is convertible to a user preference. */
 unit?:UnitKind|'none'|string
 group?:string
 description?:string
 [key:string]:unknown
}

export const channels:readonly ChannelDef[]=CHANNELS
const byId=new Map<string,ChannelDef>(CHANNELS.map(c=>[c.id,c]))

export const getChannel=(id:string):ChannelDef|undefined=>byId.get(id)
export const hasChannel=(id:string):boolean=>byId.has(id)
export const channelLabel=(id:string):string=>byId.get(id)?.label??id
export const channelsInGroup=(group:string):ChannelDef[]=>CHANNELS.filter(c=>c.group===group)
/** Ids from `needed` that the registry does not define (empty registry => unknown, reports none). */
export const missingChannels=(needed:readonly string[]):string[]=>byId.size===0?[]:needed.filter(id=>!byId.has(id))
