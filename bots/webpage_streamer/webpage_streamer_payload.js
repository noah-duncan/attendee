async function captureScreenWithAudio() {
    try {
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
      }, 25000);
      
      // To stop capture when needed
      const tracks = screenStream.getTracks();
      tracks.forEach(track => {
        // Add event listener to detect when user stops sharing
        track.addEventListener('ended', () => {
          console.log('User stopped sharing');
        });
      });
      
      return screenStream;
    } catch (error) {
      console.error('Error capturing screen:', error);
      return null;
    }
  }

  captureScreenWithAudio();