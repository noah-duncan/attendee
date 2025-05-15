const _getUserMedia = navigator.mediaDevices.getUserMedia;



class BotOutputManager {
    constructor() {
        
        // For outputting video
        this.botOutputVideoElement = null;
        this.videoSoundSource = null;
        this.botOutputVideoElementCaptureStream = null;

        // For outputting image
        this.botOutputCanvasElement = null;
        this.botOutputCanvasElementCaptureStream = null;
        this.lastImageBytes = null;
        
        // For outputting audio
        this.audioContextForBotOutput = null;
        this.gainNode = null;
        this.destination = null;
        this.botOutputAudioTrack = null;

        this.specialStream = null;
        this.specialStreamAudioElement = null;
        this.specialStreamSource = null;
        this.specialStreamProcessor = null;
        this.specialStreamAudioContext = null;
    }

    connectVideoSourceToAudioContext() {
        if (this.botOutputVideoElement && this.audioContextForBotOutput && !this.videoSoundSource) {
            this.videoSoundSource = this.audioContextForBotOutput.createMediaElementSource(this.botOutputVideoElement);
            this.videoSoundSource.connect(this.gainNode);
        }
    }

    playSpecialStream(stream) {
        this.specialStream = stream;
        
        // Initialize audio context if needed
        this.initializeBotOutputAudioTrack();
        
        // Remove previous audio element if it exists
        if (this.specialStreamAudioElement) {
            this.specialStreamAudioElement.pause();
            if (this.specialStreamSource) {
                this.specialStreamSource.disconnect();
                this.specialStreamSource = null;
            }
            this.specialStreamAudioElement.remove();
        }
        
        // Create audio element for the stream
        this.specialStreamAudioElement = document.createElement('audio');
        this.specialStreamAudioElement.style.display = 'none';
        this.specialStreamAudioElement.srcObject = stream;
        this.specialStreamAudioElement.autoplay = true;
        document.body.appendChild(this.specialStreamAudioElement);
        
        // Use a more modern approach with MediaRecorder
        const audioTrack = stream.getAudioTracks()[0];
        if (audioTrack) {
            // Create a new MediaStream with just the audio track
            const audioStream = new MediaStream([audioTrack]);
            
            // Connect the audio stream directly to our output
            if (this.audioContextForBotOutput) {
                const streamSource = this.audioContextForBotOutput.createMediaStreamSource(audioStream);
                streamSource.connect(this.gainNode);
                
                // Store reference for cleanup
                this.specialStreamSource = streamSource;
            }
            
            console.log("Audio track connected to output");
        } else {
            console.warn("No audio track found in the stream");
        }
        
    }

    playVideo(videoUrl) {
        // If camera or mic are on, turn them off
        turnOffMicAndCamera();

        this.addBotOutputVideoElement(videoUrl);

        // Add event listener to wait until the video starts playing
        this.botOutputVideoElement.addEventListener('playing', () => {
            console.log("Video has started playing, turning on mic and camera");

            this.botOutputVideoElementCaptureStream = this.botOutputVideoElement.captureStream();

            turnOnMicAndCamera();
        }, { once: true });
    }

    isVideoPlaying() {
        return !!this.botOutputVideoElement;
    }

    addBotOutputVideoElement(url) {
        // Disconnect previous video source if it exists
        if (this.videoSoundSource) {
            this.videoSoundSource.disconnect();
            this.videoSoundSource = null;
        }
    
        // Remove any existing video element
        if (this.botOutputVideoElement) {
            this.botOutputVideoElement.remove();
        }
    
        // Create new video element
        this.botOutputVideoElement = document.createElement('video');
        this.botOutputVideoElement.style.display = 'none';
        // If url is a string then do it this way
        if (typeof url === 'string') {
            this.botOutputVideoElement.src = url;
        }
        // If url is a stream then do it this way
        else {
            this.botOutputVideoElement.srcObject = url;
        }
        //this.botOutputVideoElement.crossOrigin = 'anonymous';
        this.botOutputVideoElement.loop = false;
        this.botOutputVideoElement.autoplay = true;
        this.botOutputVideoElement.muted = false;
        // Clean up when video ends
        this.botOutputVideoElement.addEventListener('ended', () => {
            turnOffMicAndCamera();
            if (this.videoSoundSource) {
                this.videoSoundSource.disconnect();
                this.videoSoundSource = null;
            }
            this.botOutputVideoElement.remove();
            this.botOutputVideoElement = null;
            this.botOutputVideoElementCaptureStream = null;

            // If we were displaying an image, turn the camera back on
            if (this.botOutputCanvasElementCaptureStream) {
                this.botOutputCanvasElementCaptureStream = null;
                // Resend last image in 1 second
                if (this.lastImageBytes) {
                    setTimeout(() => {
                        this.displayImage(this.lastImageBytes);
                    }, 1000);
                }
            }
        });
    
        document.body.appendChild(this.botOutputVideoElement);
    }

