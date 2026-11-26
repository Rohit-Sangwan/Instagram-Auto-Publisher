export type Account = {id:number;ig_id:string;username:string;picture:string|null;state:string;expires:number;can_publish:boolean;quota:number|null}
export type SourceInput = {profile:string;enabled:boolean;interval:number;kinds:string[];initial_count:number;existing:boolean;oldest:boolean;priority:number;destinations:number[]}
export type Source = Omit<SourceInput,"profile"> & {id:number;username:string;last_sync:number|null;status:string}
export type Options = {automatic:boolean;paused:boolean;dry_run:boolean;downloads:number;uploads:number;storage_mb:number;file_mb:number;retention_days:number;timezone:string;start:string;end:string;daily:number;interval:number}
export type Job = {id:number;state:string;priority:number;next_run:number;scheduled_for:number|null;error:string|null;source:string;destination:string;kind:string;size:number;duration:number;origin:string|null;permalink:string|null;assets:{id:number;mime:string}[];progress:number;download:string|null}
export type Entry = {id:number;created:number;level:string;message:string}
export type Dashboard = {accounts:Account[];sources:Source[];queue:Job[];counts:Record<string,number>;settings:Options;cpu:number;ram:number;storage:number;disk_free:number;running:boolean;logs:Entry[]}
export type Task = (path:string,data?:unknown,method?:string)=>Promise<boolean>
export const kinds:Record<string,string> = {IMAGE:"Image",VIDEO:"Video",REELS:"Reel",CAROUSEL_ALBUM:"Carousel"}
export const bytes = (amount:number) => amount >= 1e9 ? `${(amount/1e9).toFixed(1)} GB` : `${(amount/1e6).toFixed(1)} MB`
export const date = (seconds:number) => new Date(seconds*1000).toLocaleString()
export const status = (value:string) => value.replaceAll("_"," ").replace(/^./,x=>x.toUpperCase())
export const tone = (value:string) => ["connected","published","ready","downloaded"].includes(value) ? "good" : ["failed","reconnect","uncertain"].includes(value) ? "bad" : ["uploading","dry_run","processing"].includes(value) ? "warn" : "neutral"
export const destinations = (accounts:Account[]) => accounts.filter(a=>a.can_publish && a.state==="connected")
