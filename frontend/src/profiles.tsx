import { useState } from "react"
import { Instagram, Plus, Radio, RefreshCw } from "lucide-react"
import { Badge, Button, Card, Check, Field } from "./ui"
import { date, destinations, kinds, status, tone, type Account, type Source, type SourceInput, type Task } from "./types"

export function Accounts({accounts,connect,task}:{accounts:Account[];connect:(sourceOnly:boolean,accountId?:number)=>void;task:Task}) {
  return <Card><div className="section-head wrap"><div><h2>Instagram accounts</h2><p>Authorize a Business or Creator account to read its media or publish to it.</p></div><div className="actions wrap"><Button onClick={()=>connect(true)}>Connect source only</Button><Button variant="primary" onClick={()=>connect(false)}><Plus size={16}/>Connect publishing account</Button></div></div>
    {accounts.length ? <div className="rows">{accounts.map(a=><div className="row" key={a.id}>
      {a.picture ? <img className="avatar" src={a.picture} alt="" referrerPolicy="no-referrer"/> : <span className="avatar"><Instagram size={18}/></span>}
      <div className="grow"><strong>@{a.username}</strong><small>ID {a.ig_id} · {a.can_publish ? "Publishing enabled" : "Source access"} · {a.quota === null ? "Quota pending" : `${a.quota} posts remaining`}</small></div>
      <Badge tone={tone(a.state)}>{status(a.state)}</Badge><Button onClick={()=>connect(!a.can_publish,a.id)}>Reconnect</Button>
      <Button variant="ghost" onClick={()=>{if(confirm(`Disconnect @${a.username}?`)) void task(`/accounts/${a.id}`,undefined,"DELETE")}}>Remove</Button>
    </div>)}</div> : <p className="empty">Connect an Instagram account to get started.</p>}
  </Card>
}

const defaults:SourceInput = {profile:"",enabled:true,interval:30,kinds:Object.keys(kinds),initial_count:30,existing:true,oldest:true,priority:0,destinations:[]}
export function Sources({sources,accounts,task}:{sources:Source[];accounts:Account[];task:Task}) {
  const [draft,setDraft] = useState<SourceInput>()
  const [id,setId] = useState<number>()
  const change = <K extends keyof SourceInput>(key:K,value:SourceInput[K])=>setDraft(current=>current && ({...current,[key]:value}))
  return <><Card><div className="section-head"><h2>Source profiles</h2><Button variant="primary" onClick={()=>{setId(undefined);setDraft(defaults)}}><Plus size={16}/>Add source</Button></div>
    {sources.length ? <div className="rows">{sources.map(s=><div className="row" key={s.id}><span className="avatar"><Radio size={17}/></span><div className="grow"><strong>@{s.username}</strong><small>{s.status} · {s.last_sync ? date(s.last_sync) : "Awaiting first sync"}</small></div><Badge tone={s.enabled ? "good" : "neutral"}>{s.enabled ? "Enabled" : "Disabled"}</Badge>
      <Button disabled={!s.enabled} onClick={()=>void task(`/sources/${s.id}/sync`)}><RefreshCw size={14}/>Sync</Button><Button onClick={()=>{setId(s.id);setDraft({...s,profile:s.username})}}>Edit</Button></div>)}</div> : <p className="empty">Add an authorized source account to discover its media.</p>}</Card>
    {draft && <Card><h2>{id ? "Edit source" : "Add source"}</h2><form onSubmit={async e=>{e.preventDefault();if(await task(id ? `/sources/${id}` : "/sources",draft,id ? "PUT" : "POST")) setDraft(undefined)}}>
      <Field label="Instagram username or profile URL"><input required value={draft.profile} onChange={e=>change("profile",e.target.value)} list="authorized-profiles"/><datalist id="authorized-profiles">{accounts.filter(a=>a.state==="connected").map(a=><option key={a.id} value={a.username}/>)}</datalist></Field>
      <div className="form-grid">{([["interval","Sync interval (minutes)",5,1440],["initial_count","Maximum initial import",1,500],["priority","Source priority",-100,100]] as const).map(([key,label,min,max])=><Field key={key} label={label}><input type="number" min={min} max={max} required value={draft[key]} onChange={e=>change(key,Number(e.target.value))}/></Field>)}</div>
      <Field label="Destination accounts"><select multiple required value={draft.destinations.map(String)} onChange={e=>change("destinations",Array.from(e.target.selectedOptions,x=>Number(x.value)))}>{destinations(accounts).map(a=><option key={a.id} value={a.id}>@{a.username}</option>)}</select></Field>
      <div className="actions wrap">{Object.entries(kinds).map(([key,label])=><Check key={key} label={label} checked={draft.kinds.includes(key)} change={enabled=>change("kinds",enabled?[...draft.kinds,key]:draft.kinds.filter(k=>k!==key))}/>)}</div>
      <div className="actions wrap"><Check label="Enable automation" checked={draft.enabled} change={v=>change("enabled",v)}/><Check label="Import existing media" checked={draft.existing} change={v=>change("existing",v)}/><Check label="Oldest first" checked={draft.oldest} change={v=>change("oldest",v)}/></div>
      <div className="actions"><Button type="submit" variant="primary">Save source</Button><Button onClick={()=>setDraft(undefined)}>Close</Button></div>
    </form></Card>}
  </>
}