    displayImage(imageBytes) {
        try {
            // Wait for the image to be loaded onto the canvas
            return this.writeImageToBotOutputCanvas(imageBytes)
                .then(async () => {
                // If the stream is already broadcasting, don't do anything
                if (this.botOutputCanvasElementCaptureStream)
                {
                    console.log("Stream already broadcasting, skipping");
                    return;
                }

                // Now that the image is loaded, capture the stream and turn on camera
                this.lastImageBytes = imageBytes;
                this.botOutputCanvasElementCaptureStream = this.botOutputCanvasElement.captureStream(1);
                await turnOnCamera();
            })
            .catch(error => {
                console.error('Error in botOutputManager.displayImage:', error);
            });
        } catch (error) {
            console.error('Error in botOutputManager.displayImage:', error);
        }
    }

    initializeBotOutputAudioTrack() {
        if (this.botOutputAudioTrack) {
            return;
        }

        // Create AudioContext and nodes
        this.audioContextForBotOutput = new AudioContext();
        this.gainNode = this.audioContextForBotOutput.createGain();
        this.destination = this.audioContextForBotOutput.createMediaStreamDestination();

        // Set initial gain
        this.gainNode.gain.value = 1.0;

        // Connect gain node to both destinations
        this.gainNode.connect(this.destination);
        //this.gainNode.connect(this.audioContextForBotOutput.destination);  // For local monitoring

        this.botOutputAudioTrack = this.destination.stream.getAudioTracks()[0];
        
        // Initialize audio queue for continuous playback
        this.audioQueue = [];
        this.nextPlayTime = 0;
        this.isPlaying = false;
        this.sampleRate = 48000; // Default sample rate
        this.numChannels = 1;    // Default channels
        this.turnOffMicTimeout = null;
    }

    playPCMAudio(pcmData, sampleRate = 48000, numChannels = 1) {
        //turnOnMic();

        // Make sure audio context is initialized
        this.initializeBotOutputAudioTrack();
        
        // Update properties if they've changed
        if (this.sampleRate !== sampleRate || this.numChannels !== numChannels) {
            this.sampleRate = sampleRate;
            this.numChannels = numChannels;
        }
        
        // Convert Int16 PCM data to Float32 with proper scaling
        let audioData;
        if (pcmData instanceof Float32Array) {
            audioData = pcmData;
        } else {
            // Create a Float32Array of the same length
            audioData = new Float32Array(pcmData.length);
            // Scale Int16 values (-32768 to 32767) to Float32 range (-1.0 to 1.0)
            for (let i = 0; i < pcmData.length; i++) {
                // Division by 32768.0 scales the range correctly
                audioData[i] = pcmData[i] / 32768.0;
            }
        }
        
        // Add to queue with timing information
        const chunk = {
            data: audioData,
            duration: audioData.length / (numChannels * sampleRate)
        };
        
        this.audioQueue.push(chunk);
        
        // Start playing if not already
        if (!this.isPlaying) {
            this.processAudioQueue();
        }
    }
    
