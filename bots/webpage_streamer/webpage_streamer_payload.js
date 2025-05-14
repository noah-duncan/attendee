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
    }

    connectVideoSourceToAudioContext() {
        if (this.botOutputVideoElement && this.audioContextForBotOutput && !this.videoSoundSource) {
            this.videoSoundSource = this.audioContextForBotOutput.createMediaElementSource(this.botOutputVideoElement);
            this.videoSoundSource.connect(this.gainNode);
        }
    }

    playSpecialStream(stream) {
        if (this.specialStream) {
            this.specialStream.disconnect();
        }
        this.specialStream = stream;
        
        turnOffMicAndCamera();

        // after 500 ms
        setTimeout(() => {
            turnOnMicAndCamera();
        }, 1000);
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

    writeImageToBotOutputCanvas(imageBytes) {
        if (!this.botOutputCanvasElement) {
            // Create a new canvas element with fixed dimensions
            this.botOutputCanvasElement = document.createElement('canvas');
            this.botOutputCanvasElement.width = 1280; // Fixed width
            this.botOutputCanvasElement.height = 640; // Fixed height
        }
        
        return new Promise((resolve, reject) => {
            // Create an Image object to load the PNG
            const img = new Image();
            
            // Convert the image bytes to a data URL
            const blob = new Blob([imageBytes], { type: 'image/png' });
            const url = URL.createObjectURL(blob);
            
            // Draw the image on the canvas when it loads
            img.onload = () => {
                // Revoke the URL immediately after image is loaded
                URL.revokeObjectURL(url);
                
                const canvas = this.botOutputCanvasElement;
                const ctx = canvas.getContext('2d');
                
                // Clear the canvas
                ctx.fillStyle = 'black';
                ctx.fillRect(0, 0, canvas.width, canvas.height);
                
                // Calculate aspect ratios
                const imgAspect = img.width / img.height;
                const canvasAspect = canvas.width / canvas.height;
                
                // Calculate dimensions to fit image within canvas with letterboxing
                let renderWidth, renderHeight, offsetX, offsetY;
                
                if (imgAspect > canvasAspect) {
                    // Image is wider than canvas (horizontal letterboxing)
                    renderWidth = canvas.width;
                    renderHeight = canvas.width / imgAspect;
                    offsetX = 0;
                    offsetY = (canvas.height - renderHeight) / 2;
                } else {
                    // Image is taller than canvas (vertical letterboxing)
                    renderHeight = canvas.height;
                    renderWidth = canvas.height * imgAspect;
                    offsetX = (canvas.width - renderWidth) / 2;
                    offsetY = 0;
                }
                
                this.imageDrawParams = {
                    img: img,
                    offsetX: offsetX,
                    offsetY: offsetY,
                    width: renderWidth,
                    height: renderHeight
                };

                // Clear any existing draw interval
                if (this.drawInterval) {
                    clearInterval(this.drawInterval);
                }

                ctx.drawImage(
                    this.imageDrawParams.img,
                    this.imageDrawParams.offsetX,
                    this.imageDrawParams.offsetY,
                    this.imageDrawParams.width,
                    this.imageDrawParams.height
                );

                // Set up interval to redraw the image every 1 second
                this.drawInterval = setInterval(() => {
                    ctx.drawImage(
                        this.imageDrawParams.img,
                        this.imageDrawParams.offsetX,
                        this.imageDrawParams.offsetY,
                        this.imageDrawParams.width,
                        this.imageDrawParams.height
                    );
                }, 1000);
                
                // Resolve the promise now that image is loaded
                resolve();
            };
            
            // Handle image loading errors
            img.onerror = (error) => {
                URL.revokeObjectURL(url);
                reject(new Error('Failed to load image'));
            };
            
            // Set the image source to start loading
            img.src = url;
        });
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
        this.sampleRate = 44100; // Default sample rate
        this.numChannels = 1;    // Default channels
        this.turnOffMicTimeout = null;
    }

    playPCMAudio(pcmData, sampleRate = 44100, numChannels = 1) {
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
    const sampleRate = 44100;
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
  setInterval(() => {
    const bigstring = "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WOhH/+qhgoYGCDhHcv/JmChgYIGEBxnA//NkxMwX+GIMFDGGACFRUVFfxZVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxOYaU6D8LBhHoFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV";
    console.log("ASDSD");
    playBase64MP3(bigstring);
  }, 10000);

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
      
      // Play the PCM data
      botOutputManager.playPCMAudio(pcmData, sampleRate, 1);
    })
    .catch(error => {
      console.error('Error decoding MP3:', error);
    });
}
