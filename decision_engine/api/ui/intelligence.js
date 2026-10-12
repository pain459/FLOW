const api='/api/v1/intelligence';
let selected=null;
let pendingAsk=null;
const el=id=>document.getElementById(id);
function node(tag,text,cls){const n=document.createElement(tag);n.textContent=text;if(cls)n.className=cls;return n;}
function operationId(){
  if(typeof crypto.randomUUID==='function')return crypto.randomUUID();
  const bytes=crypto.getRandomValues(new Uint8Array(16));
  bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
  const hex=Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
  return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
}
async function get(path){const r=await fetch(api+path);if(!r.ok)throw Error(`Request failed: ${r.status}`);return r.json();}
async function refresh(){
  try{
    const [health,datasets,list,tools]=await Promise.all([get('/health'),get('/datasets'),get('/investigations'),get('/tools')]);
    el('health').textContent=`${health.status} · ${health.model.status}`;
    if(!el('dataset').options.length)for(const d of datasets.datasets){const o=node('option',`${d.id} · ${d.snapshot_count} observations`);o.value=d.id;el('dataset').append(o);}
    el('sessions').replaceChildren();
    for(const s of list.items){const b=node('button',`${s.mode==='live_question'?'Live question':'Replay'} · ${s.state} · ${s.id.slice(0,8)}\n${s.created_at}`,'session');b.onclick=()=>{selected=s.id;details();};el('sessions').append(b);}
    if(pendingAsk){
      const pending=list.items.find(s=>s.id===pendingAsk)||await get(`/investigations/${pendingAsk}`);
      if(pending.ended_at){pendingAsk=null;el('ask').disabled=false;el('ask-notice').textContent=pending.last_error==='FIRST_RESPONSE_COMPLETE'?'First response saved. Suggestions are hypotheses; inspect evidence and unknowns.':`Question ended (${pending.state}); review the saved evidence.`;}
    }
    el('tools').replaceChildren(...tools.tools.map(t=>node('span',`${t.tool_id} · ${t.execution_enabled?'enabled':'shadow only'}`,'tool')));
    if(selected)await details();
  }catch(e){el('notice').textContent=e.message;}
}
async function details(){
  const uid=selected;
  const [session,trace]=await Promise.all([get(`/investigations/${uid}`),get(`/investigations/${uid}/timeline`)]);
  if(selected!==uid)return;
  el('details').replaceChildren(node('h3',`${session.state} · recovery ${session.recovery_status}`));
  el('cancel').hidden=Boolean(session.ended_at);
  if(session.mode==='live_question'){
    if(trace.first_response)renderAnswer(trace.first_response);
    else el('answer').replaceChildren(node('p',session.ended_at?`No valid first response: ${session.last_error||session.state}. Evidence is unknown; no actions executed.`:'Collecting current evidence and waiting for Laya…'));
  }
  for(const d of trace.decisions){
    const box=node('div','', 'decision');box.append(node('h3',`Step ${d.step+1} · ${d.observation.observed_at}`));
    if(!d.normalized_answers?.suspected_subsystem){box.append(node('p',`No valid answer: ${d.validation_status||'pending'}`));el('details').append(box);continue;}
    const a=d.normalized_answers;
    box.append(node('p',`Suspected: ${a.suspected_subsystem.choice} · ordinal severity ${a.incident_severity.score.toFixed(2)} · needs evidence P(true) ${a.needs_more_evidence.noul.toFixed(3)}`));
    box.append(node('p',`Proposed ${d.policy_decision.proposed} → policy ${d.policy_decision.selected} (${d.policy_decision.verdict}); executed: no`));
    for(const [label,p] of Object.entries(a.next_diagnostic_tool.probabilities)){const row=node('div','', 'probability');row.append(node('span',label));const meter=document.createElement('meter');meter.min=0;meter.max=1;meter.value=p;row.append(meter,node('span',`${(p*100).toFixed(1)}%`));box.append(row);}
    box.append(node('p',`Fixed rules: ${d.baseline_decision.subsystem} / ${d.baseline_decision.tool}. Inference ${d.latency_ms.toFixed(0)} ms.`));
    const disclosure=document.createElement('details');disclosure.append(node('summary','Observation and source freshness'),node('pre',JSON.stringify(d.observation,null,2)));box.append(disclosure);el('details').append(box);
  }
}
function renderAnswer(a){
  const box=el('answer');box.replaceChildren(node('h3',`Possible reason: ${a.reason}`));
  box.append(node('p',`Suspected subsystem: ${a.suspected_subsystem}. Suggested human check: ${a.next_check}. No action executed.`));
  if(a.override_reason)box.append(node('p',`Model proposal ${a.proposal_reason_code} was withheld: ${a.override_reason}. The evidence does not support that conclusion.`));
  box.append(node('p',`Observed ${a.observed_at} · system window ${a.window_seconds}s · needs more evidence P(true) ${a.needs_more_evidence_probability.toFixed(3)}`));
  const list=document.createElement('ul');for(const h of a.hypotheses)list.append(node('li',`${h.reason} · model score ${(h.model_score*100).toFixed(1)}% · ${h.symptom_support?'supporting symptoms present':'unsupported by captured symptoms'}`));box.append(node('h4','Ranked possibilities'),list,node('p',a.score_interpretation,'muted'));
  const evidence=document.createElement('ul');for(const fact of a.evidence)evidence.append(node('li',fact));box.append(node('h4','Supporting observations'),a.evidence.length?evidence:node('p','No failure-specific evidence captured. Ask with a recent request ID, trace ID or recognized error.'));
  const unknowns=document.createElement('details');const ul=document.createElement('ul');for(const value of a.unknowns)ul.append(node('li',value));unknowns.append(node('summary',`Unknowns and limits (${a.unknowns.length})`),ul);box.append(unknowns);
}
el('ask-form').onsubmit=async e=>{
  e.preventDefault();el('ask').disabled=true;
  const body={error_excerpt:el('error-excerpt').value,lookback_seconds:Number(el('lookback').value)};
  if(el('request-id').value.trim())body.request_id=el('request-id').value.trim();
  if(el('trace-id').value.trim())body.trace_id=el('trace-id').value.trim();
  try{
    const r=await fetch(api+'/ask',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+el('token').value,'Idempotency-Key':operationId()},body:JSON.stringify(body)});
    const result=await r.json();if(!r.ok)throw Error(`Question refused (${r.status}): ${result.detail||result.code||'invalid request'}`);
    selected=result.id;pendingAsk=result.id;el('ask-notice').textContent='Collecting fresh system signals and correlated call evidence. Laya has no experiment metadata.';await refresh();
  }catch(error){el('ask-notice').textContent=error.message;el('ask').disabled=false;}
};
el('start-form').onsubmit=async e=>{e.preventDefault();el('start').disabled=true;try{const r=await fetch(api+'/replays',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+el('token').value,'Idempotency-Key':operationId()},body:JSON.stringify({dataset_ref:el('dataset').value,mode:'shadow'})});const b=await r.json();if(!r.ok)throw Error(`Replay refused (${r.status}): ${b.detail||b.code||'invalid request'}`);selected=b.id;el('notice').textContent='Shadow replay started; zero diagnostics execute.';await refresh();}catch(error){el('notice').textContent=error.message;}finally{el('start').disabled=false;}};
el('cancel').onclick=async()=>{const r=await fetch(api+`/investigations/${selected}/cancel`,{method:'POST',headers:{'Authorization':'Bearer '+el('token').value}});el('notice').textContent=r.ok?'Cancelled safely.':`Cancellation refused (${r.status}).`;await refresh();};
el('refresh').onclick=refresh;
refresh();setInterval(refresh,5000);