    processAudioQueue() {
        if (this.audioQueue.length === 0) {
            this.isPlaying = false;

            if (this.turnOffMicTimeout) {
                clearTimeout(this.turnOffMicTimeout);
                this.turnOffMicTimeout = null;
            }
            
            // Delay turning off the mic by 2 second and check if queue is still empty
            this.turnOffMicTimeout = setTimeout(() => {
                // Only turn off mic if the queue is still empty
                if (this.audioQueue.length === 0)
                    turnOffMic();
            }, 2000);
            
            return;
        }
        
        this.isPlaying = true;
        
        // Get current time and next play time
        const currentTime = this.audioContextForBotOutput.currentTime;
        this.nextPlayTime = Math.max(currentTime, this.nextPlayTime);
        
        // Get next chunk
        const chunk = this.audioQueue.shift();
        
        // Create buffer for this chunk
        const audioBuffer = this.audioContextForBotOutput.createBuffer(
            this.numChannels,
            chunk.data.length / this.numChannels,
            this.sampleRate
        );
        
        // Fill the buffer
        if (this.numChannels === 1) {
            const channelData = audioBuffer.getChannelData(0);
            channelData.set(chunk.data);
        } else {
            for (let channel = 0; channel < this.numChannels; channel++) {
                const channelData = audioBuffer.getChannelData(channel);
                for (let i = 0; i < chunk.data.length / this.numChannels; i++) {
                    channelData[i] = chunk.data[i * this.numChannels + channel];
                }
            }
        }
        
        // Create source and schedule it
        const source = this.audioContextForBotOutput.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(this.gainNode);
        
        // Schedule precisely
        source.start(this.nextPlayTime);
        this.nextPlayTime += chunk.duration;
        
        // Schedule the next chunk processing
        const timeUntilNextProcess = (this.nextPlayTime - currentTime) * 1000 * 0.8;
        setTimeout(() => this.processAudioQueue(), Math.max(0, timeUntilNextProcess));
    }
}

const botOutputManager = new BotOutputManager();
window.botOutputManager = botOutputManager;

navigator.mediaDevices.getUserMedia = function(constraints) {
    return _getUserMedia.call(navigator.mediaDevices, constraints)
      .then(originalStream => {
        console.log("Intercepted getUserMedia:", constraints);
  
        // Stop any original tracks so we don't actually capture real mic/cam
        originalStream.getTracks().forEach(t => t.stop());
  
        // Create a new MediaStream to return
        const newStream = new MediaStream();
        

        // Audio sending not supported yet
        
        // If audio is requested, add our fake audio track
        if (constraints.audio) {  // Only create once
            botOutputManager.initializeBotOutputAudioTrack();
            newStream.addTrack(botOutputManager.botOutputAudioTrack);
        } 
  
        return newStream;
      })
      .catch(err => {
        console.error("Error in custom getUserMedia override:", err);
        throw err;
      });
  };


  // Function to look for and click the orb-animation button
function clickOrbAnimationButton() {
    const mayaButton = document.querySelector('div[aria-label="Maya"]');
    if (mayaButton) {
      console.log('Found Maya button, clicking it');
      mayaButton.click();
    }
  }
  
  // Set up interval to check for the button every 5 seconds
  setTimeout(clickOrbAnimationButton, 5000);

  // Generate fake PCM audio data (sine wave)
function generateFakePCMData() {
    const duration = 3; // 3 seconds of audio
    const sampleRate = 48000;
    const frequency = 440; // A4 note
    const numSamples = duration * sampleRate;
    
    // Create an Int16Array for PCM data
    const pcmData = new Int16Array(numSamples);
    
    // Generate a simple sine wave
    for (let i = 0; i < numSamples; i++) {
      // Calculate sine wave value (-1 to 1)
      const sineValue = Math.sin(2 * Math.PI * frequency * i / sampleRate);
      // Scale to Int16 range and add to array
      pcmData[i] = Math.floor(sineValue * 32767);
    }
    
    console.log("Generated fake PCM audio data");
    return pcmData;
  }
  
  // Play fake audio data after 10 seconds
  //setInterval(() => {
    //const bigstring = "xxx";
   // console.log("ASDSD");
  //  playBase64MP3(bigstring);
 // }, 10000);

