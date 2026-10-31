const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function viewer() {
  const scroll={scrollTop:400,scrollLeft:50};
  const cards=new Map(["F1","F2"].map(id=>[id,{hidden:false,closest:()=>scroll}]));
  const lines=new Map();
  for(const source of ["F1","F2"])for(let number=1;number<=2;number++) {
    const classes=new Set();
    lines.set(`source-${source}-L${number}`,{classes,
      classList:{add:value=>classes.add(value),remove:value=>classes.delete(value)},
      scrollIntoView(){this.scrolled=true;}});
  }
  const picker={value:"F1",addEventListener(){},get selectedOptions(){return [{textContent:this.value==="F1"?"app.py":"src/helper.py"}];}};
  const status={textContent:""};
  let click;
  const context=vm.createContext({document:{
    getElementById(id){if(id==="file-picker")return picker;if(id==="source-status")return status;
      return lines.get(id) || cards.get(id.replace(/^source-/,""));},
    querySelectorAll(selector){return selector===".source-file"?[...cards.values()]:[...lines.values()].filter(line=>line.classes.has("selected-line"));},
    addEventListener(name,handler){if(name==="click")click=handler;},
  },history:{replaceState(_state,_title,href){context.currentHash=href;}}});
  vm.runInContext(fs.readFileSync(path.join(__dirname,"../../static/review.js"),"utf8"),context);
  function follow(source, first, last) {
    const href=`#source-${source}`+(first?`-L${first}`:"");
    const link={dataset:{source,...(first?{first:String(first),last:String(last)}:{})},getAttribute:()=>href};
    let prevented=false;
    click({target:{closest:()=>link},preventDefault(){prevented=true;}});
    assert.equal(prevented,true);
  }
  return {follow,picker,status,scroll,cards,lines,context};
}

test("a whole-file link changes files and clears a previous line selection",()=>{
  const ui=viewer();
  ui.follow("F1",1,2);
  ui.follow("F2");
  assert.equal(ui.picker.value,"F2");
  assert.equal(ui.cards.get("F1").hidden,true);
  assert.equal(ui.cards.get("F2").hidden,false);
  assert.equal([...ui.lines.values()].some(line=>line.classes.has("selected-line")),false);
  assert.equal(ui.scroll.scrollTop,0);
  assert.equal(ui.scroll.scrollLeft,0);
  assert.match(ui.status.textContent,/Whole file \(no line range cited\)/);
  assert.equal(ui.context.currentHash,"#source-F2");
});

test("a line reference still highlights only its specified range",()=>{
  const ui=viewer();
  ui.follow("F2",2,2);
  assert.equal(ui.lines.get("source-F2-L1").classes.has("selected-line"),false);
  assert.equal(ui.lines.get("source-F2-L2").classes.has("selected-line"),true);
  assert.equal(ui.lines.get("source-F2-L2").scrolled,true);
  assert.equal(ui.status.textContent,"src/helper.py · Line 2");
});
