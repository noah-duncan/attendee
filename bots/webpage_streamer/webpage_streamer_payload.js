async function captureScreenWithAudio() {
    try {
      console.log("Starting screen capture with audio");
      // Request screen capture with audio, preferring the current tab
      const screenStream = await navigator.mediaDevices.getDisplayMedia({
        video: {
          displaySurface: 'browser',
          preferCurrentTab: true
        },
        audio: true // This requests audio from the captured tab
      });
      
      // If you also want microphone audio (separate from screen audio)
      // const micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      
      // Now you have access to the screen capture stream
      console.log('Screen capture successful:', screenStream);
      
      // You can use the stream with video elements or for recording
      const videoElement = document.createElement('video');
      videoElement.srcObject = screenStream;
      videoElement.autoplay = true;
      window.__videoElement = videoElement;

      console.log('videoElement:', videoElement);
      
      // Set up recording of the stream
      const mediaRecorder = new MediaRecorder(screenStream);
      const recordedChunks = [];
      
      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          recordedChunks.push(event.data);
        }
      };
      
      mediaRecorder.onstop = () => {
        // Create a blob from the recorded chunks
        const blob = new Blob(recordedChunks, { type: 'video/webm' });
        const url = URL.createObjectURL(blob);
        
        // Create download button
        const downloadButton = document.createElement('button');
        downloadButton.textContent = 'Download Recording';
        downloadButton.style.position = 'fixed';
        downloadButton.style.top = '20px';
        downloadButton.style.right = '20px';
        downloadButton.style.zIndex = '9999';
        downloadButton.style.padding = '10px';
        downloadButton.style.backgroundColor = '#4CAF50';
        downloadButton.style.color = 'white';
        downloadButton.style.border = 'none';
        downloadButton.style.borderRadius = '5px';
        downloadButton.style.cursor = 'pointer';
        
        downloadButton.onclick = () => {
          const a = document.createElement('a');
          a.href = url;
          a.download = 'screen-recording.webm';
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
        };
        
        document.body.appendChild(downloadButton);
      };
      
      // Start recording
      mediaRecorder.start();
      
      // Stop recording after 5 seconds
      setTimeout(() => {
        mediaRecorder.stop();
        
        // Stop all tracks
        screenStream.getTracks().forEach(track => track.stop());
        console.log('Recording stopped after 5 seconds');
      }, 10000);
      
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
      const ws = new WebSocket('ws://localhost:8765');
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

  captureScreenWithAudio();