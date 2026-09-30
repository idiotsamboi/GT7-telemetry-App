// Error boundary with page/panel variants. Each instance owns its own state, so the OBS overlay
// boundary never shares anything with the editor. Reports to /api/client-errors (rate limited,
// scrubbed - see domain/clientErrors.ts) and offers Retry + Copy diagnostics.
import React from 'react'
import {reportClientError,copyDiagnostics} from '../domain/clientErrors'

type Props={
 /** 'page' fills the view, 'panel' is an inline card, 'overlay' is a bare message (OBS). */
 variant?:'page'|'panel'|'overlay'
 /** Name used in the report (page or panel id). */
 name:string
 children:React.ReactNode
}
type State={error:Error|null,copied:''|'ok'|'failed',attempt:number}

export default class ErrorBoundary extends React.Component<Props,State>{
 state:State={error:null,copied:'',attempt:0}
 static getDerivedStateFromError(error:Error):Partial<State>{return {error,copied:''}}
 componentDidCatch(error:Error){void reportClientError(error,this.props.name)}
 retry=()=>this.setState(s=>({error:null,copied:'',attempt:s.attempt+1}))
 copy=async()=>{
  try{await copyDiagnostics();this.setState({copied:'ok'})}catch{this.setState({copied:'failed'})}
 }
 render(){
  const {error,copied,attempt}=this.state
  if(!error)return <React.Fragment key={attempt}>{this.props.children}</React.Fragment>
  const variant=this.props.variant??'panel'
  if(variant==='overlay')return <div role="alert" data-error-boundary="overlay">Graphics unavailable. Reload this overlay.</div>
  const body=<>
   <h3>{variant==='page'?'This page could not render':`${this.props.name} could not render`}</h3>
   <p>Your saved data is retained.</p>
   <div className="toolbar">
    <button onClick={this.retry}>Retry</button>
    <button onClick={this.copy}>Copy diagnostics</button>
    {copied==='ok'&&<span role="status">Copied</span>}
    {copied==='failed'&&<span role="status">Could not copy diagnostics</span>}
   </div>
  </>
  return variant==='page'?<main className="card" role="alert" data-error-boundary="page">{body}</main>:<section className="card" role="alert" data-error-boundary="panel">{body}</section>
 }
}
