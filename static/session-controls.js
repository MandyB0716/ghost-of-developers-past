"use strict";
(() => {
  let channel=null;
  try {
    if(typeof BroadcastChannel!=="undefined")channel=new BroadcastChannel("revival-session");
  } catch { /* Clearing this tab still works when cross-tab messaging is unavailable. */ }

  function returnToStart() {
    if(typeof stopNarration==="function")stopNarration();
    // A fresh document releases selected text, answers, source previews and audio.
    window.location.replace("/?cleared=1");
  }
  if(channel)channel.onmessage=event=>{
    if(event.data==="cleared")returnToStart();
  };
  function confirmation(show) {
    byId("clear-session").hidden=show;
    byId("clear-session-confirmation").hidden=!show;
    byId(show?"clear-session-cancel":"clear-session").focus();
  }
  byId("clear-session").addEventListener("click",()=>{
    if(busy)return;
    confirmation(true);
  });
  byId("clear-session-cancel").addEventListener("click",()=>{
    if(!busy)confirmation(false);
  });
  byId("clear-session-confirm").addEventListener("click",()=>{
    if(busy)return;
    return operation(async()=>{
      // Do not report success or discard the page if the server rejects the clear.
      await requestJSON("/api/session/clear",{});
      try { channel?.postMessage("cleared"); } catch { /* Server cleanup already succeeded. */ }
      returnToStart();
    });
  });
})();
