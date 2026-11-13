import {datasets} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {table} from '../components/common/table.js';
import {esc,notify} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';
import {parseCSV} from '../utils/csv.js';

const ACTION_LABELS={added:'新增',replaced:'替换',ignored:'忽略'};
const ACTION_CLASSES=new Set(Object.keys(ACTION_LABELS));
const tag=action=>'<span class="merge-tag '+(ACTION_CLASSES.has(action)?action:'ignored')+'">'+esc(ACTION_LABELS[action]||action)+'</span>';

// 历史接口缺省字段时的兜底，保证升级前的批次也能展示。
function normalizeDataset(d){
 if(!d)return d;
 return {...d,revision:d.revision??1,parent_dataset_id:d.parent_dataset_id??null,merge:d.merge??null};
}

function revisionPanel(selected){
 if(!selected)return '<section class="panel revision-panel"><p class="empty">先选择一个原批次，再补传更正记录。</p></section>';
 const role=session.user.role;
 return '<section class="panel revision-panel" id="revision-panel"><div class="section-title"><h2>补传更正 · 基于「'+esc(selected.name)+'」</h2><span>原批次 r'+selected.revision+' · '+selected.rows+' 条 · 不会被改写</span></div>'+
  '<p class="hint">只上传需要更正或新增的管段，每条带 segment_version（缺省视为 v1）。按管段取最高版本：旧版本晚到不覆盖，同版本同内容重复投递不新增样本。同版本内容冲突时整批拒绝并列出管段，原批次与已发起的试验不受影响。</p>'+
  '<form id="revision-form"><label>新批次名称（留空自动命名）<input name="name" placeholder="例如：'+esc(selected.name)+' · 11 月补传" maxlength="160"></label>'+
  '<label>补传 CSV 或 JSON<input type="file" id="revision-file" accept=".json,.csv"></label>'+
  '<label>补传记录 JSON<textarea name="records" rows="6" placeholder="粘贴 JSON 数组，或先选择上方文件" required></textarea></label>'+
  '<button type="submit" class="primary" '+(role==='viewer'?'disabled':'')+'>校验并生成完整新批次 ↗</button>'+
  '<p class="hint">仅含重复投递或旧版本时不会生成新批次，界面会列出每个被忽略的管段及原因。</p></form>'+
  '<div id="revision-result">'+(workspace.lastRevision?'<div class="revision-persisted">'+resultHtml(workspace.lastRevision)+'</div>':'')+'</div></section>';
}

function resultHtml(payload){
 const s=payload.summary||{},d=payload.details||[];
 const rows=d.map(x=>'<tr><td>'+esc(x.segment_id)+'</td><td>'+tag(x.action)+'</td><td>v'+esc(x.version)+'</td><td>'+esc(x.current_version==null?'—':'v'+x.current_version)+'</td><td>'+esc(x.reason)+'</td></tr>').join('');
 const head='<div class="revision-summary">'+[['新增',s.added],['替换',s.replaced],['忽略',s.ignored],['未变更',s.unchanged],['新批次总数',s.after_rows]].map(([k,v])=>'<div><span>'+k+'</span><strong>'+esc(v??0)+'</strong></div>').join('')+'</div>';
 const created=payload.created?'<p class="merge-ok">已生成完整新批次 <strong>'+esc(payload.dataset.name)+'</strong>（r'+payload.dataset.revision+' · '+payload.dataset.rows+' 条），原批次与既有试验保持不变。<a class="text-link" href="#/workbench">基于新批次发起试验 ↗</a></p>':'<p class="warning">'+esc(payload.message||'本次没有新增或替换，未生成新批次。')+'</p>';
 return created+head+'<div class="table-wrap"><table><thead><tr><th>管段</th><th>处理</th><th>本次版本</th><th>当前版本</th><th>原因</th></tr></thead><tbody>'+(rows||'<tr><td colspan="5">无处理明细</td></tr>')+'</tbody></table></div>';
}

function conflictHtml(error){
 const detail=error.detail||{},conflicts=detail.conflicts||[];
 if(!conflicts.length)return '<p class="warning">'+esc(error.message)+'</p>';
 return '<div class="conflict-block"><p class="warning">'+esc(detail.message||error.message)+'，原批次与已发起的试验不受影响。</p><div class="table-wrap"><table><thead><tr><th>管段</th><th>版本</th><th>冲突字段</th><th>原值</th><th>补传值</th></tr></thead><tbody>'+conflicts.map(c=>'<tr><td>'+esc(c.segment_id)+'</td><td>v'+esc(c.version)+'</td><td>'+esc((c.fields||[]).map(f=>f.label).join('、'))+'</td><td>'+esc((c.fields||[]).map(f=>f.from).join('、'))+'</td><td>'+esc((c.fields||[]).map(f=>f.to).join('、'))+'</td></tr>').join('')+'</tbody></table></div></div>';
}

