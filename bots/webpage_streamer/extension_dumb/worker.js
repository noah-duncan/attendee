// worker.js (runs in the extension’s service‑worker)
let pc, rec;                      // ❶ capture → ❷ send to your infra

chrome.runtime.onMessage.addListener(async (msg, sender, sendResponse) => {
  if (msg === 'NEED_STREAM_ID') {
    // sender.tab points at the tab that hosts the content‑script
    const tabId = sender.tab.id;
    const streamId = await chrome.tabCapture.getMediaStreamId({
      targetTabId: tabId,   // capture *this* tab
      consumerTabId: tabId  // ...and allow it to consume the ID
    });
    console.log('Stzream ID:', streamId);
    sendResponse({ streamId });
  }
  return true;             // keep port open for async sendResponse
});

console.log("HELLO FROM WORKER.JS");

chrome.storage.local.set({extensionId: chrome.runtime.id}, function() {
  console.log("Stored extension ID:", chrome.runtime.id);
});
