import { useState } from "react"
import { Film, Plus } from "lucide-react"
import { Badge, Button, Card, Field } from "./ui"
import { bytes, date, destinations, kinds, status, tone, type Account, type Job, type Task } from "./types"

function queueState(job:Job) {
  if(job.state==="waiting")return job.download==="pending"?"download_pending":job.download || "discovered"
  if(job.state==="ready")return job.scheduled_for?"scheduled":"ready to publish"
  return job.state
}
export function Queue({jobs,accounts,task,offset,setOffset}:{jobs:Job[];accounts:Account[];task:Task;offset:number;setOffset:(value:number)=>void}) {
  const [importing,setImporting] = useState(false)
  const [preview,setPreview] = useState<Job>()
  const [filter,setFilter] = useState("all")
  function act(job:Job,action:string) {
    if (["republish","delete","confirm_published","confirm_not_published"].includes(action) &&
      !confirm(action.startsWith("confirm") ? `Verify the post on Instagram first. ${status(action)}?` : `${status(action)} this item?`)) return
    const priority = action==="priority" ? prompt("Queue priority (−100 to 100)",String(job.priority)) : "0"
    if (priority===null) return
    const instagramId = action==="confirm_published" ? prompt("Instagram media ID, if available") : null
    void task(`/queue/${job.id}`,{action,priority:Number(priority),instagram_id:instagramId || null})
  }
  const visible = jobs.filter(job=>filter==="all" || queueState(job)===filter)
  return <>
    {importing && <Card><h2>Manual media import</h2><form onSubmit={async e=>{e.preventDefault();if(await task("/import",new FormData(e.currentTarget)))setImporting(false)}}>
      <Field label="Destination"><select name="account_id" required><option value="">Select a destination</option>{destinations(accounts).map(a=><option key={a.id} value={a.id}>@{a.username}</option>)}</select></Field>
      <Field label="Media files in carousel order"><input name="files" type="file" accept="image/*,video/*" multiple required/></Field>
      <Field label="Original Instagram permalink (optional)"><input name="permalink" type="url"/></Field>
      <label className="check"><input name="authorized" type="checkbox" value="true" required/>I have permission to repost these files.</label>
      <div className="actions"><Button variant="primary" type="submit">Import media</Button><Button onClick={()=>setImporting(false)}>Close</Button></div>
    </form></Card>}
    {preview && <Card><div className="section-head"><h2>Media preview</h2><Button onClick={()=>setPreview(undefined)}>Close</Button></div><div className="previews">{preview.assets.map(a=>a.mime.startsWith("video")?<video controls key={a.id} src={`/api/preview/${a.id}`}/>:<img key={a.id} src={`/api/preview/${a.id}`} alt="Media preview"/>)}</div></Card>}
    <Card><div className="section-head wrap"><h2>Media queue</h2><div className="actions"><select aria-label="Filter this page by status" value={filter} onChange={e=>setFilter(e.target.value)}><option value="all">All statuses on this page</option>{[...new Set(jobs.map(queueState))].sort().map(state=><option key={state} value={state}>{status(state)}</option>)}</select><Button variant="primary" onClick={()=>setImporting(true)}><Plus size={16}/>Manual import</Button></div></div>
    {visible.length ? <div className="table-scroll"><table><thead><tr><th scope="col">Media</th><th scope="col">Destination</th><th scope="col">Status</th><th scope="col">Actions</th></tr></thead><tbody>{visible.map(job=>{
      const state=queueState(job)
      const thumbnail=job.assets.find(a=>a.mime.startsWith("image"))
      const actions=["ready","failed","dry_run","cancelled","skipped"].includes(job.state)?["publish","retry"]:[]
      if(["waiting","ready","failed","dry_run"].includes(job.state))actions.push("cancel","skip")
      if(["failed","skipped","cancelled","dry_run"].includes(job.state))actions.push("delete")
      if(["waiting","ready"].includes(job.state))actions.push("priority")
      if(job.state==="published")actions.push("republish")
      if(job.state==="uncertain")actions.push("confirm_published","confirm_not_published")
      return <tr key={job.id}><td><div className="media-cell">{thumbnail?<img className="thumb" src={`/api/preview/${thumbnail.id}`} alt=""/>:<span className="thumb"><Film size={18}/></span>}<div><strong>{kinds[job.kind] || job.kind} · #{job.id}</strong><small>{job.source} {job.origin&&<a href={job.origin} target="_blank" rel="noreferrer">Original ↗</a>}</small><small>{job.size?bytes(job.size):"—"}{job.duration?` · ${Math.round(job.duration)} s`:""}</small></div></div></td>
      <td>@{job.destination}{job.permalink&&<small><a href={job.permalink} target="_blank" rel="noreferrer">View post ↗</a></small>}</td><td><Badge tone={tone(state)}>{status(state)}</Badge>{job.state==="waiting"&&<small>{job.progress}%</small>}{job.scheduled_for?<small>Eligible from {date(job.scheduled_for)}</small>:job.next_run>Date.now()/1000&&<small>{date(job.next_run)}</small>}{job.error&&<small className="error-text">{job.error}</small>}</td>
      <td><div className="actions wrap">{job.assets.length>0&&<Button onClick={()=>setPreview(job)}>Preview</Button>}{actions.map(action=><Button key={action} onClick={()=>act(job,action)}>{status(action)}</Button>)}</div></td></tr>
    })}</tbody></table></div> : <p className="empty">{filter==="all"?"Sync a source or import media to add items to this queue.":"No jobs match this status on this page."}</p>}
    {(offset>0||jobs.length===50)&&<div className="actions pagination"><Button disabled={!offset} onClick={()=>{setFilter("all");setOffset(Math.max(0,offset-50))}}>Previous</Button><Button disabled={jobs.length<50} onClick={()=>{setFilter("all");setOffset(offset+50)}}>Next</Button></div>}</Card>
  </>
}
