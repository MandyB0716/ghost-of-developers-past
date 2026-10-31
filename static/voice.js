"use strict";
let narrationURL=null, microphoneRecorder=null, microphoneStream=null, recordingTimeout=null;
function stopNarration() {
  const audio=byId("narration");if(!audio)return;
  audio.pause();audio.removeAttribute("src");audio.load();audio.hidden=true;
  if(narrationURL){URL.revokeObjectURL(narrationURL);narrationURL=null;}
  byId("stop-audio").disabled=true;
}
byId("read-button").addEventListener("click",()=>operation(async()=>{
  stopNarration();activity("ElevenLabs is preparing narration for this analysis…");
  const response=await fetch("/api/read-aloud",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({version:currentVersion})});
  if(!response.ok){const result=await response.json();throw new Error(result.error || "Narration did not complete.");}
  narrationURL=URL.createObjectURL(await response.blob());const audio=byId("narration");
  audio.src=narrationURL;audio.hidden=false;byId("stop-audio").disabled=false;
  try{await audio.play();activity("Reading the analysis aloud. Use Stop audio to stop playback.");}
  catch{activity("Narration is ready. Press Play in the audio controls.");}
}));
byId("stop-audio").addEventListener("click",()=>{
  byId("narration").pause();byId("narration").currentTime=0;activity("Audio stopped. You can replay it using the audio controls.");
});
function releaseMicrophone() {
  clearTimeout(recordingTimeout);recordingTimeout=null;
  microphoneStream?.getTracks().forEach(track=>track.stop());microphoneStream=null;
  byId("record-button").dataset.recording="false";byId("record-button").textContent="Speak your goal";
}
byId("record-button").addEventListener("click",async()=>{
  if(microphoneRecorder?.state==="recording") {microphoneRecorder.stop();return;}
  if(busy)return;
  busy=true;controls();stopNarration();let chunks=[],failed=false;
  try{
    if(!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder)throw new Error("Microphone recording is unavailable. You can type your goal instead.");
    microphoneStream=await navigator.mediaDevices.getUserMedia({audio:true});
    const type=["audio/webm;codecs=opus","audio/webm","audio/mp4"].find(value=>MediaRecorder.isTypeSupported(value));
    microphoneRecorder=new MediaRecorder(microphoneStream,type?{mimeType:type}:{});
    microphoneRecorder.ondataavailable=event=>{if(event.data.size)chunks.push(event.data);};
    microphoneRecorder.onerror=()=>{failed=true;releaseMicrophone();busy=false;controls();activity("Recording stopped unexpectedly. You can try again or type your goal.",true);};
    microphoneRecorder.onstop=async()=>{
      const contentType=microphoneRecorder.mimeType || type || "audio/webm";
      releaseMicrophone();microphoneRecorder=null;controls();if(failed)return;
      try{
        const blob=new Blob(chunks,{type:contentType});if(!blob.size)throw new Error("The recording was empty. Please try again.");
        activity("Transcribing your goal with ElevenLabs…");
        const data=new FormData();data.append("file",blob,contentType.includes("mp4")?"goal.m4a":"goal.webm");
        const response=await fetch("/api/transcribe",{method:"POST",body:data});const result=await response.json();
        if(!response.ok)throw new Error(result.error || "Transcription did not complete.");
        byId("restart-goal").value=result.text;activity("Your spoken goal is ready. Review or edit it before clicking Analyze.");
      }catch(error){activity(error.message,true);}finally{busy=false;controls();}
    };
    microphoneRecorder.start();byId("record-button").dataset.recording="true";
    byId("record-button").textContent="Stop and transcribe";controls();
    activity("Recording your goal. Click Stop and transcribe when finished; recordings are limited to 90 seconds.");
    recordingTimeout=setTimeout(()=>{if(microphoneRecorder?.state==="recording")microphoneRecorder.stop();},90000);
  }catch(error){releaseMicrophone();microphoneRecorder=null;busy=false;controls();activity(error.message,true);}
});
window.addEventListener("pagehide",()=>{microphoneStream?.getTracks().forEach(track=>track.stop());});