// Function to play a base64 encoded MP3 file by converting it to PCM
function playBase64MP3(base64Mp3) {
  // Decode base64 to binary
  const binaryString = atob(base64Mp3);
  const len = binaryString.length;
  const bytes = new Uint8Array(len);
  
  // Convert binary string to bytes
  for (let i = 0; i < len; i++) {
    bytes[i] = binaryString.charCodeAt(i);
  }
  
  // Create an audio context for decoding
  const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  
  // Decode the MP3 data to PCM
  audioCtx.decodeAudioData(bytes.buffer)
    .then(audioBuffer => {
      // Get PCM data from the decoded audio buffer
      const numChannels = audioBuffer.numberOfChannels;
      const sampleRate = audioBuffer.sampleRate;
      const length = audioBuffer.length;
      
      // Extract PCM data from the first channel (or mix channels if needed)
      const pcmData = new Float32Array(length);
      
      // If mono, just copy the data
      if (numChannels === 1) {
        pcmData.set(audioBuffer.getChannelData(0));
      } 
      // If stereo or multichannel, mix down to mono
      else {
        const channels = [];
        for (let i = 0; i < numChannels; i++) {
          channels.push(audioBuffer.getChannelData(i));
        }
        
        for (let i = 0; i < length; i++) {
          let sum = 0;
          for (let c = 0; c < numChannels; c++) {
            sum += channels[c][i];
          }
          pcmData[i] = sum / numChannels;
        }
      }
      
  
      botOutputManager.playPCMAudio(pcmData, sampleRate, 1);
    })
    .catch(error => {
      console.error('Error decoding MP3:', error);
    });
}

class WebRTCStreamReceiver {
    constructor(options = {}) {
        this.options = {
            wsUrl: 'ws://localhost:8796',
            ...options
        };
        
        // WebRTC variables
        this.peerConnection = null;
        this.ws = null;
        this.currentSenderId = null;
        this.clientId = 'receiver-' + Math.floor(Math.random() * 1000);
        this.remoteStream = null;
        
        // Track handling
        this.hasAudioTrack = false;
        this.hasVideoTrack = false;
        this.audioTrack = null;
        this.videoTrack = null;
        this.combinedStream = new MediaStream();
        
        // Callbacks
        this.onStreamCallback = options.onStream;
        this.onStatusChangeCallback = null;
        this.onLogCallback = null;
    }
    
    log(message) {
        console.log('[WebRTCStreamReceiver]', message);
        if (this.onLogCallback) {
            this.onLogCallback(message);
        }
    }
    
    updateStatus(status, type) {
        this.log(status);
        if (this.onStatusChangeCallback) {
            this.onStatusChangeCallback(status, type);
        }
    }
    
    connect() {
        this.log('Connecting to signaling server at ' + this.options.wsUrl);
        this.ws = new WebSocket(this.options.wsUrl);
        
        this.ws.onopen = () => {
            this.updateStatus('Connected to signaling server', 'connected');
            
            // Register with the signaling server
            this.ws.send(JSON.stringify({
                type: 'register',
                clientId: this.clientId
            }));
            
            // Initialize WebRTC
            this.initWebRTC();
            
            this.log('Registered with signaling server as: ' + this.clientId);
        };
        
        this.ws.onclose = () => {
            this.updateStatus('Disconnected from signaling server', 'error');
            this.log('WebSocket connection closed');
        };
        
        this.ws.onerror = (error) => {
            this.updateStatus('Error connecting to signaling server', 'error');
            this.log('WebSocket error');
        };
        
        this.ws.onmessage = async (event) => {
            const data = JSON.parse(event.data);
            this.log('Received message: ' + data.type);
            
            if (data.type === 'offer') {
                this.currentSenderId = data.senderId;
                this.updateStatus('Received offer from sender: ' + this.currentSenderId, 'connecting');
                await this.handleOffer(data.offer);
            } else if (data.type === 'ice-candidate') {
                this.log('Received ICE candidate from: ' + data.senderId);
                await this.handleIceCandidate(data.candidate);
            }
        };
    }
    
