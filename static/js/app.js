const $ = (id) => document.getElementById(id);
const page = document.body.dataset.page;
let catalog = { reference: [], current: [], pairs: [] };
let detectorConfig = {};

function setClock(){ const el=$("clock"); if(el) el.textContent=new Date().toLocaleString(); }
setClock(); setInterval(setClock,1000);

function toast(message, danger=false){ const box=$("toast"); if(!box) return; box.textContent=message; box.style.borderColor=danger?"rgba(255,70,93,.45)":"rgba(83,216,255,.28)"; box.classList.add("show"); setTimeout(()=>box.classList.remove("show"),3200); }
function escapeHtml(v){ return String(v??"").replace(/[&<>'\"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'\"':"&quot;"}[c])); }
function setImage(id,url){ const el=$(id); if(el) el.src=url||""; }
function showModal(url,caption=""){ if(!url)return; $("modalImage").src=url; $("modalCaption").textContent=caption; $("imageModal").classList.add("show"); }
document.querySelectorAll("[data-close-modal]").forEach(x=>x.addEventListener("click",()=>$("imageModal").classList.remove("show")));
$("imageModal")?.addEventListener("click",e=>{if(e.target.id==="imageModal") e.currentTarget.classList.remove("show");});

async function getJson(url,options){ const res=await fetch(url,options); const data=await res.json(); if(!res.ok) throw new Error(data.error||`Request failed (${res.status})`); return data; }
function fillSelect(el,items,selected){ if(!el)return; el.innerHTML=items.map(item=>`<option value="${escapeHtml(item.name)}" ${item.name===selected?"selected":""}>${escapeHtml(item.name)}</option>`).join(""); }

function pairCard(pair,compact=false){
  return `<article class="${compact?"pair-mini":"pair-card"}" data-pair="${pair.id}">
    ${compact?"":`<div class="pair-card-head"><span class="badge">${escapeHtml(pair.label)}</span><small>${escapeHtml(pair.pairing)}</small></div>`}
    <div class="${compact?"pair-mini-images":"pair-images"}">
      <img src="${pair.before.url}" alt="Before fire" data-preview="${pair.before.url}" data-caption="Before fire · ${escapeHtml(pair.before.name)}">
      <img src="${pair.after.url}" alt="After fire" data-preview="${pair.after.url}" data-caption="After/current · ${escapeHtml(pair.after.name)}">
    </div>
    <div class="${compact?"pair-mini-body":"pair-card-body"}"><strong>${escapeHtml(pair.label)}</strong><small>${escapeHtml(pair.before.name)} → ${escapeHtml(pair.after.name)}</small>${compact?"":`<div class="pair-card-actions"><button class="mini-btn" data-analyze-pair="${pair.id}">Analyze Pair</button><button class="mini-btn" data-preview="${pair.before.url}" data-caption="Before fire · ${escapeHtml(pair.before.name)}">View Before</button><button class="mini-btn" data-preview="${pair.after.url}" data-caption="After/current · ${escapeHtml(pair.after.name)}">View After</button></div>`}</div>
  </article>`;
}

document.addEventListener("click",e=>{
  const preview=e.target.closest("[data-preview]"); if(preview) showModal(preview.dataset.preview,preview.dataset.caption||"");
  const analyze=e.target.closest("[data-analyze-pair]"); if(analyze) window.location=`/detection?pair=${encodeURIComponent(analyze.dataset.analyzePair)}`;
});

async function initDashboard(){
  const data=await getJson("/api/dashboard");
  $("statPairs").textContent=data.stats.image_pairs;
  $("statFires").textContent=data.stats.fire_events;
  $("statHealth").textContent=`${data.stats.system_health}%`;
  $("statGps").textContent=(data.gps.latitude||data.gps.longitude)?"GPS Valid":"GPS Pending";
  $("statCoords").textContent=`${data.gps.latitude}, ${data.gps.longitude}`;
  $("dashDrone").textContent=data.mission.drone_id;
  $("dashMode").textContent=data.mission.flight_mode;
  $("dashboardPairs").innerHTML=data.pairs.slice(0,3).map(p=>pairCard(p,true)).join("")||`<p>No image pairs found.</p>`;
  const telemetry=[
    ["Battery",`${data.mission.battery}%`],["Signal",`${data.mission.signal}%`],["Altitude",`${data.gps.altitude_m} m`],["Wind",data.mission.wind],["Ambient",data.mission.ambient_temperature],["Humidity",data.mission.humidity]
  ];
  $("telemetryCards").innerHTML=telemetry.map(([k,v])=>`<div class="telemetry-card"><span>${k}</span><strong>${v}</strong></div>`).join("");
  $("capabilities").innerHTML=data.capabilities.map(x=>`<div class="capability">✓ ${escapeHtml(x)}</div>`).join("");
}

async function initDetection(){
  const data=await getJson("/api/images"); catalog=data; detectorConfig=data.detector_config||{};
  const params=new URLSearchParams(location.search); const requested=params.get("pair");
  const pair=(requested&&data.pairs.find(p=>p.id===requested))||data.pairs[0];
  const ref=pair?.before.name||data.default_reference; const cur=pair?.after.name||data.default_current;
  fillSelect($("referenceSelect"),data.reference,ref); fillSelect($("currentSelect"),data.current,cur);
  $("latInput").value=data.gps.latitude; $("lonInput").value=data.gps.longitude; $("altInput").value=data.gps.altitude_m;
  $("minArea").value=detectorConfig.min_area_percent; $("confThreshold").value=detectorConfig.confidence_threshold; $("heatGate").value=detectorConfig.heat_gate;
  previewDetectionPair();
  $("referenceSelect").addEventListener("change",previewDetectionPair); $("currentSelect").addEventListener("change",previewDetectionPair); $("runDetection").addEventListener("click",runDetection);
}
function previewDetectionPair(){ const ref=$("referenceSelect").value,cur=$("currentSelect").value; setImage("beforePreview",`/media/reference/${encodeURIComponent(ref)}`);setImage("afterPreview",`/media/current/${encodeURIComponent(cur)}`);$("beforeName").textContent=ref;$("afterName").textContent=cur; }
async function runDetection(){
  const btn=$("runDetection"); btn.disabled=true; btn.textContent="Analyzing…";
  try{
    const payload={reference_image:$("referenceSelect").value,current_image:$("currentSelect").value,latitude:Number($("latInput").value),longitude:Number($("lonInput").value),altitude_m:Number($("altInput").value),detector_config:{...detectorConfig,min_area_percent:Number($("minArea").value),confidence_threshold:Number($("confThreshold").value),heat_gate:Number($("heatGate").value)}};
    const data=await getJson("/api/analyze",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
    $("detectionResult").classList.remove("hidden"); $("resultStatus").textContent=data.status; $("resultStatus").style.color=data.fire_detected?"#ff9cab":"#baffea"; $("resultConfidence").textContent=`${data.confidence}%`; $("resultSeverity").textContent=data.severity; $("resultLatency").textContent=`${data.processing_ms} ms`; $("resultArea").textContent=`${data.hotspot_area_percent}%`; setImage("resultImage",data.result_url);setImage("differenceImage",data.diff_url);setImage("maskImage",data.mask_url);$("downloadEvidence").href=data.result_url; $("decisionText").textContent=data.fire_detected?`A new high-thermal-contrast region was detected against the baseline. ${data.bbox_count} region(s) crossed the configured threshold at ${data.confidence}% confidence. GPS ${data.gps_valid?"is valid":"is not fixed"}.`:`The current frame was compared against the baseline and no fire-level thermal growth crossed the configured threshold.`; $("detectionResult").scrollIntoView({behavior:"smooth"}); toast(data.fire_detected?"Fire detected. Evidence captured.":"Analysis complete. No fire detected.");
  }catch(err){toast(err.message,true)}finally{btn.disabled=false;btn.textContent="Analyze Pair";}
}

let libraryPairs=[];
async function initLibrary(){ const data=await getJson("/api/pairs"); libraryPairs=data.pairs; renderLibrary(); $("librarySearch").addEventListener("input",renderLibrary);$("libraryFilter").addEventListener("change",renderLibrary);$("refreshLibrary").addEventListener("click",async()=>{const fresh=await getJson("/api/pairs");libraryPairs=fresh.pairs;renderLibrary();toast("Evidence library refreshed.")}); }
function renderLibrary(){ const q=($("librarySearch").value||"").toLowerCase(),filter=$("libraryFilter").value;const filtered=libraryPairs.filter(p=>(filter==="all"||p.pairing===filter)&&(`${p.label} ${p.before.name} ${p.after.name}`.toLowerCase().includes(q)));$("libraryCount").textContent=`${filtered.length} pairs`;$("pairLibrary").innerHTML=filtered.map(p=>pairCard(p,false)).join("")||`<p>No matching evidence pairs.</p>`; }

async function initBatch(){ const data=await getJson("/api/pairs"); catalog.pairs=data.pairs; $("batchPairs").textContent=data.pairs.length; $("batchResults").innerHTML=data.pairs.map(p=>`<div class="batch-row"><img src="${p.after.url}"><div><strong>${escapeHtml(p.label)}</strong><small>${escapeHtml(p.before.name)} → ${escapeHtml(p.after.name)}</small></div><strong>Queued</strong><small>--</small><small>--</small><small>--</small></div>`).join("");$("runBatch").addEventListener("click",runBatch); }
async function runBatch(){ const btn=$("runBatch");btn.disabled=true;btn.textContent="Processing…";$("batchProgress").style.width="35%";try{const data=await getJson("/api/batch/analyze",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({pair_ids:catalog.pairs.map(p=>p.id)})});$("batchProgress").style.width="100%";$("batchProcessed").textContent=data.summary.processed;$("batchFires").textContent=data.summary.fire_count;$("batchConfidence").textContent=`${data.summary.average_confidence}%`;$("batchResults").innerHTML=data.results.map((r,i)=>{const pair=catalog.pairs.find(p=>p.id===r.pair_id);return `<div class="batch-row"><img src="${r.result_url||pair?.after.url||""}" data-preview="${r.result_url||pair?.after.url||""}" data-caption="${escapeHtml(r.pair_label||pair?.label||"")}"><div><strong>${escapeHtml(r.pair_label||pair?.label||r.pair_id)}</strong><small>${r.ok?escapeHtml(r.status):escapeHtml(r.error)}</small></div><strong>${r.ok?`${r.confidence}%`:"Failed"}</strong><small>${r.severity||"--"}</small><small>${r.bbox_count??"--"} regions</small><small>${r.processing_ms?`${r.processing_ms} ms`:"--"}</small></div>`}).join("");toast(`Batch complete: ${data.summary.fire_count} fire detections.`);}catch(err){toast(err.message,true)}finally{btn.disabled=false;btn.textContent="Analyze All Pairs";}}

let allEvents=[];
async function initEvents(){ const data=await getJson("/api/events?limit=250");allEvents=data.events;renderEvents();$("eventSearch").addEventListener("input",renderEvents);$("severityFilter").addEventListener("change",renderEvents); }
function renderEvents(){const q=($("eventSearch").value||"").toLowerCase(),severity=$("severityFilter").value;const rows=allEvents.filter(e=>(!severity||e.severity===severity)&&(`${e.event_id} ${e.status} ${e.reference_image} ${e.current_image}`.toLowerCase().includes(q)));$("eventRows").innerHTML=rows.map(e=>`<tr><td>${escapeHtml(e.timestamp)}</td><td>${escapeHtml(e.status)}</td><td>${escapeHtml(e.severity)}</td><td>${escapeHtml(e.confidence)}%</td><td>${escapeHtml(e.latitude)}, ${escapeHtml(e.longitude)}</td><td>${e.result_url?`<span class="evidence-link" data-preview="${e.result_url}" data-caption="Event ${escapeHtml(e.event_id)}">View</span>`:"--"}</td></tr>`).join("")||`<tr><td colspan="6">No events found.</td></tr>`;}

async function initMission(){ const data=await getJson("/api/dashboard");$("missionDrone").textContent=data.mission.drone_id;$("missionZone").textContent=data.mission.zone;const t=[["Battery",`${data.mission.battery}%`],["Signal",`${data.mission.signal}%`],["Altitude",`${data.gps.altitude_m} m`],["Wind",data.mission.wind],["Ambient",data.mission.ambient_temperature],["Humidity",data.mission.humidity],["Flight Mode",data.mission.flight_mode],["Camera",data.mission.camera],["Edge Node",data.mission.edge_node],["GPS",data.mission.gps_module]];$("missionTelemetry").innerHTML=t.map(([k,v])=>`<div><span>${k}</span><strong>${escapeHtml(v)}</strong></div>`).join(""); }

async function initSettings(){const data=await getJson("/api/settings");const g=data.gps,d=data.detector;$("settingLat").value=g.latitude;$("settingLon").value=g.longitude;$("settingAlt").value=g.altitude_m;$("settingLocation").value=g.location_label;$("settingArea").value=d.min_area_percent;$("settingConfidence").value=d.confidence_threshold;$("settingDelta").value=d.min_delta_threshold;$("settingHeat").value=d.heat_gate;$("settingMorph").value=d.morph_kernel;$("settingContours").value=d.top_contours;$("saveSettings").addEventListener("click",saveSettings);}
async function saveSettings(){try{const payload={gps:{latitude:Number($("settingLat").value),longitude:Number($("settingLon").value),altitude_m:Number($("settingAlt").value),location_label:$("settingLocation").value},detector:{min_area_percent:Number($("settingArea").value),confidence_threshold:Number($("settingConfidence").value),min_delta_threshold:Number($("settingDelta").value),heat_gate:Number($("settingHeat").value),morph_kernel:Number($("settingMorph").value),top_contours:Number($("settingContours").value)}};await getJson("/api/settings",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});toast("Settings saved successfully.");}catch(err){toast(err.message,true)}}

(async()=>{try{if(page==="dashboard")await initDashboard();if(page==="detection")await initDetection();if(page==="library")await initLibrary();if(page==="batch")await initBatch();if(page==="events")await initEvents();if(page==="mission")await initMission();if(page==="settings")await initSettings();}catch(err){toast(err.message,true);console.error(err);}})();