export async function dataPage(){
 workspace.datasets=(await datasets.list()).map(normalizeDataset);
 let selectedId=workspace.selectedDataset||workspace.datasets[0]?.id;
 workspace.selectedDataset=selectedId;
 const selected=normalizeDataset(selectedId?await datasets.get(selectedId):null),m=workspace.meta;
 if(workspace.lastRevision&&workspace.lastRevision.base?.id!==selectedId)workspace.lastRevision=null;
 return heading('02 / DATA INTAKE','数据接入与批次追溯','保留原始业务字段、来源和内容指纹。补传更正会基于选定批次生成完整新批次，原批次保持不可变。')+
 '<div class="dataset-grid"><section class="panel"><div class="section-title"><h2>业务批次</h2><span>'+workspace.datasets.length+' 批</span></div><div class="batch-list">'+workspace.datasets.map(d=>'<button class="batch-item '+(d.id===selectedId?'active':'')+'" data-dataset="'+d.id+'"><strong>'+esc(d.name)+'</strong><span>r'+esc(d.revision||1)+' · '+d.rows+' 条 · '+esc(d.source)+(d.parent_dataset_id?' · 由 #'+d.parent_dataset_id+' 补传':'')+'</span><small>SHA256 '+esc(d.checksum.slice(0,18))+'…</small>'+(d.merge?'<small>新增 '+esc(d.merge.added)+' / 替换 '+esc(d.merge.replaced)+' / 忽略 '+esc(d.merge.ignored)+'</small>':'')+'</button>').join('')+'</div><div class="section-title"><h2>接入新数据</h2></div><form id="dataset-form"><label>批次名称<input name="name" required minlength="2" placeholder="例如：11 月复测批次"></label><label>上传 CSV 或 JSON<input type="file" id="file-input" accept=".json,.csv"></label><label>记录 JSON<textarea name="records" rows="6" placeholder="粘贴 JSON 数组，或先选择上方文件" required></textarea></label><p class="hint">字段：'+m.columns.map(c=>esc(c.key)+' / '+esc(c.label)+(c.optional?'（可选，缺省 '+esc(c.default)+'）':'')).join('，')+'。5–5,000 条记录。</p><button type="submit" class="primary" '+(session.user.role==='viewer'?'disabled':'')+'>校验并接入批次</button></form></section>'+
 '<div><section class="panel"><div class="section-title"><h2 id="preview-name">'+esc(selected?.name||'尚无批次')+'</h2><span>预览前 30 条</span></div><div id="data-preview">'+table(m.columns,selected?.records.slice(0,30)||[])+'</div></section>'+revisionPanel(selected)+(selected?.merge?mergeHistory(selected.merge):'')+'</div></div>';
}

function mergeHistory(merge){
 const d=merge.details||[];
 return '<section class="panel merge-history"><div class="section-title"><h2>本批次的补传来源</h2><span>基于 #'+esc(merge.base_dataset_id)+' '+esc(merge.base_name)+' · 原批次校验和 '+esc((merge.base_checksum||'').slice(0,18))+'…</span></div><div class="revision-summary">'+[['新增',merge.summary?.added],['替换',merge.summary?.replaced],['忽略',merge.summary?.ignored],['补传前',merge.summary?.before_rows],['补传后',merge.summary?.after_rows]].map(([k,v])=>'<div><span>'+k+'</span><strong>'+esc(v??0)+'</strong></div>').join('')+'</div><div class="table-wrap"><table><thead><tr><th>管段</th><th>处理</th><th>版本</th><th>原因</th></tr></thead><tbody>'+d.map(x=>'<tr><td>'+esc(x.segment_id)+'</td><td>'+tag(x.action)+'</td><td>v'+esc(x.version)+'</td><td>'+esc(x.reason)+'</td></tr>').join('')+'</tbody></table></div></section>';
}

export function bindData(refresh){
 let source='manual.json';
 document.querySelector('#file-input').addEventListener('change',async e=>{try{const file=e.target.files[0];if(!file)return;source=file.name;const text=await file.text(),records=file.name.endsWith('.csv')?parseCSV(text):JSON.parse(text);document.querySelector('[name=records]').value=JSON.stringify(records,null,2);}catch(error){notify(error.message,true);}});
 document.querySelectorAll('[data-dataset]').forEach(button=>button.onclick=async()=>{try{workspace.selectedDataset=Number(button.dataset.dataset);await refresh();}catch(error){notify(error.message,true);}});
 submit(document.querySelector('#dataset-form'),async f=>{await datasets.create({name:f.get('name'),source,records:JSON.parse(f.get('records'))});notify('数据已接入，可前往工作台执行分析');await refresh();});

 let revisionSource='补传记录.json';
 document.querySelector('#revision-file')?.addEventListener('change',async e=>{try{const file=e.target.files[0];if(!file)return;revisionSource=file.name;const text=await file.text(),records=file.name.endsWith('.csv')?parseCSV(text):JSON.parse(text);document.querySelector('#revision-form [name=records]').value=JSON.stringify(records,null,2);}catch(error){notify(error.message,true);}});
 const revisionForm=document.querySelector('#revision-form');
 submit(revisionForm,async f=>{
  const result=document.querySelector('#revision-result');
  try{
   const payload=await datasets.revise(workspace.selectedDataset,{name:f.get('name')||undefined,source:revisionSource,records:JSON.parse(f.get('records'))});
   // 生成新批次时由新批次的合并历史展示明细；未生成批次时保留本次处理清单。
   workspace.lastRevision=payload.created?null:payload;
   result.innerHTML=resultHtml(payload);
   notify(payload.created?'已生成完整新批次，可基于它发起试验':'补传未改变数据，未生成新批次');
   if(payload.created)workspace.selectedDataset=payload.dataset.id;
   await refresh();
  }catch(error){
   result.innerHTML=conflictHtml(error);
   notify(error.message,true);
  }
 });
}
