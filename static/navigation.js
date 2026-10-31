"use strict";
(() => {
  const names=["project","plan","sources"], find=id=>document.getElementById(id);
  let active="project", peek=false;
  const viewer=find("source-viewer");
  function arrange() {
    const beside=active==="plan" && peek;
    find("plan-layout").classList.toggle("has-source",beside);
    find("plan-source-host").hidden=!beside;
    find(beside?"plan-source-host":"full-source-host").append(viewer);
    find("close-source-preview").hidden=!beside;
  }
  function select(name, focus=false) {
    if(!names.includes(name))return;
    active=name;
    names.forEach(key=>{
      const chosen=key===name, tab=find("tab-"+key);
      tab.setAttribute("aria-selected",String(chosen));tab.tabIndex=chosen?0:-1;
      find("panel-"+key).hidden=!chosen;
    });
    arrange();
    if(focus)find("tab-"+name).focus();
  }
  names.forEach((name,index)=>{
    const tab=find("tab-"+name);
    tab.addEventListener("click",()=>select(name));
    tab.addEventListener("keydown",event=>{
      const next={ArrowRight:(index+1)%3,ArrowLeft:(index+2)%3,Home:0,End:2}[event.key];
      if(next!==undefined){event.preventDefault();select(names[next],true);}
    });
  });
  document.addEventListener("click",event=>{
    if(active==="plan" && event.target.closest("a.citation")){peek=true;arrange();}
  },true);
  find("close-source-preview").addEventListener("click",()=>{
    peek=false;arrange();find("tab-plan").focus();
  });
  find("back-to-project").addEventListener("click",()=>select("project",true));
  window.revivalNavigation={select,reset(){peek=false;arrange();}};
  select("project");
})();
