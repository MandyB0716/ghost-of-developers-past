const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ROOT = path.resolve(__dirname,"../..");
const {collectProjectFolder} = require(path.join(ROOT,"static/project-folder.js"));

function file(name, text="print('hello')") {
  const bytes=Buffer.from(text);
  return {kind:"file",name,async getFile(){return {name,size:bytes.length,async arrayBuffer(){return bytes;}};}};
}
function folder(name, entries) {
  return {kind:"directory",name,async *values(){yield* entries;}};
}
const options={excludedFolders:[".venv","node_modules"],allowFile:name=>name.endsWith(".py")};

test("selecting the root gathers nested code without opening excluded entries",async()=>{
  const forbiddenFile={kind:"file",name:".env",getFile(){throw Error("Must not read credentials");}};
  const forbiddenFolder={kind:"directory",name:".venv",values(){throw Error("Must not enter virtual environment");}};
  const root=folder("DevChallenge",[forbiddenFolder,forbiddenFile,folder("src",[file("worker.py")]),file("server.py")]);
  const selection=await collectProjectFolder(root,options);
  assert.deepEqual(selection.files.map(item=>item.path),["server.py","src/worker.py"]);
  assert.equal(selection.excluded,2);
  assert.equal(selection.unreadable,0);
});

test("unreadable subdirectories are reported without losing readable files",async()=>{
  const denied={kind:"directory",name:"restricted",async *values(){throw Error("Access denied");}};
  const selection=await collectProjectFolder(folder("project",[denied,file("app.py")]),options);
  assert.equal(selection.files.length,1);
  assert.equal(selection.unreadable,1);
});

test("large directory scans stop and explicitly report a partial selection",async()=>{
  const entries=Array.from({length:1002},(_,i)=>file(`module-${i}.py`));
  const selection=await collectProjectFolder(folder("large",entries),options);
  assert.equal(selection.files.length,1000);
  assert.equal(selection.limited,true);
});

function workbench(picker, directorySupport=true) {
  const elements=new Map();
  function element(id) {
    if(!elements.has(id))elements.set(id,{id,textContent:"",value:"",disabled:false,hidden:false,
      dataset:{},classList:{toggle(){}},listeners:{},children:[],
      addEventListener(type,callback){this.listeners[type]=callback;},
      setAttribute(name,value){this[name]=value;},
      replaceChildren(){this.children=[];},append(...children){this.children.push(...children);},
      click(){this.clicked=true;}});
    return elements.get(id);
  }
  element("reader-policy").textContent=JSON.stringify({excluded_folders:[".venv"],sensitive_names:[],
    text_names:["readme.md"],text_suffixes:[".py",".md"],manifests:[]});
  if(directorySupport)element("folder-input").webkitdirectory=true;
  const requests=[];
  const context=vm.createContext({TextDecoder,window:{showDirectoryPicker:picker},
    document:{getElementById:element,createElement:()=>element(Symbol()),
      createTextNode:text=>text,querySelectorAll:()=>[]},
    fetch:async(...args)=>{requests.push(args);throw Error("Folder selection must not upload");}});
  for(const name of ["project-folder.js","workbench.js"])
    vm.runInContext(fs.readFileSync(path.join(ROOT,"static",name),"utf8"),context);
  return {element,context,requests,open:()=>element("folder-button").listeners.click()};
}

test("the primary button requests read-only folder access and prepares code without uploading",async()=>{
  let pickerOptions;
  const ui=workbench(async options=>{pickerOptions=options;return folder("DevChallenge",[file("server.py")]);});
  await ui.open();
  assert.equal(pickerOptions.mode,"read");
  assert.equal(ui.element("project-name").textContent,"DevChallenge");
  assert.equal(ui.element("selection-details").open,true);
  assert.equal(ui.element("preview-button").disabled,false);
  assert.equal(ui.element("analyze-button").disabled,true);
  assert.equal(ui.requests.length,0);
});

test("cancelling the picker preserves the existing project and analysis",async()=>{
  const ui=workbench(async()=>{throw Object.assign(Error("Cancelled"),{name:"AbortError"});});
  ui.element("project-name").textContent="Existing project";
  ui.element("report-content").textContent="Existing analysis";
  await ui.open();
  assert.equal(ui.element("project-name").textContent,"Existing project");
  assert.equal(ui.element("report-content").textContent,"Existing analysis");
  assert.equal(ui.requests.length,0);
});

test("the fallback only opens a directory-capable input",async()=>{
  const supported=workbench(undefined);
  await supported.open();
  assert.equal(supported.element("folder-input").clicked,true);
  const unsupported=workbench(undefined,false);
  await unsupported.open();
  assert.notEqual(unsupported.element("folder-input").clicked,true);
  assert.match(unsupported.element("activity").textContent,/cannot select a whole folder/);
});

test("the folder fallback rejects ordinary file selection without replacing the existing review",async()=>{
  const ui=workbench(undefined);
  ui.element("project-name").textContent="Existing project";
  ui.element("report-content").textContent="Existing analysis";
  await ui.element("folder-input").listeners.change({target:{files:[{name:"app.py",webkitRelativePath:""}]}});
  assert.equal(ui.element("project-name").textContent,"Existing project");
  assert.equal(ui.element("report-content").textContent,"Existing analysis");
  assert.match(ui.element("activity").textContent,/individual files, not a project folder/);
});
