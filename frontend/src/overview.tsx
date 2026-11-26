import { useState } from "react"
import { Activity, ArrowDownToLine, ArrowUpRight, CircleCheck, Clock3, Film, HardDrive, Instagram, Plus } from "lucide-react"
import { Button, Card, Check, Field } from "./ui"
import { bytes, date, type Dashboard, type Entry, type Options, type Task } from "./types"
import type { Tab } from "./main"

export function Overview({data,navigate}:{data:Dashboard;navigate:(page:Tab)=>void}) {
  const c = data.counts
  const pending = (c.waiting || 0) + (c.ready || 0) + (c.uploading || 0) + (c.uncertain || 0)
  const quotas = data.accounts.filter(a=>a.quota!==null && a.state==="connected")
  const metrics = [
    {label:"Discovered media",value:c.discovered || 0,icon:Film},
    {label:"Downloaded",value:c.downloaded || 0,icon:ArrowDownToLine},
    {label:"Pending uploads",value:pending,icon:Clock3},
    {label:"Published",value:c.published || 0,icon:CircleCheck},
    {label:"Failed jobs",value:c.failed || 0,icon:Activity},
    {label:"Known quota remaining",value:quotas.length ? quotas.reduce((sum,a)=>sum+(a.quota || 0),0) : "—",icon:Instagram},
  ]
  const bars = [
    {name:"CPU",value:data.cpu,caption:`${data.cpu.toFixed(0)}%`},
    {name:"RAM",value:data.ram,caption:`${data.ram.toFixed(0)}%`},
    {name:"Media storage",value:100*data.storage/(data.settings.storage_mb*1e6),caption:`${bytes(data.storage)} / ${data.settings.storage_mb.toLocaleString()} MB`},
  ]
  return <>
    <div className="intro"><div><h2>Automation at a glance</h2><p>{data.accounts.filter(a=>a.state==="connected").length} connected accounts · {data.sources.length} configured sources</p></div><Button variant="primary" onClick={()=>navigate(data.accounts.length?"Sources":"Accounts")}><Plus size={17}/>{data.accounts.length?"Manage sources":"Connect Instagram"}</Button></div>
    <div className="metrics">{metrics.map(({label,value,icon:Icon})=><Card key={label}><div className="metric-top"><span>{label}</span><span className="metric-icon"><Icon size={17}/></span></div><strong>{typeof value==="number"?value.toLocaleString():value}</strong></Card>)}</div>
    <div className="split"><Card><div className="section-head"><h2>VPS resources</h2><HardDrive size={18}/></div>{bars.map(bar=><div className="meter" key={bar.name}><div><span>{bar.name}</span><span>{bar.caption}</span></div><progress aria-label={bar.name} max={100} value={Math.min(100,bar.value)}/></div>)}<p>{bytes(data.disk_free)} free on media volume</p></Card>
    <Card><div className="section-head"><h2>Recent activity</h2><Button variant="ghost" onClick={()=>navigate("Activity")}>View all <ArrowUpRight size={15}/></Button></div><Logs rows={data.logs.slice(0,5)}/></Card></div>
  </>
}
export function Logs({rows}:{rows:Entry[]}) {
  return rows.length ? <ul className="logs">{rows.map(row=><li key={row.id}><span className={`log-dot ${row.level}`}/><div>{row.message}<small>{date(row.created)}</small></div></li>)}</ul> : <p className="empty">Activity will appear as sources sync and queue items are processed.</p>
}
export function Settings({options,task}:{options:Options;task:Task}) {
  const [draft,setDraft] = useState(options)
  const change = <K extends keyof Options>(key:K,value:Options[K])=>setDraft(current=>({...current,[key]:value}))
  return <Card><h2>Automation and scheduling</h2><form onSubmit={e=>{e.preventDefault();if(options.dry_run&&!draft.dry_run&&!confirm("Enable live Instagram publishing?"))return;void task("/settings",draft,"PUT")}}>
    <div className="actions wrap"><Check label="Automatic publishing" checked={draft.automatic} change={v=>change("automatic",v)}/><Check label="Pause automation" checked={draft.paused} change={v=>change("paused",v)}/><Check label="Dry run" checked={draft.dry_run} change={v=>change("dry_run",v)}/></div>
    <div className="form-grid">
      <Field label="Time zone (IANA)"><input required value={draft.timezone} onChange={e=>change("timezone",e.target.value)}/></Field>
      <Field label="Start time"><input type="time" required value={draft.start} onChange={e=>change("start",e.target.value)}/></Field>
      <Field label="End time"><input type="time" required value={draft.end} onChange={e=>change("end",e.target.value)}/></Field>
      {([["daily","Posts per account per day",1,100],["interval","Minimum interval (minutes)",1,1440],["downloads","Concurrent downloads",1,8],["uploads","Concurrent uploads",1,8],["storage_mb","Media storage limit (MB)",300,1000000],["file_mb","Download file limit (MB)",1,1000],["retention_days","Retention (days)",1,365]] as const).map(([key,label,min,max])=><Field label={label} key={key}><input type="number" required min={min} max={max} value={draft[key]} onChange={e=>change(key,Number(e.target.value))}/></Field>)}
    </div><div><Button type="submit" variant="primary">Save settings</Button></div>
  </form></Card>
}
