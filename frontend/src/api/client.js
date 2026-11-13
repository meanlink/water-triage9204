import {session} from '../stores/session.js';
export class ApiError extends Error{
 constructor(message,detail,status){super(message);this.name='ApiError';this.detail=detail;this.status=status;}
}
export async function api(path,options={}){
 const r=await fetch('/api'+path,{...options,headers:{'Content-Type':'application/json',...(session.token?{Authorization:'Bearer '+session.token}:{}),...options.headers}});
 if(!r.ok){let d=await r.json().catch(()=>({detail:'连接失败，请稍后重试'}));if(r.status===401&&path!='/auth/login'){session.clear();location.hash='#/login';}
  const detail=d.detail;
  throw new ApiError(typeof detail==='string'?detail:(detail?.message||JSON.stringify(detail)),detail,r.status);
 }
 return r.json();
}
export async function download(id,format){
 const r=await fetch('/api/deliveries/'+id+'/download?format='+format,{headers:{Authorization:'Bearer '+session.token}});
 if(!r.ok)throw new Error('下载失败，请重试');
 const u=URL.createObjectURL(await r.blob()),a=document.createElement('a');a.href=u;a.download='分析归档-'+id+'.'+format;a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);
}
