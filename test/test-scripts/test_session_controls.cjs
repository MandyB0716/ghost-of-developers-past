const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function setup({fail=false, busy=false, messaging=true}={}) {
  let channel;
  const handlers={}, elements=new Map();
  const calls=[], navigations=[], notifications=[], errors=[];
  let stopped=0;
  const context=vm.createContext({busy,
    byId:id=>{if(!elements.has(id))elements.set(id,{hidden:id==="clear-session-confirmation",focus(){},addEventListener(_name,handler){handlers[id]=handler;}});return elements.get(id);},
    window:{location:{replace:url=>navigations.push(url)}},
    stopNarration:()=>stopped++,
    requestJSON:async(...args)=>{calls.push(args);if(fail)throw new Error("Connection lost.");return {cleared:true};},
    operation:async action=>{try{await action();}catch(error){errors.push(error.message);}},
    ...(messaging?{BroadcastChannel:class {constructor(){channel=this;}postMessage(value){notifications.push(value);}}}:{}),
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname,"../../static/session-controls.js"),"utf8"),context);
  return {click:()=>handlers["clear-session"](),cancel:()=>handlers["clear-session-cancel"](),confirm:()=>handlers["clear-session-confirm"](),elements,calls,navigations,notifications,errors,
    get stopped(){return stopped;},receive:data=>channel.onmessage({data})};
}

test("cancelling clear or using it while busy keeps the current workspace",async()=>{
  for(const options of [{},{busy:true}]) {
    const ui=setup(options);await ui.click();await ui.cancel();
    assert.equal(ui.calls.length,0);assert.equal(ui.navigations.length,0);assert.equal(ui.stopped,0);
    if(!options.busy)assert.equal(ui.elements.get("clear-session-confirmation").hidden,true);
  }
});
test("failed server cleanup preserves the visible plan and reports the error",async()=>{
  const ui=setup({fail:true});await ui.click();await ui.confirm();
  assert.equal(ui.navigations.length,0);assert.equal(ui.stopped,0);
  assert.deepEqual(ui.errors,["Connection lost."]);
});
test("successful cleanup stops narration, informs other tabs and starts fresh",async()=>{
  const ui=setup();await ui.click();assert.equal(ui.calls.length,0);await ui.confirm();
  assert.equal(ui.calls[0][0],"/api/session/clear");assert.equal(ui.stopped,1);
  assert.deepEqual(ui.notifications,["cleared"]);assert.deepEqual(ui.navigations,["/?cleared=1"]);
});
test("another workbench tab clears its visible copy without another server call",()=>{
  const ui=setup();ui.receive("ignored");assert.equal(ui.navigations.length,0);
  ui.receive("cleared");assert.equal(ui.calls.length,0);assert.equal(ui.stopped,1);
  assert.deepEqual(ui.navigations,["/?cleared=1"]);
});
test("clear still works when cross-tab messaging is unavailable",async()=>{
  const ui=setup({messaging:false});await ui.click();await ui.confirm();
  assert.deepEqual(ui.navigations,["/?cleared=1"]);
});
