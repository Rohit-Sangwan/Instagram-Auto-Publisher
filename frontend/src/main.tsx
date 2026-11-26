import { useEffect, useState } from "react"
import { createRoot } from "react-dom/client"
import { Activity, Instagram, LayoutGrid, ListOrdered, LogOut, Moon, Radio, Settings2, Sun, Users } from "lucide-react"
import { Badge, Button, Card, Field } from "./ui"
import { Accounts, Sources } from "./profiles"
import { Logs, Overview, Settings } from "./overview"
import { Queue } from "./queue"
import type {Dashboard,Task} from "./types"
import "./style.css"

let csrf = ""
async function api<T>(path:string, data?:unknown, method="GET"):Promise<T> {
  const multipart = data instanceof FormData
  const response = await fetch("/api"+path,{
    method,headers:{...(data&&!multipart?{"Content-Type":"application/json"}:{}),...(method!=="GET"&&csrf?{"X-CSRF-Token":csrf}:{})},
    body:data ? multipart ? data : JSON.stringify(data) : undefined,
  })
  if (!response.ok) {
    const detail = (await response.json().catch(()=>null))?.detail
    throw new Error(typeof detail==="string"?detail:Array.isArray(detail)?detail.map(x=>x.msg).join(". "):`Request failed (${response.status})`)
  }
  return response.json()
}

const tabs = {Overview:LayoutGrid,Accounts:Users,Sources:Radio,Queue:ListOrdered,Activity,Settings:Settings2}
export type Tab = keyof typeof tabs
function Brand() {return <div className="brand"><span className="brand-icon"><Instagram size={21}/></span><div>Auto Publisher<small>Instagram workspace</small></div></div>}

function App() {
  const [theme,setTheme] = useState(localStorage.getItem("publisher-theme") || "dark")
  const [authed,setAuthed] = useState<boolean|null>(null)
  const [page,setPage] = useState<Tab>("Overview")
  const [data,setData] = useState<Dashboard>()
  const [error,setError] = useState("")
  const [notice,setNotice] = useState("")
  const [busy,setBusy] = useState(false)
  const [offset,setOffset] = useState(0)
  useEffect(()=>{document.documentElement.dataset.theme=theme;localStorage.setItem("publisher-theme",theme)},[theme])
  useEffect(()=>{
    api<{csrf:string}>("/session").then(value=>{csrf=value.csrf;setAuthed(true)}).catch(()=>setAuthed(false))
    const oauth = new URLSearchParams(location.search).get("instagram")
    if (oauth) {
      setNotice(oauth==="connected" ? "Instagram account connected." : "Instagram authorization didn’t complete. Check the activity log and your Meta app settings.")
      setPage("Accounts");history.replaceState(null,"",location.pathname)
    }
  },[])
  useEffect(()=>{
    if(!authed) return
    let alive=true
    const poll=()=>api<Dashboard>(`/dashboard?offset=${offset}`).then(value=>{if(alive)setData(value)}).catch(err=>{if(alive)setError(err.message)})
    void poll()
    const timer=window.setInterval(poll,5000)
    return ()=>{alive=false;clearInterval(timer)}
  },[authed,offset])
  const task:Task=async(path,value,method="POST")=>{
    setBusy(true);setError("");setNotice("")
    try {await api(path,value,method);setData(await api<Dashboard>(`/dashboard?offset=${offset}`));setNotice("Changes saved.");return true}
    catch(err){setError((err as Error).message);return false}
    finally{setBusy(false)}
  }
  async function connect(sourceOnly:boolean,accountId?:number){
    setBusy(true);setError("")
    try{location.assign((await api<{url:string}>(`/instagram/connect?source_only=${sourceOnly}${accountId ? `&account_id=${accountId}` : ""}`,undefined,"POST")).url)}
    catch(err){setError((err as Error).message);setBusy(false)}
  }
  function navigate(tab:Tab){setPage(tab);setOffset(0);setError("");setNotice("")}
  const themeButton=<Button variant="ghost" aria-label="Toggle color theme" onClick={()=>setTheme(theme==="dark"?"light":"dark")}>{theme==="dark"?<Sun size={17}/>:<Moon size={17}/>}</Button>
  if(authed===null)return <div className="login"><Brand/><p>Loading workspace…</p></div>
  if(!authed)return <div className="login"><Card><div className="section-head"><Brand/>{themeButton}</div><h1>Sign in</h1><form onSubmit={async e=>{
    e.preventDefault();setBusy(true);setError("")
    try{csrf=(await api<{csrf:string}>("/login",Object.fromEntries(new FormData(e.currentTarget)),"POST")).csrf;setAuthed(true)}
    catch(err){setError((err as Error).message)}finally{setBusy(false)}
  }}><Field label="Username"><input name="username" autoComplete="username" required/></Field><Field label="Password"><input name="password" autoComplete="current-password" type="password" required/></Field>
  {error&&<p role="alert" className="feedback bad">{error}</p>}<Button type="submit" variant="primary" disabled={busy}>Sign in</Button></form></Card></div>
  return <div className="shell"><aside><Brand/><nav aria-label="Workspace">{(Object.keys(tabs) as Tab[]).map(name=>{
    const Icon=tabs[name]
    return <Button key={name} variant="ghost" aria-current={page===name?"page":undefined} onClick={()=>navigate(name)}><Icon size={18}/>{name}</Button>
  })}</nav><div className="sidebar-bottom"><Badge tone={data?.running?"good":"neutral"}>{data?.settings.paused?"Automation paused":data?.running?"● Scheduler online":"Checking status"}</Badge>
  <Button variant="ghost" onClick={async()=>{try{await api("/logout",undefined,"POST");csrf="";setData(undefined);setAuthed(false);navigate("Overview")}catch(err){setError((err as Error).message)}}}><LogOut size={17}/>Sign out</Button></div></aside>
  <main><header><div><div className="breadcrumb">Workspace / {page}</div><h1>{page==="Overview"?"Publishing overview":page}</h1></div><div className="actions">{data?.settings.dry_run&&<Badge tone="warn">Dry run</Badge>}{themeButton}</div></header>
  {error&&<p role="alert" className="feedback bad">{error}</p>}{notice&&<p role="status" className="feedback">{notice}</p>}
  {!data?<p>Loading dashboard…</p>:<fieldset disabled={busy} className="page">
   {page==="Overview"&&<Overview data={data} navigate={navigate}/>}
   {page==="Accounts"&&<Accounts accounts={data.accounts} connect={connect} task={task}/>}
   {page==="Sources"&&<Sources sources={data.sources} accounts={data.accounts} task={task}/>}
   {page==="Queue"&&<Queue jobs={data.queue} accounts={data.accounts} task={task} offset={offset} setOffset={setOffset}/>}
   {page==="Activity"&&<Card><h2>Activity log</h2><Logs rows={data.logs}/></Card>}
   {page==="Settings"&&<Settings options={data.settings} task={task}/>}
  </fieldset>}</main></div>
}
createRoot(document.getElementById("root")!).render(<App/>)

