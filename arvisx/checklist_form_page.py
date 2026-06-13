"""The Phase-0 mobile checklist form — a single self-contained page served at GET /forms.
Dependency-free (vanilla JS); talks to /api/v1/forms/*. Phone-first so the technician
fills it on the floor, each entry server-timestamped (no Saturday backfill)."""

FORM_HTML = r"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>ArvisX — Daily Checklist</title>
<style>
  :root{--bg:#0f1216;--card:#1a1f26;--line:#2a313b;--ink:#e7ecf2;--mute:#94a0ad;
        --ok:#27c08a;--issue:#e0533d;--accent:#3b9eff;--warn:#e2a03f;}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 -apple-system,Segoe UI,Roboto,sans-serif}
  header{position:sticky;top:0;background:#11151a;border-bottom:1px solid var(--line);padding:10px 14px;z-index:5}
  h1{font-size:16px;margin:0 0 6px}
  .bar{height:7px;background:#22292f;border-radius:6px;overflow:hidden}
  .bar>i{display:block;height:100%;background:var(--ok);width:0;transition:width .3s}
  .meta{display:flex;justify-content:space-between;font-size:12px;color:var(--mute);margin-top:5px}
  main{padding:12px 14px 90px;max-width:680px;margin:0 auto}
  .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 12px;margin:0 0 10px}
  .pick{cursor:pointer} .pick:active{opacity:.7}
  .pick b{font-size:15px} .pick .sub{color:var(--mute);font-size:12px}
  label.fld{display:block;color:var(--mute);font-size:12px;margin:10px 0 4px}
  input,select,textarea{width:100%;background:#0f141a;border:1px solid var(--line);color:var(--ink);
        border-radius:9px;padding:10px;font-size:15px}
  .sec{font-size:13px;letter-spacing:.4px;text-transform:uppercase;color:var(--accent);margin:16px 2px 6px}
  .item{border-bottom:1px solid var(--line);padding:10px 0}
  .item:last-child{border-bottom:0}
  .ilabel{display:flex;justify-content:space-between;gap:8px;align-items:center}
  .ilabel .nm{flex:1}
  .tag{font-size:11px;padding:2px 7px;border-radius:20px}
  .tag.ok{background:rgba(39,192,138,.15);color:var(--ok)}
  .tag.issue{background:rgba(224,83,61,.15);color:var(--issue)}
  .tick{display:flex;gap:8px;margin-top:6px}
  .tick button{flex:1;padding:9px;border-radius:9px;border:1px solid var(--line);background:#0f141a;color:var(--ink);font-size:14px}
  .tick button.on-ok{background:var(--ok);border-color:var(--ok);color:#04231a}
  .tick button.on-issue{background:var(--issue);border-color:var(--issue);color:#2a0a05}
  .row{display:flex;gap:8px;align-items:center}
  .unit{color:var(--mute);font-size:13px;white-space:nowrap}
  .note{margin-top:6px;font-size:13px;padding:7px}
  footer{position:fixed;bottom:0;left:0;right:0;background:#11151a;border-top:1px solid var(--line);padding:10px 14px}
  .btn{display:block;width:100%;padding:12px;border:0;border-radius:10px;background:var(--accent);color:#03121f;font-size:15px;font-weight:600}
  .btn.ghost{background:#222;color:var(--ink)}
  .signoff{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
  .signoff button{flex:1 1 30%;padding:9px;border-radius:9px;border:1px solid var(--line);background:#0f141a;color:var(--ink);font-size:13px}
  .signoff button.done{background:rgba(39,192,138,.15);border-color:var(--ok);color:var(--ok)}
  .banner{background:rgba(224,83,61,.12);border:1px solid var(--issue);color:#ffb3a6;border-radius:9px;padding:8px 10px;margin-bottom:10px;font-size:13px}
  .muted{color:var(--mute);font-size:12px}
  .hide{display:none}
</style></head>
<body>
<header>
  <h1 id="title">ArvisX — Daily Checklist</h1>
  <div class="bar"><i id="prog"></i></div>
  <div class="meta"><span id="metaL">Pick a checklist</span><span id="metaR"></span></div>
</header>
<main id="main"></main>
<footer id="foot" class="hide"></footer>

<script>
const API="/api/v1/forms";
let TPL=null, RUN=null, BUILDING="one-anthem";
const $=(id)=>document.getElementById(id);

async function jget(u){const r=await fetch(u);if(!r.ok)throw new Error(await r.text());return r.json();}
async function jpost(u,b){const r=await fetch(u,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(b||{})});if(!r.ok)throw new Error(await r.text());return r.json();}

function setProgress(s){
  $("prog").style.width=(s.completion_pct||0)+"%";
  $("metaR").textContent=s.done+"/"+s.total+" · "+(s.issues?s.issues.length:0)+" issue(s)";
}

async function showPicker(){
  $("foot").classList.add("hide");
  const d=await jget(API+"/templates?building="+BUILDING);
  $("title").textContent="ArvisX — "+(d.building||"").replace(/-/g," ");
  $("metaL").textContent="Pick a checklist";
  let h='<label class="fld">Your name</label><input id="tech" placeholder="technician name">';
  d.templates.forEach(t=>{
    h+=`<div class="card pick" onclick="start('${t.template_id}','${(t.per_asset&&t.per_asset.length)?'1':''}')">
      <b>${t.name}</b><div class="sub">${t.timing||''} · ${t.items} items${t.cadence==='quarterly'?' · quarterly':''}</div></div>`;
  });
  $("main").innerHTML=h;
}

async function start(tid, perAsset){
  const tech=($("tech")&&$("tech").value)||"";
  let asset="";
  if(perAsset){asset=prompt("Which asset/panel? (e.g. MSB, DG Panel)")||"";}
  RUN=await jpost(API+"/run",{template_id:tid,building:BUILDING,technician:tech,asset:asset});
  TPL=RUN.template;
  renderForm();
}

function entryOf(id){return (RUN.entries&&RUN.entries[id])||null;}

function renderForm(){
  $("title").textContent=TPL.name + (RUN.run.asset?(" · "+RUN.run.asset):"");
  $("metaL").textContent=(RUN.run.technician||"—")+" · "+RUN.run.shift_date;
  const submitted=RUN.run.status!=="open";
  let h="";
  if(submitted) h+='<div class="banner" style="background:rgba(39,192,138,.12);border-color:var(--ok);color:#9ff0cf">Submitted — read-only. Sign-off below.</div>';
  const iss=RUN.summary.issues||[];
  if(iss.length) h+=`<div class="banner">⚠️ ${iss.length} issue(s) flagged: ${iss.map(i=>i.label).join(', ')}</div>`;
  TPL.sections.forEach(sec=>{
    h+=`<div class="sec">${sec.name}</div><div class="card">`;
    sec.items.forEach(it=>{ h+=renderItem(it,submitted); });
    h+="</div>";
  });
  $("main").innerHTML=h;
  setProgress(RUN.summary);
  // footer
  let f="";
  if(!submitted){ f+='<button class="btn" onclick="submitRun()">Submit checklist</button>'; }
  else { f+=signoffRow(); }
  $("foot").innerHTML=f; $("foot").classList.remove("hide");
}

function renderItem(it,ro){
  const e=entryOf(it.item_id); const dis=ro?"disabled":"";
  let tag="";
  if(e&&e.is_issue) tag='<span class="tag issue">issue</span>';
  else if(e) tag='<span class="tag ok">✓ '+(e.ts?e.ts.slice(11,16):'')+'</span>';
  let ctl="";
  if(it.kind==="tick"){
    const ok=e&&e.status==="ok"?"on-ok":"", is=e&&e.status==="issue"?"on-issue":"";
    ctl=`<div class="tick">
      <button class="${ok}" ${dis} onclick="saveTick('${it.item_id}','ok')">Done</button>
      <button class="${is}" ${dis} onclick="saveTick('${it.item_id}','issue')">Issue</button></div>`;
  } else if(it.kind==="state"){
    let opts='<option value="">—</option>'+it.options.map(o=>`<option ${e&&e.value===o?'selected':''}>${o}</option>`).join("");
    ctl=`<select ${dis} onchange="saveVal('${it.item_id}',this.value)">${opts}</select>`;
  } else if(it.kind==="reading"){
    ctl=`<div class="row"><input type="number" step="any" ${dis} value="${e?e.value:''}"
        onchange="saveVal('${it.item_id}',this.value)" placeholder="reading">
        <span class="unit">${it.unit||''}</span></div>`;
  } else {
    ctl=`<textarea class="note" rows="2" ${dis} onchange="saveVal('${it.item_id}',this.value)"
        placeholder="notes">${e?e.value:''}</textarea>`;
  }
  return `<div class="item"><div class="ilabel"><span class="nm">${it.label}</span>${tag}</div>${ctl}</div>`;
}

async function saveTick(id,status){ await save(id,status,status); }
async function saveVal(id,val){ await save(id,val,""); }
async function save(id,value,status){
  const r=await jpost(API+"/run/"+RUN.run.id+"/entry",{item_id:id,value:value,status:status});
  RUN=await jget(API+"/run/"+RUN.run.id);   // refresh entries+summary
  TPL=RUN.template; renderForm();
}

async function submitRun(){
  if(!confirm("Submit this checklist? Entries lock after submit.")) return;
  RUN=await jpost(API+"/run/"+RUN.run.id+"/submit",{}); TPL=RUN.template; renderForm();
}

function signoffRow(){
  const done=new Set((RUN.signoffs||[]).map(s=>s.role));
  let h='<div class="muted">Sign-off chain</div><div class="signoff">';
  (TPL.signoff_roles||[]).forEach(r=>{
    h+=`<button class="${done.has(r)?'done':''}" onclick="signoff('${r}')">${done.has(r)?'✓ ':''}${r}</button>`;
  });
  h+='</div><button class="btn ghost" style="margin-top:8px" onclick="showPicker()">← Back to checklists</button>';
  return h;
}
async function signoff(role){
  const by=prompt("Sign as "+role+" — name?")||"";
  RUN=await jpost(API+"/run/"+RUN.run.id+"/signoff",{role:role,by:by}); TPL=RUN.template; renderForm();
}

showPicker();
</script>
</body></html>
"""
