"use strict";
const policy = JSON.parse(document.getElementById("reader-policy").textContent);
const byId = id => document.getElementById(id);
let candidates = [], projectName = "Your project", ready = false, busy = false, currentVersion = -1;
function activity(message, error=false) { byId("activity").textContent=message; byId("activity").classList.toggle("error",error); }
function controls() {
  ["clear-session","clear-session-confirm","clear-session-cancel"].forEach(id=>{byId(id).disabled=busy;});
  ["folder-button","folder-input","files-input","example-button","restart-goal","version-picker"].forEach(id=>{byId(id).disabled=busy;});
  byId("preview-button").disabled=busy || !candidates.length;
  byId("analyze-button").disabled=busy || !ready;
  byId("revise-button").disabled=busy || currentVersion<0;
  byId("export-format").disabled=busy || currentVersion<0;
  byId("save-review").setAttribute("aria-disabled",String(busy || currentVersion<0));
  if(byId("read-button"))byId("read-button").disabled=busy || currentVersion<0;
  if(byId("record-button"))byId("record-button").disabled=busy && byId("record-button").dataset.recording!=="true";
  document.querySelectorAll("#file-list input").forEach(input=>{input.disabled=busy;});
}
async function requestJSON(url, data) {
  const response=await fetch(url, data===undefined ? {} : {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)});
  const result=await response.json();
  if(!response.ok) throw new Error(result.error || "The request did not complete.");
  return result;
}
async function operation(action) {
  if(busy)return;
  busy=true;controls();
  try { await action(); } catch(error) { activity(error.message,true); }
  finally { busy=false;controls(); }
}
function listFiles() {
  const list=byId("file-list");list.replaceChildren();
  candidates.forEach((file,index)=>{
    const item=document.createElement("li"),label=document.createElement("label"),box=document.createElement("input");
    box.type="checkbox";box.checked=true;box.dataset.index=index;
    box.addEventListener("change",()=>{ready=false;byId("analyze-button").disabled=true;activity("Selection changed. Review the selected files again before analyzing.");});
    label.append(box,document.createTextNode(file.path));item.append(label);list.append(item);
  });
  byId("selection-details").hidden=false;byId("selection-count").textContent=candidates.length+" readable files selected";
  byId("selection-label").textContent=candidates.length+" source files selected";
  byId("project-chip-name").textContent=projectName;
  byId("project-chip").hidden=false;
}
function allowName(path) {
  const parts=path.toLowerCase().replaceAll("\\","/").split("/"),name=parts.at(-1);
  if(parts.some(p=>!p || p==="." || p===".." || p.includes(":")))return false;
  if(parts.slice(0,-1).some(p=>p.startsWith(".") || policy.excluded_folders.includes(p)))return false;
  if(name.startsWith(".env") || policy.sensitive_names.includes(name) || /\.(pem|key|p12|pfx)$/.test(name))return false;
  if(name.startsWith(".") && !policy.text_names.includes(name))return false;
  if(/(-lock\.json|\.lock)$/.test(name))return false;
  return policy.text_names.includes(name) || policy.text_suffixes.some(suffix=>name.endsWith(suffix));
}
function priority(file) {
  const name=file.path.split("/").at(-1).toLowerCase();
  if(file.path.indexOf("/")<0 && name.startsWith("readme"))return 0;
  if(policy.manifests.includes(name))return 1;
  return /\.(py|js|jsx|ts|tsx|html|css|sql|sh|ps1|go|rs|java|c|h|cpp|cs|rb|php)$/.test(name)?2:3;
}
async function chooseFiles(files, folder, selectedName=null, excluded=0, note="") {
  const selected=Array.from(files);
  if(!selected.length && !selectedName)return;
  if(folder && !selectedName && selected.some(file=>!file.webkitRelativePath?.includes("/"))) {
    throw new Error("The browser returned individual files, not a project folder. Open this page in Edge or Chrome and use Open project folder.");
  }
  if(typeof stopNarration==="function")stopNarration();
  ready=false;currentVersion=-1;byId("version-controls").hidden=true;byId("feedback-panel").hidden=true;byId("save-panel").hidden=true;
  byId("source-count").textContent="0";window.revivalNavigation?.reset();
  if(byId("model-status"))byId("model-status").hidden=true;
  byId("report-content").textContent="Review the selected files, then ask Gemma for a restart plan.";
  byId("source-content").replaceChildren();byId("file-picker").replaceChildren();byId("file-picker").disabled=true;
  candidates=[];let total=0, skipped=excluded;
  projectName=selectedName || (folder ? selected[0].webkitRelativePath.split("/")[0] : "Selected project files");
  const eligible=(selectedName ? selected : selected.map(file=>({file,path:folder ? file.webkitRelativePath.split("/").slice(1).join("/") : file.name})))
    .filter(item=>{if(!allowName(item.path) || item.file.size>65536){skipped++;return false;}return true;})
    .sort((a,b)=>priority(a)-priority(b) || a.path.split("/").length-b.path.split("/").length || a.path.localeCompare(b.path));
  for(const item of eligible.slice(0,1000)) {
    if(candidates.length>=40 || total+item.file.size>160000){skipped++;continue;}
    try {
      const text=new TextDecoder("utf-8",{fatal:true}).decode(await item.file.arrayBuffer());
      if(text.includes("\0") || !text.trim()){skipped++;continue;}
      candidates.push({path:item.path,text});total+=item.file.size;
    } catch { skipped++; }
  }
  byId("project-name").textContent=projectName;listFiles();
  byId("selection-details").open=true;
  activity(candidates.length+" text files ready for review. "+skipped+" files or folders excluded. "+note+"Nothing has been sent to Gemma.");
}
function applyPreview(result) {
  if(typeof stopNarration==="function")stopNarration();
  if(byId("model-status"))byId("model-status").hidden=true;
  candidates=result.files;projectName=result.name;ready=true;currentVersion=-1;
  byId("project-name").textContent=projectName;listFiles();
  byId("source-content").innerHTML=result.source_html;
  byId("file-picker").innerHTML=result.source_options;byId("file-picker").disabled=false;
  byId("report-content").textContent="Your file preview is ready. Inspect it in Sources, then return to Project to build your restart plan.";
  byId("version-controls").hidden=true;byId("feedback-panel").hidden=true;byId("save-panel").hidden=true;
  byId("source-count").textContent=String(result.manifest.file_count);
  byId("plan-project-name").textContent=projectName;
  window.revivalNavigation?.reset();
  window.revivalNavigation?.select("sources",true);
  byId("source-status").textContent="Previewing "+result.manifest.file_count+" files. Choose one to inspect.";
  activity(projectName+": "+result.manifest.file_count+" files reviewed; "+result.manifest.skipped.length+" excluded. Ready for analysis.");
}
function applyAnalysis(result) {
  if(typeof stopNarration==="function")stopNarration();
  const modelStatus=byId("model-status");
  if(modelStatus) {
    modelStatus.textContent=result.fallback_used ? "Grok backup used · Gemma's service was temporarily unavailable." : "Analysis by Gemma";
    modelStatus.hidden=false;
  }
  byId("report-content").innerHTML=result.report_html;currentVersion=result.version;
  const versions=byId("version-picker");versions.replaceChildren();
  for(let i=0;i<result.versions;i++) {
    const option=document.createElement("option");option.value=i;option.textContent="Version "+(i+1)+(i===0?" · Original":" · Revised");
    option.selected=i===currentVersion;versions.append(option);
  }
  byId("version-controls").hidden=false;byId("feedback-panel").hidden=false;
  byId("feedback-panel").open=true;
  byId("save-panel").hidden=false;updateExport();
  window.revivalNavigation?.select("plan",true);
  let message="Analysis ready in "+result.seconds+" seconds. Select a reference to inspect its source.";
  if(result.finish_reason==="length")message="The response reached its length limit. Review it before continuing.";
  if(result.reference_issues.length)message+=" Some references could not be matched to source locations.";
  activity(message);
}
byId("folder-button").addEventListener("click",()=>{
  if(busy)return;
  if(typeof window.showDirectoryPicker!=="function") {
    if(!("webkitdirectory" in byId("folder-input"))) {
      activity("This browser cannot select a whole folder. Open the workbench in Edge or Chrome, or use the optional individual-file control.",true);
      return;
    }
    byId("folder-input").value="";byId("folder-input").click();return;
  }
  return operation(async()=>{
    let directory;
    try { directory=await window.showDirectoryPicker({id:"project-revival",mode:"read"}); }
    catch(error) {
      if(error.name==="AbortError"){activity("Folder selection cancelled. Your current review is unchanged.");return;}
      if(error.name==="NotAllowedError" || error.name==="SecurityError")throw new Error("Folder access wasn't granted. Try Open project folder again in Edge or Chrome; no files have been sent to Gemma.");
      throw error;
    }
    activity("Preparing "+directory.name+". Excluding credential and generated folders before reading project text…");
    const selection=await collectProjectFolder(directory,{excludedFolders:policy.excluded_folders,allowFile:allowName});
    let note=selection.limited?"Folder scan limit reached; this is a partial selection. ":"";
    if(selection.unreadable)note+=selection.unreadable+" items could not be read. ";
    await chooseFiles(selection.files,true,directory.name,selection.excluded,note);
  });
});
byId("folder-input").addEventListener("change",event=>operation(()=>chooseFiles(event.target.files,true)));
byId("files-input").addEventListener("click",event=>{if(busy)event.preventDefault();else event.target.value="";});
byId("files-input").addEventListener("change",event=>operation(()=>chooseFiles(event.target.files,false)));
byId("example-button").addEventListener("click",()=>operation(async()=>{
  activity("Loading the example project. No Gemma request is being made.");
  applyPreview(await requestJSON("/api/example"));
  byId("restart-goal").value="Help me return to this unfinished offline grant tracker and finish CSV export. Check the startup instructions and keep it local and simple.";
}));
byId("preview-button").addEventListener("click",()=>operation(async()=>{
  const indices=Array.from(document.querySelectorAll("#file-list input:checked")).map(box=>Number(box.dataset.index));
  if(!indices.length)throw new Error("Select at least one file.");
  activity("Preparing the source preview. Nothing is being sent to Gemma.");
  applyPreview(await requestJSON("/api/preview",{name:projectName,files:indices.map(index=>candidates[index])}));
}));
byId("analyze-button").addEventListener("click",()=>operation(async()=>{
  activity("Gemma is reading the reviewed files and preparing your restart plan…");
  applyAnalysis(await requestJSON("/api/analyze",{goal:byId("restart-goal").value}));
}));
byId("revise-button").addEventListener("click",()=>operation(async()=>{
  const feedback=byId("feedback").value.trim();if(!feedback)throw new Error("Enter your answers or changes before updating the plan.");
  activity("Using your answers and feedback to update the plan. The previous version will remain available…");
  applyAnalysis(await requestJSON("/api/revise",{version:currentVersion,feedback}));byId("feedback").value="";
}));
byId("version-picker").addEventListener("change",event=>operation(async()=>applyAnalysis(await requestJSON("/api/version/"+event.target.value))));
function updateExport() {
  byId("save-review").href="/api/export?version="+currentVersion+"&format="+byId("export-format").value;
}
byId("export-format").addEventListener("change",updateExport);
byId("save-review").addEventListener("click",event=>{if(busy || currentVersion<0)event.preventDefault();});
controls();
