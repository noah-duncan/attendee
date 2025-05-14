// Get the extension ID from chrome storage instead of using a message listener
const extensionId = chrome.runtime.id;
console.log("Extension ID:", extensionId);

// Post message every second for 10 seconds total
let count = 0;
const intervalId = setInterval(() => {
  window.postMessage({type:'EXT_ID', id: extensionId}, '*');
  count++;
  
  if (count >= 20) {
    clearInterval(intervalId);
  }
}, 500);

// Listen for messages from the webpage
window.addEventListener('message', function(event) {
  // Make sure message is from our webpage
  if (event.data.type === 'EXTENSION_COMMAND') {
    console.log('Content script received command:', event.data.command);
    

    (async () => {
        // 1. Ask the service‑worker for a streamId
        const { streamId } = await chrome.runtime.sendMessage('NEED_STREAM_ID');
        console.log('Stream ID:', streamId);
      
        // 2. Turn the ID into a full MediaStream (audio + video)
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: { mandatory: { chromeMediaSource: 'tab', chromeMediaSourceId: streamId } },
          video: { mandatory: { chromeMediaSource: 'tab', chromeMediaSourceId: streamId } }
        });
      
        // 3. Do whatever you need (pipe to WebRTC, analyse frames, etc.)
        window.postMessage({ type: 'CAPTURE_READY' });     // example hand‑off
      })();

  }
});