    initWebRTC() {
        this.log('Initializing WebRTC connection');
        
        // Create new RTCPeerConnection
        this.peerConnection = new RTCPeerConnection({
            iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
        });
        
        // Set up event handlers
        this.peerConnection.ontrack = (event) => {
            const track = event.track;
            this.log('🎉 RECEIVED MEDIA TRACK: ' + track.kind);
            
            // Store the incoming track based on its kind
            if (track.kind === 'audio') {
                this.hasAudioTrack = true;
                this.audioTrack = track;
                this.log('Received audio track');
            } else if (track.kind === 'video') {
                this.hasVideoTrack = true;
                this.videoTrack = track;
                this.log('Received video track');
            }
            
            // Create or update the combined stream
            this.updateCombinedStream();
            
            // Update status
            this.updateStatus(`Received ${track.kind} track. Have audio: ${this.hasAudioTrack}, video: ${this.hasVideoTrack}`, 'connected');
        };
        
        this.peerConnection.onicecandidate = (event) => {
            if (event.candidate && this.currentSenderId) {
                this.log('Sending ICE candidate to sender: ' + this.currentSenderId);
                this.ws.send(JSON.stringify({
                    type: 'ice-candidate',
                    targetId: this.currentSenderId,
                    candidate: event.candidate
                }));
            }
        };
        
        this.peerConnection.oniceconnectionstatechange = () => {
            this.log('ICE connection state changed to: ' + this.peerConnection.iceConnectionState);
            this.updateStatus(`ICE connection: ${this.peerConnection.iceConnectionState}`, 
                            this.peerConnection.iceConnectionState === 'connected' ? 'connected' : 'connecting');
        };
        
        this.peerConnection.onicegatheringstatechange = () => {
            this.log('ICE gathering state: ' + this.peerConnection.iceGatheringState);
        };
        
        this.peerConnection.onsignalingstatechange = () => {
            this.log('Signaling state: ' + this.peerConnection.signalingState);
        };
        
        this.peerConnection.onconnectionstatechange = () => {
            this.log('Connection state: ' + this.peerConnection.connectionState);
        };
    }
    
    updateCombinedStream() {
        // Remove any existing tracks from the combined stream
        this.combinedStream.getTracks().forEach(track => {
            this.combinedStream.removeTrack(track);
        });
        
        // Add the tracks we have
        if (this.audioTrack) {
            this.combinedStream.addTrack(this.audioTrack);
        }
        
        // Call the callback when we have at least one track
        // Ideally we'd wait for both, but we should handle cases where only one type is sent
        if ((this.hasAudioTrack) && this.onStreamCallback) {
            this.remoteStream = this.combinedStream;
            this.onStreamCallback(this.combinedStream);
        }
    }
    
    async handleOffer(offer) {
        try {
            this.log('Setting remote description (offer)');
            await this.peerConnection.setRemoteDescription(new RTCSessionDescription(offer));
            
            this.log('Creating answer');
            const answer = await this.peerConnection.createAnswer();
            
            this.log('Setting local description (answer)');
            await this.peerConnection.setLocalDescription(answer);
            
            this.log('Sending answer to sender: ' + this.currentSenderId);
            this.ws.send(JSON.stringify({
                type: 'answer',
                targetId: this.currentSenderId,
                answer: this.peerConnection.localDescription
            }));
            
            this.updateStatus('Sent answer to sender', 'connecting');
        } catch (error) {
            this.log('ERROR handling offer: ' + error.message);
            this.updateStatus('Error handling offer', 'error');
        }
    }
    
    async handleIceCandidate(candidate) {
        try {
            await this.peerConnection.addIceCandidate(new RTCIceCandidate(candidate));
            this.log('Added ICE candidate successfully');
        } catch (error) {
            this.log('ERROR adding ICE candidate: ' + error.message);
        }
    }
    
    getStream() {
        return this.combinedStream;
    }
    
    onStream(callback) {
        this.onStreamCallback = callback;
        // If we already have a stream, call the callback immediately
        if (this.remoteStream && callback) {
            callback(this.remoteStream);
        }
    }
    
    onStatusChange(callback) {
        this.onStatusChangeCallback = callback;
    }
    
    onLog(callback) {
        this.onLogCallback = callback;
    }
    
    disconnect() {
        if (this.peerConnection) {
            this.peerConnection.close();
            this.peerConnection = null;
        }
        
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
        
        this.remoteStream = null;
        this.hasAudioTrack = false;
        this.hasVideoTrack = false;
        this.audioTrack = null;
        this.videoTrack = null;
        this.combinedStream = new MediaStream();
        this.log('Disconnected WebRTC and signaling connections');
    }
}


const webRTCStreamReceiver = new WebRTCStreamReceiver({
    onStream: (stream) => {
        botOutputManager.playSpecialStream(stream);
        // create an audio element and play the stream
    }
});
window.webRTCStreamReceiver = webRTCStreamReceiver;

setTimeout(() => {
    webRTCStreamReceiver.connect();
}, 10000);