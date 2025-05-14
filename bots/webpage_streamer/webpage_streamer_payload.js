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

  captureScreenWithAudio();