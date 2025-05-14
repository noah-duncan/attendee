// Copyright 2023 Google LLC
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     https://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

async function captureScreenWithAudio(screenStream) {
    try {
      console.log("Starting screen capture with audio");
      // Request screen capture with audio, with explicit settings for tab audio
      /*
      const screenStream = await navigator.mediaDevices.getDisplayMedia({
        video: {
          displaySurface: 'browser',
          preferCurrentTab: true
        },
        audio: true
      });*/


      
      // If you also want microphone audio (separate from screen audio)
      // const micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      
      // Now you have access to the screen capture stream
      console.log('Screen capture successful:', screenStream);
      
      // You can use the stream with video elements or for recording
      /*
      const videoElement = document.createElement('video');
      videoElement.srcObject = screenStream;
      videoElement.autoplay = true;
      window.__videoElement = videoElement;*/

     // console.log('videoElement:', videoElement);
            
      // To stop capture when needed
      const tracks = screenStream.getTracks();
      tracks.forEach(track => {
        // Add event listener to detect when user stops sharing
        track.addEventListener('ended', () => {
          console.log('User stopped sharing');
        });
      });
      
      // Set up WebRTC with WebSocket signaling
      const peerConnection = new RTCPeerConnection({
        iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
      });
      
      // Add tracks to the connection
      screenStream.getTracks().forEach(track => {
        peerConnection.addTrack(track, screenStream);
        console.log(`Added track: ${track.kind}`);
      });
      
      // Connect to signaling server
      const ws = new WebSocket('ws://localhost:8795');
      const clientId = 'sender-' + Math.floor(Math.random() * 1000);
      let receiverId = null;
      
      ws.onopen = () => {
        console.log('Connected to signaling server');
        
        // Register with the signaling server
        ws.send(JSON.stringify({
          type: 'register',
          clientId: clientId
        }));
        
        // Handle ICE candidates
        peerConnection.onicecandidate = (event) => {
          if (event.candidate && receiverId) {
            console.log('Sending ICE candidate to receiver');
            ws.send(JSON.stringify({
              type: 'ice-candidate',
              targetId: receiverId,
              candidate: event.candidate
            }));
          }
        };
        
        peerConnection.oniceconnectionstatechange = () => {
          console.log(`ICE connection state: ${peerConnection.iceConnectionState}`);
        };
        
        console.log('Waiting for receiver to connect...');
      };
      
      ws.onmessage = async (event) => {
        const data = JSON.parse(event.data);
        console.log('Received message:', data.type);
        
        if (data.type === 'receiver-ready') {
          receiverId = data.receiverId;
          console.log('Receiver is ready, creating offer for:', receiverId);
          
          try {
            const offer = await peerConnection.createOffer();
            await peerConnection.setLocalDescription(offer);
            
            ws.send(JSON.stringify({
              type: 'offer',
              targetId: receiverId,
              offer: peerConnection.localDescription
            }));
            console.log('Offer sent to receiver');
          } catch (error) {
            console.error('Error creating offer:', error);
          }
        }
        else if (data.type === 'answer') {
          console.log('Received answer from receiver');
          try {
            await peerConnection.setRemoteDescription(new RTCSessionDescription(data.answer));
            console.log('Remote description set successfully');
          } catch (error) {
            console.error('Error setting remote description:', error);
          }
        } 
        else if (data.type === 'ice-candidate') {
          console.log('Received ICE candidate from receiver');
          try {
            await peerConnection.addIceCandidate(new RTCIceCandidate(data.candidate));
            console.log('Added ICE candidate successfully');
          } catch (error) {
            console.error('Error adding ICE candidate:', error);
          }
        }
      };
      
      return screenStream;
    } catch (error) {
      console.error('Error capturing screen:', error);
      return null;
    }
  }

chrome.runtime.onMessage.addListener(async (message) => {
    if (message.target === 'offscreen') {
      switch (message.type) {
        case 'start-recording':
          startRecording(message.data);
          break;
        case 'stop-recording':
          stopRecording();
          break;
        default:
          throw new Error('Unrecognized message:', message.type);
      }
    }
  });
  
  let recorder;
  let data = [];
  
  async function startRecording(streamId) {
    if (recorder?.state === 'recording') {
      throw new Error('Called startRecording while recording is in progress.');
    }

    console.log('Starting recording with stream ID:', streamId);
  
    const media = await navigator.mediaDevices.getUserMedia({
      audio: {
        mandatory: {
          chromeMediaSource: 'tab',
          chromeMediaSourceId: streamId
        }
      },
      video: {
        mandatory: {
          chromeMediaSource: 'tab',
          chromeMediaSourceId: streamId
        }
      }
    });

    captureScreenWithAudio(media);
    return;
  
    // Continue to play the captured audio to the user.
    const output = new AudioContext();
    const source = output.createMediaStreamSource(media);
    source.connect(output.destination);
  
    // Start recording.
    recorder = new MediaRecorder(media, { mimeType: 'video/webm' });
    recorder.ondataavailable = (event) => data.push(event.data);
    recorder.onstop = () => {
      const blob = new Blob(data, { type: 'video/webm' });
      window.open(URL.createObjectURL(blob), '_blank');
  
      // Clear state ready for next recording
      recorder = undefined;
      data = [];
    };
    recorder.start();
  
    // Record the current state in the URL. This provides a very low-bandwidth
    // way of communicating with the service worker (the service worker can check
    // the URL of the document and see the current recording state). We can't
    // store that directly in the service worker as it may be terminated while
    // recording is in progress. We could write it to storage but that slightly
    // increases the risk of things getting out of sync.
    window.location.hash = 'recording';
  }
  
  async function stopRecording() {
    recorder.stop();
  
    // Stopping the tracks makes sure the recording icon in the tab is removed.
    recorder.stream.getTracks().forEach((t) => t.stop());
  
    // Update current state in URL
    window.location.hash = '';
  
    // Note: In a real extension, you would want to write the recording to a more
    // permanent location (e.g IndexedDB) and then close the offscreen document,
    // to avoid keeping a document around unnecessarily. Here we avoid that to
    // make sure the browser keeps the Object URL we create (see above) and to
    // keep the sample fairly simple to follow.
  }