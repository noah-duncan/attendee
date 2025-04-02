class StyleManager {
    constructor() {
        this.videoTrackIdToSSRC = new Map();
        this.videoElementToCaptureCanvasElements = new Map();
        this.captureCanvasVisible = true; // Track visibility state
        this.mainElement = null;
        this.misMatchTracker = new Map();

        this.audioContext = null;
        this.audioTracks = [];
        this.silenceThreshold = 0.0;
        this.silenceCheckInterval = null;
        this.numFramesSynced = 0;
        this.renderState = "unsynced";
        this.renderStateUnsyncReason = "";
        this.trackToVideoElement = new Map();
    }

    addAudioTrack(audioTrack) {
        this.audioTracks.push(audioTrack);
    }

    checkAudioActivity() {
        // Get audio data
        this.analyser.getByteTimeDomainData(this.audioDataArray);
        
        // Calculate deviation from the center value (128)
        let sumDeviation = 0;
        for (let i = 0; i < this.audioDataArray.length; i++) {
            // Calculate how much each sample deviates from the center (128)
            sumDeviation += Math.abs(this.audioDataArray[i] - 128);
        }
        
        const averageDeviation = sumDeviation / this.audioDataArray.length;
        
        // If average deviation is above threshold, we have audio activity
        if (averageDeviation > this.silenceThreshold) {
            window.ws.sendJson({
                type: 'SilenceStatus',
                isSilent: false
            });
        }
    }

    startSilenceDetection() {
         // Set up audio context and processing as before
         this.audioContext = new AudioContext();

         this.audioSources = this.audioTracks.map(track => {
             const mediaStream = new MediaStream([track]);
             return this.audioContext.createMediaStreamSource(mediaStream);
         });
 
         // Create a destination node
         const destination = this.audioContext.createMediaStreamDestination();
 
         // Connect all sources to the destination
         this.audioSources.forEach(source => {
             source.connect(destination);
         });
 
         // Create analyzer and connect it to the destination
         this.analyser = this.audioContext.createAnalyser();
         this.analyser.fftSize = 256;
         const bufferLength = this.analyser.frequencyBinCount;
         this.audioDataArray = new Uint8Array(bufferLength);
 
         // Create a source from the destination's stream and connect it to the analyzer
         const mixedSource = this.audioContext.createMediaStreamSource(destination.stream);
         mixedSource.connect(this.analyser);
 
         this.mixedAudioTrack = destination.stream.getAudioTracks()[0];

        // Clear any existing interval
        if (this.silenceCheckInterval) {
            clearInterval(this.silenceCheckInterval);
        }
                
        // Check for audio activity every second
        this.silenceCheckInterval = setInterval(() => {
            this.checkAudioActivity();
        }, 1000);
    }

    stop() {
        this.toggleCaptureCanvasVisibility();
    }

    start() {
        // Find the main element that contains all the video elements
        this.mainElement = document.querySelector('main');
        if (!this.mainElement) {
            console.error('No <main> element found in the DOM');
            return;
        }

        //this.hideAllNonCaptureCanvasElements();
        this.captureCanvas = this.createCaptureCanvas();

        // Using the contents of the main element, compute the layout of the frame we want to render
        let frameLayout = this.computeFrameLayout(this.mainElement);

        const outerThis = this;
        let lastFrameLayoutComputationTime = 0;

        function beforeFrameRenders() {
            try {
                if (performance.now() - lastFrameLayoutComputationTime > 250)
                {
                    frameLayout = outerThis.computeFrameLayout(outerThis.mainElement);
                    lastFrameLayoutComputationTime = performance.now();
                    if (outerThis.renderState === "synced")
                    {
                        outerThis.syncCaptureCanvasElements(frameLayout);
                        outerThis.updateElementsForRenderStateChange(frameLayout);                    
                    }
                }
            }
            catch (error) {
                console.error('Error computing frame layout', error);
            }

            try {
                outerThis.makeSureElementsAreInSync(frameLayout);
            }
            catch (error) {
                console.error('Error making sure elements are in sync', error);
            }
            outerThis.updateveLabels();
            // Request the next frame
            requestAnimationFrame(beforeFrameRenders);
        }
        
        // Start the animation loop
        requestAnimationFrame(beforeFrameRenders);

        // Add keyboard listener for toggling canvas visibility
        document.addEventListener('keydown', this.handleKeyDown.bind(this));

        this.startSilenceDetection();

        console.log('Started StyleManager');
    }

    updateveLabels() {
        this.videoElementToCaptureCanvasElements.forEach((captureCanvasElements) => {
            const currentLabel = captureCanvasElements.captureCanvasLabelElement.textContent;
            const pipeIndex = currentLabel.indexOf(' | ');
            
            if (pipeIndex !== -1) {
                // Keep everything to the right of the pipe character
                const rightSideContent = currentLabel.substring(pipeIndex);
                // Replace left side with new random string
                captureCanvasElements.captureCanvasLabelElement.textContent = captureCanvasElements.captureCanvasCanvasElement.style.zIndex.toString() + '/' + captureCanvasElements.captureCanvasVideoElement.style.zIndex.toString() + ',' + this.renderState + ',' + this.renderStateUnsyncReason + ', ' + captureCanvasElements.captureCanvasVideoElement.readyState + rightSideContent;
            } else {
                // If no pipe character found, just replace the whole thing
                captureCanvasElements.captureCanvasLabelElement.textContent = captureCanvasElements.captureCanvasCanvasElement.style.zIndex.toString() + '/' + captureCanvasElements.captureCanvasVideoElement.style.zIndex.toString() + ',' + this.renderState + ',' + this.renderStateUnsyncReason + ', ' + captureCanvasElements.captureCanvasVideoElement.readyState;
            }
        });
    }

    updateElementsForRenderStateChange(captureCanvasElements) {
        this.videoElementToCaptureCanvasElements.forEach((captureCanvasElements) => {
            if (this.renderState === "unsynced") {
                if (captureCanvasElements.captureCanvasCanvasElement.style.zIndex !== '9') {
                    // use getclientrects to get the width and height of the container and the canvas
                    const containerRect = captureCanvasElements.captureCanvasContainerElement.getBoundingClientRect();
                    const canvasRect = captureCanvasElements.captureCanvasCanvasElement.getBoundingClientRect();
                    
                    // Set canvas dimensions to match container
                    captureCanvasElements.captureCanvasCanvasElement.width = containerRect.width;
                    captureCanvasElements.captureCanvasCanvasElement.height = containerRect.height;
                    
                    const ctx = captureCanvasElements.captureCanvasCanvasElement.getContext("2d");
                    
                    // Calculate dimensions to maintain aspect ratio (objectFit: 'contain')
                    const videoElement = captureCanvasElements.captureCanvasVideoElement;
                    const videoAspect = videoElement.videoWidth / videoElement.videoHeight;
                    const containerAspect = containerRect.width / containerRect.height;
                    
                    let drawWidth, drawHeight, drawX, drawY;
                    
                    if (videoAspect > containerAspect) {
                        // Video is wider - fit to width
                        drawWidth = containerRect.width;
                        drawHeight = containerRect.width / videoAspect;
                        drawX = 0;
                        drawY = (containerRect.height - drawHeight) / 2;
                    } else {
                        // Video is taller - fit to height
                        drawHeight = containerRect.height;
                        drawWidth = containerRect.height * videoAspect;
                        drawX = (containerRect.width - drawWidth) / 2;
                        drawY = 0;
                    }
                    
                    // Clear canvas and draw with proper dimensions
                    ctx.fillStyle = 'green';
                    ctx.fillRect(0, 0, containerRect.width, containerRect.height);
                    ctx.drawImage(videoElement, drawX, drawY, drawWidth, drawHeight);
                    
                }
                captureCanvasElements.captureCanvasCanvasElement.style.zIndex = '9';
                captureCanvasElements.captureCanvasVideoElement.style.zIndex = '-9999';
            }
            else {
                captureCanvasElements.captureCanvasCanvasElement.style.zIndex = '-9999';
                captureCanvasElements.captureCanvasVideoElement.style.zIndex = '9';
            }
        });            
    }

    makeSureElementsAreInSync(frameLayout) {
        this.renderStateUnsyncReason = "";
        const anyMisMatch = frameLayout.some(({ element, ssrc, videoWidth }) => {
            let captureCanvasElements = this.videoElementToCaptureCanvasElements.get(element);
            if (!captureCanvasElements) {
                return;
            }

            if (ssrc && ssrc !== this.getSSRCFromVideoElement(element)) {
                this.renderStateUnsyncReason = "SSRC mismatch";
                return true;
            }
            //if (videoWidth && videoWidth !== element.videoWidth) {
            //    this.renderStateUnsyncReason = "Video width mismatch";
            //    return true;
            //}
            if (!element.checkVisibility()) {
                this.renderStateUnsyncReason = "Element not visible";
                return true;
            }
            if (ssrc &&this.getSSRCFromVideoElementByDataAttribute(element) !== ssrc) {
                this.renderStateUnsyncReason = "SSRC mismatch v2";
                return true;
            }
            
            return false;
        });
        
        if (!anyMisMatch) {
            this.numFramesSynced++;
        }
        if (anyMisMatch) {
            this.numFramesSynced = 0;
        }

        if (anyMisMatch && this.renderState === "synced") {
            this.renderState = "unsynced";
            this.updateElementsForRenderStateChange(frameLayout);
        }

        if (!anyMisMatch && this.renderState === "unsynced" && this.numFramesSynced > 5) {
            this.renderState = "synced";
        }
    }

    handleKeyDown(event) {
        // Toggle canvas visibility when 's' key is pressed
        if (event.key === 's') {
            this.toggleCaptureCanvasVisibility();
        }
    }

    toggleCaptureCanvasVisibility() {
        if (this.captureCanvasVisible) {
            this.showAllNonCaptureCanvasElementsAndHideCaptureCanvas();
            this.captureCanvasVisible = false;
            console.log('Capture canvas hidden');
        } else {
            try {
                this.hideAllNonCaptureCanvasElements();
                this.captureCanvasVisible = true;
                console.log('Capture canvas shown');
            }
            catch (error) {
                console.error('Error showing capture canvas', error);
            }
        }
    }

    syncCaptureCanvasElements(frameLayout) {
        frameLayout.forEach(({ element, dst_rect, label }) => {
            let captureCanvasElements = this.videoElementToCaptureCanvasElements.get(element);
            if (!captureCanvasElements) {
                let captureCanvasContainerElement = document.createElement('div');
                captureCanvasContainerElement.style.position = 'absolute';
                captureCanvasContainerElement.style.padding = '0';
                captureCanvasContainerElement.style.margin = '0';
                captureCanvasContainerElement.style.border = 'none';
                captureCanvasContainerElement.style.outline = 'none';
                captureCanvasContainerElement.style.boxShadow = 'none';
                captureCanvasContainerElement.style.background = 'none';
                

                let captureCanvasVideoElement = this.trackToVideoElement.get(element.srcObject.getTracks()[0]);
                //captureCanvasVideoElement.srcObject = element.srcObject;
                //captureCanvasVideoElement.autoplay = true;
                //captureCanvasVideoElement.playsinline = true;
                captureCanvasVideoElement.style.width = '100%';
                captureCanvasVideoElement.style.height = '100%';
                captureCanvasVideoElement.style.objectFit = 'contain';
                captureCanvasVideoElement.style.position = 'absolute';
                captureCanvasVideoElement.style.border = 'yellow 2px dashed';
                captureCanvasVideoElement.style.top = '0';
                captureCanvasVideoElement.style.left = '0';
                captureCanvasVideoElement.style.zIndex = '9';
                captureCanvasContainerElement.appendChild(captureCanvasVideoElement);

                let captureCanvasLabelElement = document.createElement('div');
                captureCanvasLabelElement.style.backgroundColor = 'rgba(0, 0, 0, 0.35)';
                captureCanvasLabelElement.style.color = 'white';
                captureCanvasLabelElement.style.fontSize = '14px';
                captureCanvasLabelElement.style.textAlign = 'left';
                captureCanvasLabelElement.style.lineHeight = '1.2';
                captureCanvasLabelElement.style.padding = '3px 5px';
                captureCanvasLabelElement.style.display = 'inline-block';
                captureCanvasLabelElement.style.position = 'absolute';
                captureCanvasLabelElement.style.bottom = '3px';
                captureCanvasLabelElement.style.left = '5px';
                captureCanvasLabelElement.style.zIndex = '10'; // Add this line to ensure label is above other elements
                captureCanvasLabelElement.textContent = ' | ' + label + ' ' + Math.random().toString(36).substring(2, 15);
                captureCanvasContainerElement.appendChild(captureCanvasLabelElement);    
                
                // Add event listener for when video is paused
                captureCanvasVideoElement.addEventListener('pause', () => {
                    // Update the label with video dimensions
                    const originalLabel = captureCanvasLabelElement.textContent;
                    captureCanvasLabelElement.textContent = `${originalLabel} (VIDEO PAUSED)`;
                });

                // Add event listener for when video is ended
                captureCanvasVideoElement.addEventListener('ended', () => {
                    // Update the label with video dimensions
                    const originalLabel = captureCanvasLabelElement.textContent;
                    captureCanvasLabelElement.textContent = `${originalLabel} (VIDEO ENDED)`;
                });

                // Add event listener for when video metadata is loaded
                captureCanvasVideoElement.addEventListener('playing', () => {
                    // Update the label with video dimensions
                    const originalLabel = captureCanvasLabelElement.textContent;
                    const dimensions = `${captureCanvasVideoElement.videoWidth}x${captureCanvasVideoElement.videoHeight}`;
                    captureCanvasLabelElement.textContent = `${originalLabel} (${dimensions})`;
                });

                // Add event listener for when track ends
                const track = element.srcObject.getTracks()[0];
                if (track) {
                    track.addEventListener('ended', () => {
                            captureCanvasLabelElement.textContent = `${captureCanvasLabelElement.textContent} (STOPPED)`;
                    });
                }

                let captureCanvasCanvasElement = document.createElement('canvas');
                captureCanvasCanvasElement.style.width = '100%';
                captureCanvasCanvasElement.style.height = '100%';
                captureCanvasCanvasElement.style.position = 'absolute';
                captureCanvasCanvasElement.style.top = '0';
                captureCanvasCanvasElement.style.left = '0';
                captureCanvasCanvasElement.style.border = 'none';
                captureCanvasCanvasElement.style.display = 'none';  
                captureCanvasCanvasElement.style.zIndex = '8';              
                captureCanvasContainerElement.appendChild(captureCanvasCanvasElement);

                this.captureCanvas.appendChild(captureCanvasContainerElement);
                captureCanvasElements = {
                    captureCanvasVideoElement,
                    captureCanvasLabelElement,
                    captureCanvasContainerElement,
                    captureCanvasCanvasElement
                }
                this.videoElementToCaptureCanvasElements.set(element, captureCanvasElements);
            }

            if (captureCanvasElements.captureCanvasVideoElement.srcObject !== element.srcObject) {
                captureCanvasElements.captureCanvasVideoElement.srcObject = element.srcObject;
                
                // Update label to indicate source change
                const originalLabel = captureCanvasElements.captureCanvasLabelElement.textContent;
                captureCanvasElements.captureCanvasLabelElement.textContent = `${originalLabel} (SOURCE UPDATED)`;
            }

            captureCanvasElements.captureCanvasContainerElement.style.left = `${Math.round(dst_rect.left)}px`;
            captureCanvasElements.captureCanvasContainerElement.style.top = `${Math.round(dst_rect.top)}px`;
            captureCanvasElements.captureCanvasContainerElement.style.width = `${Math.round(dst_rect.width)}px`;
            captureCanvasElements.captureCanvasContainerElement.style.height = `${Math.round(dst_rect.height)}px`;
        });

        // For each element in videoElementToCaptureCanvasElements that was not in the frameLayout, remove it
        this.videoElementToCaptureCanvasElements.forEach((captureCanvasElements, videoElement) => {
            if (!frameLayout.some(frameLayoutElement => frameLayoutElement.element === videoElement)) {
                if (window.initialData.recordingView === 'speaker_view') {
                    // remove after a 16 ms timeout to eliminate flicker
                    setTimeout(() => {
                        this.captureCanvas.removeChild(captureCanvasElements.captureCanvasContainerElement);
                        this.videoElementToCaptureCanvasElements.delete(videoElement);
                    }, 16 * 3);                
                }
                else {
                    this.captureCanvas.removeChild(captureCanvasElements.captureCanvasContainerElement);
                    this.videoElementToCaptureCanvasElements.delete(videoElement);
                }
            }
        });
    }
    
    addVideoTrack(trackEvent) {
        const firstStreamId = trackEvent.streams[0]?.id;
        const trackId = trackEvent.track?.id;

        this.videoTrackIdToSSRC.set(trackId, firstStreamId);
        const newVideoElement = document.createElement('video');
        newVideoElement.srcObject = trackEvent.stream;
        newVideoElement.autoplay = true;
        newVideoElement.style.width = '100%';
        newVideoElement.style.height = '100%';
        newVideoElement.style.objectFit = 'contain';
        newVideoElement.style.position = 'absolute';
        newVideoElement.style.top = '0';
        newVideoElement.style.left = '0';
        newVideoElement.playsinline = true;
        this.trackToVideoElement.set(trackEvent.track, newVideoElement);
        this.captureCanvas.appendChild(newVideoElement);
    }

    createCaptureCanvas() {
        const canvas = document.createElement('div');
        canvas.classList.add('captureCanvas');
        canvas.style.width = '1920px';
        canvas.style.height = '240px';
        canvas.style.backgroundColor = 'black';
        canvas.style.position = 'fixed';
        canvas.style.top = '0';
        canvas.style.left = '0';
        canvas.style.zIndex = '9999';
        document.body.appendChild(canvas);
        return canvas;
    }

    hideAllNonCaptureCanvasElements() {
        if (this.captureCanvas) {
            this.captureCanvas.style.visibility = 'visible';
        }

        const style = document.createElement('style');
        style.textContent = `
        /* First, hide everything */
        body * {
          visibility: hidden !important;
        }
        
        /* Then, show only elements with captureCanvas class */
        body .captureCanvas,
        body .captureCanvas * {
          visibility: visible !important;
        }
        
        /* Make sure parent containers of captureCanvas elements are visible too */
        body .captureCanvas,
        body .captureCanvas *,
        body .captureCanvas:hover,
        body .captureCanvas:focus {
          visibility: visible !important;
          opacity: 1 !important;
        }
        `;
        document.head.appendChild(style);
        this.currentStyleElement = style;
    }
    
    showAllNonCaptureCanvasElementsAndHideCaptureCanvas() {
        if (this.currentStyleElement) {
            document.head.removeChild(this.currentStyleElement);
        }

        // Hide the capture canvas
        this.captureCanvas.style.visibility = 'hidden';
    }

    getActiveSpeakerElementsWithInfo(mainElement) {
        const activeSpeakerElements = mainElement.querySelectorAll('div.tC2Wod.kssMZb');

        return Array.from(activeSpeakerElements).map(element => {
            const participantElement = element.closest('[data-participant-id]');
            const participantId = participantElement ? participantElement.getAttribute('data-participant-id') : null;
            
            return {
                element: element,
                bounding_rect: element.getBoundingClientRect(),
                participant_id: participantId
            };
        }).filter(element => element.bounding_rect.width > 0 && element.bounding_rect.height > 0 && element.participant_id);
    }

    getSSRCFromVideoElement(videoElement) {
        const track_id = videoElement.srcObject?.getTracks().find(track => track.kind === 'video')?.id;
        return this.videoTrackIdToSSRC.get(track_id);
    }

    getSSRCFromVideoElementByDataAttribute(videoElement) {
        return videoElement.parentElement?.getAttribute('data-ssrc');
    }

    getVideoElementsWithInfo(mainElement, activeSpeakerElementsWithInfo) {
        const videoElements = mainElement.querySelectorAll('video');
        const results = Array.from(videoElements).map(video => {
            // Get the parent element to extract SSRC
            const containerElement = video.closest('.LBDzPb');
            const bounding_rect = video.getBoundingClientRect();
            const container_bounding_rect = containerElement.getBoundingClientRect();
            const clip_rect = {
                top: container_bounding_rect.top - bounding_rect.top,
                left: container_bounding_rect.left - bounding_rect.left,
                right: container_bounding_rect.right - bounding_rect.top,
                bottom: container_bounding_rect.bottom - bounding_rect.left,
                width: container_bounding_rect.width,
                height: container_bounding_rect.height,
            }
            const ssrc = this.getSSRCFromVideoElement(video);
            const user = window.userManager.getUserByStreamId(ssrc);
            return {
                element: video,
                bounding_rect: bounding_rect,
                container_bounding_rect: container_bounding_rect,
                clip_rect: clip_rect,
                ssrc: ssrc,
                user: user,
                is_screen_share: Boolean(user?.parentDeviceId),
                is_active_speaker: activeSpeakerElementsWithInfo?.[0]?.participant_id === user?.deviceId,
            };
        }).filter(video => video.ssrc && video.user && !video.paused && video.bounding_rect.width > 0 && video.bounding_rect.height > 0 && video.element.readyState === 4);
        const largestContainerBoundingRectArea = results.reduce((max, video) => {
            return Math.max(max, video.container_bounding_rect.width * video.container_bounding_rect.height);
        }, 0);
        return results.map(video => {
            return {
                ...video,
                is_largest: video.container_bounding_rect.width * video.container_bounding_rect.height === largestContainerBoundingRectArea,
            };
        });
    }

    computeFrameLayout(mainElement) {
        const activeSpeakerElementsWithInfo = this.getActiveSpeakerElementsWithInfo(mainElement);
        const videoElementsWithInfo = this.getVideoElementsWithInfo(mainElement, activeSpeakerElementsWithInfo);

        const layoutElements = [];

        if (window.initialData.recordingView === 'speaker_view') {
            const screenShareVideo = videoElementsWithInfo.find(video => video.is_screen_share);
            if (screenShareVideo) {
                layoutElements.push({
                    element: screenShareVideo.element,
                    dst_rect: screenShareVideo.bounding_rect,
                    ssrc: screenShareVideo.ssrc,
                });
                const activeSpeakerVideo = videoElementsWithInfo.find(video => video.is_active_speaker);
                if (activeSpeakerVideo) {                    
                    // Calculate position in upper right corner of screen share
                    const x = screenShareVideo.bounding_rect.right - activeSpeakerVideo.bounding_rect.width;
                    const y = screenShareVideo.bounding_rect.top;
                    
                    layoutElements.push({
                        element: activeSpeakerVideo.element,
                        dst_rect: {
                            left: x,
                            top: y,
                            width: activeSpeakerVideo.bounding_rect.width,
                            height: activeSpeakerVideo.bounding_rect.height
                        },
                        label: activeSpeakerVideo.user?.fullName || activeSpeakerVideo.user?.displayName,
                        ssrc: activeSpeakerVideo.ssrc,
                    });
                }
            }
            else
            {
                const mainParticipantVideo = videoElementsWithInfo.find(video => video.is_largest) || videoElementsWithInfo[0];
                this.lastMainParticipantVideoSsrc = mainParticipantVideo?.ssrc;
                if (mainParticipantVideo) {                   
                    layoutElements.push({
                        element: mainParticipantVideo.element,
                        dst_rect: mainParticipantVideo.bounding_rect,
                        label: mainParticipantVideo.user?.fullName || mainParticipantVideo.user?.displayName,
                        ssrc: mainParticipantVideo.ssrc,
                    });
                }
            }

            return this.scaleLayoutToCanvasWithLetterBoxing(layoutElements);
        }

        if (window.initialData.recordingView === 'gallery_view') {
            const videoElementsFiltered = videoElementsWithInfo.filter(video => !video.is_screen_share);

            const ssrcsInCurrentFrame = videoElementsFiltered.map(video => video.ssrc);
            const ssrcsInCurrentFrameSet = new Set(ssrcsInCurrentFrame);
            this.ssrcsInLastFrame = this.ssrcsInLastFrame || [];
            this.ssrcsOrder = this.ssrcsOrder || [];

            // Remove ssrcs that are not in the current frame
            this.ssrcsOrder = this.ssrcsOrder.filter(ssrc => ssrcsInCurrentFrameSet.has(ssrc));
            // Add ssrcs that are in the current frame but are not in ssrcsOrder
            const ssrcsOrderSet = new Set(this.ssrcsOrder);
            this.ssrcsOrder.push(...ssrcsInCurrentFrame.filter(ssrc => !ssrcsOrderSet.has(ssrc)));

            const numCols = Math.ceil(Math.sqrt(this.ssrcsOrder.length));
            const cellWidth = 1920 / numCols;
            const cellHeight = 1080 / numCols;

            const ssrcToVideoElement = new Map(videoElementsFiltered.map(video => [video.ssrc, video]));
                       
            let galleryLayoutElements = [];
            this.ssrcsOrder.forEach((ssrc, index) => {
                const video = ssrcToVideoElement.get(ssrc);
                if (!video) {
                    console.error('Video element not found for ssrc', ssrc);
                    return;
                }

                const videoWidth = video.element.videoWidth;
                const videoHeight = video.element.videoHeight;
                const videoAspect = videoWidth / videoHeight;
                const cellAspect = (cellWidth - 10) / (cellHeight - 10);
                
                let cropX, cropY, cropWidth, cropHeight;
                
                // Determine crop dimensions to match cell aspect ratio
                if (videoAspect > cellAspect) {
                    // Video is wider than cell - crop width
                    cropHeight = videoHeight;
                    cropWidth = videoHeight * cellAspect;
                } else {
                    // Video is taller than cell - crop height
                    cropWidth = videoWidth;
                    cropHeight = videoWidth / cellAspect;
                }

                cropX = (videoWidth - cropWidth) / 2;
                cropY = (videoHeight - cropHeight) / 2;

                galleryLayoutElements.push({
                    element: video.element,
                    src_rect: {
                        left: cropX,
                        top: cropY,
                        width: cropWidth,
                        height: cropHeight
                    },
                    dst_rect: {
                        left: (index % numCols) * cellWidth + 5,
                        top: Math.floor(index / numCols) * cellHeight + 5,
                        width: cellWidth - 10,
                        height: cellHeight - 10
                    },
                    label: video.user?.fullName || video.user?.displayName,
                    videoWidth: videoWidth,
                    ssrc: video.ssrc,
                });
            });

            this.ssrcsInLastFrame = ssrcsInCurrentFrame;

            return this.scaleLayoutToCanvasWithLetterBoxing(galleryLayoutElements);
        }

        return layoutElements;
    }

    scaleLayoutToCanvasWithLetterBoxing(layoutElements) {
        if (layoutElements.length === 0) {
            return layoutElements;
        }

        const canvasWidth = 1920;
        const canvasHeight = 240;
        let minX = Infinity;
        let minY = Infinity;
        let maxX = 0;
        let maxY = 0;

        // Find active videos and determine the bounding box
        layoutElements.forEach(({ element, dst_rect }) => {
            if (element.videoWidth > 0 && element.videoHeight > 0) {
                minX = Math.min(minX, dst_rect.left);
                minY = Math.min(minY, dst_rect.top);
                maxX = Math.max(maxX, dst_rect.left + dst_rect.width);
                maxY = Math.max(maxY, dst_rect.top + dst_rect.height);
            }
        });

        const boundingWidth = maxX - minX;
        const boundingHeight = maxY - minY;

        // Calculate aspect ratios
        const inputAspect = boundingWidth / boundingHeight;
        const outputAspect = canvasWidth / canvasHeight;
        let scaledWidth, scaledHeight, offsetX, offsetY;

        if (Math.abs(inputAspect - outputAspect) < 1e-2) {
            // Same aspect ratio, use full canvas
            scaledWidth = canvasWidth;
            scaledHeight = canvasHeight;
            offsetX = 0;
            offsetY = 0;
        } else if (inputAspect > outputAspect) {
            // Input is wider, fit to width with letterboxing
            scaledWidth = canvasWidth;
            scaledHeight = canvasWidth / inputAspect;
            offsetX = 0;
            offsetY = (canvasHeight - scaledHeight) / 2;
        } else {
            // Input is taller, fit to height with pillarboxing
            scaledHeight = canvasHeight;
            scaledWidth = canvasHeight * inputAspect;
            offsetX = (canvasWidth - scaledWidth) / 2;
            offsetY = 0;
        }

        return layoutElements.map(layoutElement => {
            const dst_rect = layoutElement.dst_rect;
            const relativeX = (dst_rect.left - minX) / boundingWidth;
            const relativeY = (dst_rect.top - minY) / boundingHeight;
            const relativeWidth = dst_rect.width / boundingWidth;
            const relativeHeight = dst_rect.height / boundingHeight;

            const dst_rect_transformed = {
                left: offsetX + relativeX * scaledWidth,
                top: offsetY + relativeY * scaledHeight,
                width: relativeWidth * scaledWidth,
                height: relativeHeight * scaledHeight,
            }

            return {
                ...layoutElement,
                dst_rect: dst_rect_transformed,
            };
        });
    }
}

class FullCaptureManager {
    constructor() {
        this.videoTrack = null;
        this.audioSources = [];
        this.mixedAudioTrack = null;
        this.canvasStream = null;
        this.finalStream = null;
        this.mediaRecorder = null;
        this.audioContext = null;
        this.observer = null;
        this.audioTracks = [];
        this.layoutUpdateInterval = null;

        this.silenceThreshold = 0.0;
        this.silenceCheckInterval = null;

        this.videoTrackIdToSSRC = new Map();
    }

    addVideoTrack(trackEvent) {
        const firstStreamId = trackEvent.streams[0]?.id;
        const trackId = trackEvent.track?.id;

        this.videoTrackIdToSSRC.set(trackId, firstStreamId);
    }

    addAudioTrack(audioTrack) {
        this.audioTracks.push(audioTrack);
    }

    getActiveSpeakerElementsWithInfo(mainElement) {
        const activeSpeakerElements = mainElement.querySelectorAll('div.tC2Wod.kssMZb');

        return Array.from(activeSpeakerElements).map(element => {
            const participantElement = element.closest('[data-participant-id]');
            const participantId = participantElement ? participantElement.getAttribute('data-participant-id') : null;
            
            return {
                element: element,
                bounding_rect: element.getBoundingClientRect(),
                participant_id: participantId
            };
        }).filter(element => element.bounding_rect.width > 0 && element.bounding_rect.height > 0 && element.participant_id);
    }

    getSSRCFromVideoElement(videoElement) {
        const track_id = videoElement.srcObject?.getTracks().find(track => track.kind === 'video')?.id;
        return this.videoTrackIdToSSRC.get(track_id);
    }

    getVideoElementsWithInfo(mainElement, activeSpeakerElementsWithInfo) {
        const videoElements = mainElement.querySelectorAll('video');
        return Array.from(videoElements).map(video => {
            // Get the parent element to extract SSRC
            const containerElement = video.closest('.LBDzPb');
            const bounding_rect = video.getBoundingClientRect();
            const container_bounding_rect = containerElement.getBoundingClientRect();
            const clip_rect = {
                top: container_bounding_rect.top - bounding_rect.top,
                left: container_bounding_rect.left - bounding_rect.left,
                right: container_bounding_rect.right - bounding_rect.top,
                bottom: container_bounding_rect.bottom - bounding_rect.left,
                width: container_bounding_rect.width,
                height: container_bounding_rect.height,
            }
            const ssrc = this.getSSRCFromVideoElement(video);
            const user = window.userManager.getUserByStreamId(ssrc);
            return {
                element: video,
                bounding_rect: bounding_rect,
                container_bounding_rect: container_bounding_rect,
                clip_rect: clip_rect,
                ssrc: ssrc,
                user: user,
                is_screen_share: Boolean(user?.parentDeviceId),
                is_active_speaker: activeSpeakerElementsWithInfo?.[0]?.participant_id === user?.deviceId,
            };
        }).filter(video => video.ssrc && video.user && !video.paused && video.bounding_rect.width > 0 && video.bounding_rect.height > 0);
    }

    computeFrameLayout(mainElement) {
        const activeSpeakerElementsWithInfo = this.getActiveSpeakerElementsWithInfo(mainElement);
        const videoElementsWithInfo = this.getVideoElementsWithInfo(mainElement, activeSpeakerElementsWithInfo);

        const layoutElements = [];

        if (window.initialData.recordingView === 'speaker_view') {
            const screenShareVideo = videoElementsWithInfo.find(video => video.is_screen_share);
            if (screenShareVideo) {
                layoutElements.push({
                    element: screenShareVideo.element,
                    dst_rect: screenShareVideo.bounding_rect,
                    ssrc: screenShareVideo.ssrc,
                });
                const activeSpeakerVideo = videoElementsWithInfo.find(video => video.is_active_speaker);
                if (activeSpeakerVideo) {                    
                    // Calculate position in upper right corner of screen share
                    const x = screenShareVideo.bounding_rect.right - activeSpeakerVideo.bounding_rect.width;
                    const y = screenShareVideo.bounding_rect.top;
                    
                    layoutElements.push({
                        element: activeSpeakerVideo.element,
                        dst_rect: {
                            left: x,
                            top: y,
                            width: activeSpeakerVideo.bounding_rect.width,
                            height: activeSpeakerVideo.bounding_rect.height
                        },
                        label: activeSpeakerVideo.user?.fullName || activeSpeakerVideo.user?.displayName,
                        ssrc: activeSpeakerVideo.ssrc,
                    });
                }
            }
            else
            {
                const mainParticipantVideo = videoElementsWithInfo.find(video => video.is_active_speaker) || videoElementsWithInfo.find(video => video.ssrc === this.lastMainParticipantVideoSsrc) || videoElementsWithInfo[0];
                this.lastMainParticipantVideoSsrc = mainParticipantVideo?.ssrc;
                if (mainParticipantVideo) {                   
                    layoutElements.push({
                        element: mainParticipantVideo.element,
                        dst_rect: mainParticipantVideo.bounding_rect,
                        label: mainParticipantVideo.user?.fullName || mainParticipantVideo.user?.displayName,
                        ssrc: mainParticipantVideo.ssrc,
                    });
                }
            }

            return this.scaleLayoutToCanvasWithLetterBoxing(layoutElements);
        }

        if (window.initialData.recordingView === 'gallery_view') {
            const videoElementsFiltered = videoElementsWithInfo.filter(video => !video.is_screen_share);

            const ssrcsInCurrentFrame = videoElementsFiltered.map(video => video.ssrc);
            const ssrcsInCurrentFrameSet = new Set(ssrcsInCurrentFrame);
            this.ssrcsInLastFrame = this.ssrcsInLastFrame || [];
            this.ssrcsOrder = this.ssrcsOrder || [];

            // Remove ssrcs that are not in the current frame
            this.ssrcsOrder = this.ssrcsOrder.filter(ssrc => ssrcsInCurrentFrameSet.has(ssrc));
            // Add ssrcs that are in the current frame but are not in ssrcsOrder
            const ssrcsOrderSet = new Set(this.ssrcsOrder);
            this.ssrcsOrder.push(...ssrcsInCurrentFrame.filter(ssrc => !ssrcsOrderSet.has(ssrc)));

            const numCols = Math.ceil(Math.sqrt(this.ssrcsOrder.length));
            const cellWidth = 1920 / numCols;
            const cellHeight = 1080 / numCols;

            const ssrcToVideoElement = new Map(videoElementsFiltered.map(video => [video.ssrc, video]));
                       
            let galleryLayoutElements = [];
            this.ssrcsOrder.forEach((ssrc, index) => {
                const video = ssrcToVideoElement.get(ssrc);
                if (!video) {
                    console.error('Video element not found for ssrc', ssrc);
                    return;
                }

                const videoWidth = video.element.videoWidth;
                const videoHeight = video.element.videoHeight;
                const videoAspect = videoWidth / videoHeight;
                const cellAspect = (cellWidth - 10) / (cellHeight - 10);
                
                let cropX, cropY, cropWidth, cropHeight;
                
                // Determine crop dimensions to match cell aspect ratio
                if (videoAspect > cellAspect) {
                    // Video is wider than cell - crop width
                    cropHeight = videoHeight;
                    cropWidth = videoHeight * cellAspect;
                } else {
                    // Video is taller than cell - crop height
                    cropWidth = videoWidth;
                    cropHeight = videoWidth / cellAspect;
                }

                cropX = (videoWidth - cropWidth) / 2;
                cropY = (videoHeight - cropHeight) / 2;

                galleryLayoutElements.push({
                    element: video.element,
                    src_rect: {
                        left: cropX,
                        top: cropY,
                        width: cropWidth,
                        height: cropHeight
                    },
                    dst_rect: {
                        left: (index % numCols) * cellWidth + 5,
                        top: Math.floor(index / numCols) * cellHeight + 5,
                        width: cellWidth - 10,
                        height: cellHeight - 10
                    },
                    label: video.user?.fullName || video.user?.displayName,
                    videoWidth: videoWidth,
                    ssrc: video.ssrc,
                });
            });

            this.ssrcsInLastFrame = ssrcsInCurrentFrame;

            return this.scaleLayoutToCanvasWithLetterBoxing(galleryLayoutElements);
        }

        return layoutElements;
    }

    scaleLayoutToCanvasWithLetterBoxing(layoutElements) {
        if (layoutElements.length === 0) {
            return layoutElements;
        }

        const canvasWidth = 1920;
        const canvasHeight = 1080;
        let minX = Infinity;
        let minY = Infinity;
        let maxX = 0;
        let maxY = 0;

        // Find active videos and determine the bounding box
        layoutElements.forEach(({ element, dst_rect }) => {
            if (element.videoWidth > 0 && element.videoHeight > 0) {
                minX = Math.min(minX, dst_rect.left);
                minY = Math.min(minY, dst_rect.top);
                maxX = Math.max(maxX, dst_rect.left + dst_rect.width);
                maxY = Math.max(maxY, dst_rect.top + dst_rect.height);
            }
        });

        const boundingWidth = maxX - minX;
        const boundingHeight = maxY - minY;

        // Calculate aspect ratios
        const inputAspect = boundingWidth / boundingHeight;
        const outputAspect = canvasWidth / canvasHeight;
        let scaledWidth, scaledHeight, offsetX, offsetY;

        if (Math.abs(inputAspect - outputAspect) < 1e-2) {
            // Same aspect ratio, use full canvas
            scaledWidth = canvasWidth;
            scaledHeight = canvasHeight;
            offsetX = 0;
            offsetY = 0;
        } else if (inputAspect > outputAspect) {
            // Input is wider, fit to width with letterboxing
            scaledWidth = canvasWidth;
            scaledHeight = canvasWidth / inputAspect;
            offsetX = 0;
            offsetY = (canvasHeight - scaledHeight) / 2;
        } else {
            // Input is taller, fit to height with pillarboxing
            scaledHeight = canvasHeight;
            scaledWidth = canvasHeight * inputAspect;
            offsetX = (canvasWidth - scaledWidth) / 2;
            offsetY = 0;
        }

        return layoutElements.map(layoutElement => {
            const dst_rect = layoutElement.dst_rect;
            const relativeX = (dst_rect.left - minX) / boundingWidth;
            const relativeY = (dst_rect.top - minY) / boundingHeight;
            const relativeWidth = dst_rect.width / boundingWidth;
            const relativeHeight = dst_rect.height / boundingHeight;

            const dst_rect_transformed = {
                left: offsetX + relativeX * scaledWidth,
                top: offsetY + relativeY * scaledHeight,
                width: relativeWidth * scaledWidth,
                height: relativeHeight * scaledHeight,
            }

            return {
                ...layoutElement,
                dst_rect: dst_rect_transformed,
            };
        });
    }

    async start() {
        // Find the main element that contains all the video elements
        const mainElement = document.querySelector('main');
        if (!mainElement) {
            console.error('No <main> element found in the DOM');
            return;
        }

        // Create a canvas element with dimensions of rendered frame
        const canvas = document.createElement('canvas');
        canvas.width = 1920;
        canvas.height = 1080;
        document.body.appendChild(canvas);

        const debugCanvas = false;
        if (debugCanvas) {
            canvas.style.position = 'fixed';
            canvas.style.top = '0';
            canvas.style.left = '0';
            canvas.style.zIndex = '9999';
            canvas.style.border = '2px solid red';
            canvas.style.opacity = '1.0';
    
            
            // Create toggle button for canvas visibility
            const toggleButton = document.createElement('button');
            toggleButton.textContent = 'Show Canvas';
            toggleButton.style.position = 'fixed';
            toggleButton.style.bottom = '20px';
            toggleButton.style.right = '20px';
            toggleButton.style.zIndex = '10000';
            toggleButton.style.padding = '8px 12px';
            toggleButton.style.backgroundColor = '#4285f4';
            toggleButton.style.color = 'white';
            toggleButton.style.border = 'none';
            toggleButton.style.borderRadius = '4px';
            toggleButton.style.cursor = 'pointer';
            toggleButton.style.fontFamily = 'Arial, sans-serif';
            
            // Toggle canvas visibility function
            toggleButton.addEventListener('click', () => {
                if (canvas.style.opacity === '0') {
                    canvas.style.opacity = '1.0';
                    toggleButton.textContent = 'Hide Canvas';
                } else {
                    canvas.style.opacity = '0';
                    toggleButton.textContent = 'Show Canvas';
                }
            });
            
            document.body.appendChild(toggleButton);
            this.toggleButton = toggleButton; // Store reference for cleanup
        }
        

        // Set up the canvas context for drawing
        const canvasContext = canvas.getContext('2d');

        // Using the contents of the main element, compute the layout of the frame we want to render
        let frameLayout = this.computeFrameLayout(mainElement);

        // Create a MutationObserver to watch for changes to the DOM
        this.observer = new MutationObserver((mutations) => {
            // Update the frame layout when DOM changes
            frameLayout = this.computeFrameLayout(mainElement);
        });

        // Commented out mutation observer because we don't need it anymore
        // Just recomputing the layout every 500ms works good
        // Start observing the main element for changes which will trigger a recomputation of the frame layout
        // TODO: This observer fires whenever someone speaks. We should try to see if we can filter those out so it fires less often
        // because the computeFrameLayout is a relatively expensive operation
        /*
        this.observer.observe(mainElement, { 
            childList: true,      // Watch for added/removed nodes
            subtree: true,        // Watch all descendants
            attributes: false,    // Don't need to watch attributes
            characterData: false  // Don't need to watch text content
        });*/

        // Set up a timer to update the frame layout every 100
        this.layoutUpdateInterval = setInterval(() => {
            frameLayout = this.computeFrameLayout(mainElement);
        }, 100);

        // Create a drawing function that runs at 30fps
        const drawFrameLayoutToCanvas = () => {  
            try {
                const hasMismatchOrInvisible = frameLayout.some(({ element, ssrc, videoWidth }) => 
                    (ssrc && ssrc !== this.getSSRCFromVideoElement(element)) ||
                    (videoWidth && videoWidth !== element.videoWidth) ||
                    !element.checkVisibility()
                );
                
                if (hasMismatchOrInvisible) {
                    // Schedule the next frame and exit
                    this.animationFrameId = requestAnimationFrame(drawFrameLayoutToCanvas);
                    return;
                }

                // Clear the canvas with black background
                canvasContext.fillStyle = 'black';
                canvasContext.fillRect(0, 0, canvas.width, canvas.height);


                frameLayout.forEach(({ element, dst_rect, src_rect, label }) => {

                    if (src_rect) {
                        canvasContext.drawImage(
                            element,
                            src_rect.left,
                            src_rect.top,
                            src_rect.width,
                            src_rect.height,
                            dst_rect.left,
                            dst_rect.top,
                            dst_rect.width,
                            dst_rect.height
                        );
                    }
                    else {
                        canvasContext.drawImage(
                            element,
                            dst_rect.left,
                            dst_rect.top,
                            dst_rect.width,
                            dst_rect.height
                        );
                    }

                    if (label) {
                        canvasContext.fillStyle = 'white';
                        canvasContext.font = 'bold 16px Arial';
                        canvasContext.fillText(label, dst_rect.left + 16, dst_rect.top + dst_rect.height - 16);
                    }
                });

                // Schedule the next frame
                this.animationFrameId = requestAnimationFrame(drawFrameLayoutToCanvas);
            } catch (e) {
                console.error('Error drawing frame layout to canvas', e);
            }
        };

        // Start the drawing loop
        drawFrameLayoutToCanvas();

        // Capture the canvas stream at 30 fps
        const canvasStream = canvas.captureStream(30);
        const [videoTrack] = canvasStream.getVideoTracks();
        this.videoTrack = videoTrack;
        this.canvas = canvas; // Store canvas reference for cleanup

        // Set up audio context and processing as before
        this.audioContext = new AudioContext();

        this.audioSources = this.audioTracks.map(track => {
            const mediaStream = new MediaStream([track]);
            return this.audioContext.createMediaStreamSource(mediaStream);
        });

        // Create a destination node
        const destination = this.audioContext.createMediaStreamDestination();

        // Connect all sources to the destination
        this.audioSources.forEach(source => {
            source.connect(destination);
        });

        // Create analyzer and connect it to the destination
        this.analyser = this.audioContext.createAnalyser();
        this.analyser.fftSize = 256;
        const bufferLength = this.analyser.frequencyBinCount;
        this.audioDataArray = new Uint8Array(bufferLength);

        // Create a source from the destination's stream and connect it to the analyzer
        const mixedSource = this.audioContext.createMediaStreamSource(destination.stream);
        mixedSource.connect(this.analyser);

        this.mixedAudioTrack = destination.stream.getAudioTracks()[0];

        this.finalStream = new MediaStream([
            this.videoTrack,
            this.mixedAudioTrack
        ]);

        // Initialize MediaRecorder with the final stream
        this.startRecording();

        this.startSilenceDetection();
    }

    startSilenceDetection() {
        // Clear any existing interval
        if (this.silenceCheckInterval) {
            clearInterval(this.silenceCheckInterval);
        }
                
        // Check for audio activity every second
        this.silenceCheckInterval = setInterval(() => {
            this.checkAudioActivity();
        }, 1000);
    }

    checkAudioActivity() {
        // Get audio data
        this.analyser.getByteTimeDomainData(this.audioDataArray);
        
        // Calculate deviation from the center value (128)
        let sumDeviation = 0;
        for (let i = 0; i < this.audioDataArray.length; i++) {
            // Calculate how much each sample deviates from the center (128)
            sumDeviation += Math.abs(this.audioDataArray[i] - 128);
        }
        
        const averageDeviation = sumDeviation / this.audioDataArray.length;
        
        // If average deviation is above threshold, we have audio activity
        if (averageDeviation > this.silenceThreshold) {
            window.ws.sendJson({
                type: 'SilenceStatus',
                isSilent: false
            });
        }
    }

    startRecording() {
        // Options for better quality
        const options = { mimeType: 'video/mp4' };
        this.mediaRecorder = new MediaRecorder(this.finalStream, options);

        this.mediaRecorder.ondataavailable = (event) => {
            if (event.data.size > 0) {
                console.log('ondataavailable', event.data.size);
                window.ws.sendEncodedMP4Chunk(event.data);
            }
        };

        this.mediaRecorder.onstop = () => {
            this.saveRecording();
        };

        // Start recording, collect data in chunks every 1 second
        this.mediaRecorder.start(1000);
        console.log("Recording started");
    }

    stopRecording() {
        if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
            this.mediaRecorder.stop();
            console.log("Recording stopped");
        }
    }

    stop() {
        this.stopRecording();

        // Clear silence detection interval
        if (this.silenceCheckInterval) {
            clearInterval(this.silenceCheckInterval);
            this.silenceCheckInterval = null;
        }

        // Clear layout update interval
        if (this.layoutUpdateInterval) {
            clearInterval(this.layoutUpdateInterval);
            this.layoutUpdateInterval = null;
        }

        // Cancel animation frame if it exists
        if (this.animationFrameId) {
            cancelAnimationFrame(this.animationFrameId);
            this.animationFrameId = null;
        }

        // Disconnect the MutationObserver
        if (this.observer) {
            this.observer.disconnect();
            this.observer = null;
        }

        // Remove canvas element if it exists
        if (this.canvas) {
            document.body.removeChild(this.canvas);
            this.canvas = null;
        }

        // Stop all tracks
        if (this.videoTrack) this.videoTrack.stop();
        if (this.mixedAudioTrack) this.mixedAudioTrack.stop();

        // Clean up
        this.videoTrack = null;
        this.mixedAudioTrack = null;
        this.finalStream = null;
        this.mediaRecorder = null;
    }
}

// Video track manager
class VideoTrackManager {
    constructor(ws) {
        this.videoTracks = new Map();
        this.ws = ws;
        this.trackToSendCache = null;
    }

    deleteVideoTrack(videoTrack) {
        this.videoTracks.delete(videoTrack.id);
        this.trackToSendCache = null;
    }

    upsertVideoTrack(videoTrack, streamId, isScreenShare) {
        const existingVideoTrack = this.videoTracks.get(videoTrack.id);

        // Create new object with track info and firstSeenAt timestamp
        const trackInfo = {
            originalTrack: videoTrack,
            isScreenShare: isScreenShare,
            firstSeenAt: existingVideoTrack ? existingVideoTrack.firstSeenAt : Date.now(),
            streamId: streamId
        };
 
        console.log('upsertVideoTrack for', videoTrack.id, '=', trackInfo);
        
        this.videoTracks.set(videoTrack.id, trackInfo);
        this.trackToSendCache = null;
    }

    getStreamIdToSendCached() {
        return this.getTrackToSendCached()?.streamId;
    }

    getTrackToSendCached() {
        if (this.trackToSendCache) {
            return this.trackToSendCache;
        }

        this.trackToSendCache = this.getTrackToSend();
        return this.trackToSendCache;
    }

    getTrackToSend() {
        const screenShareTracks = Array.from(this.videoTracks.values()).filter(track => track.isScreenShare);
        const mostRecentlyCreatedScreenShareTrack = screenShareTracks.reduce((max, track) => {
            return track.firstSeenAt > max.firstSeenAt ? track : max;
        }, screenShareTracks[0]);

        if (mostRecentlyCreatedScreenShareTrack) {
            return mostRecentlyCreatedScreenShareTrack;
        }

        const nonScreenShareTracks = Array.from(this.videoTracks.values()).filter(track => !track.isScreenShare);
        const mostRecentlyCreatedNonScreenShareTrack = nonScreenShareTracks.reduce((max, track) => {
            return track.firstSeenAt > max.firstSeenAt ? track : max;
        }, nonScreenShareTracks[0]);

        if (mostRecentlyCreatedNonScreenShareTrack) {
            return mostRecentlyCreatedNonScreenShareTrack;
        }

        return null;
    }
}

// Caption manager
class CaptionManager {
    constructor(ws) {
        this.captions = new Map();
        this.ws = ws;
    }

    singleCaptionSynced(caption) {
        this.captions.set(caption.captionId, caption);
        this.ws.sendClosedCaptionUpdate(caption);
    }
}

const DEVICE_OUTPUT_TYPE = {
    AUDIO: 1,
    VIDEO: 2
}

// User manager
class UserManager {
    constructor(ws) {
        this.allUsersMap = new Map();
        this.currentUsersMap = new Map();
        this.deviceOutputMap = new Map();

        this.ws = ws;
    }

    deviceForStreamIsActive(streamId) {
        for(const deviceOutput of this.deviceOutputMap.values()) {
            if (deviceOutput.streamId === streamId) {
                return !deviceOutput.disabled;
            }
        }

        return false;
    }

    getDeviceOutput(deviceId, outputType) {
        return this.deviceOutputMap.get(`${deviceId}-${outputType}`);
    }

    updateDeviceOutputs(deviceOutputs) {
        for (const output of deviceOutputs) {
            const key = `${output.deviceId}-${output.deviceOutputType}`; // Unique key combining device ID and output type

            const deviceOutput = {
                deviceId: output.deviceId,
                outputType: output.deviceOutputType, // 1 = audio, 2 = video
                streamId: output.streamId,
                disabled: output.deviceOutputStatus.disabled,
                lastUpdated: Date.now()
            };

            this.deviceOutputMap.set(key, deviceOutput);
        }

        // Notify websocket clients about the device output update
        this.ws.sendJson({
            type: 'DeviceOutputsUpdate',
            deviceOutputs: Array.from(this.deviceOutputMap.values())
        });
    }

    getUserByStreamId(streamId) {
        // Look through device output map and find the corresponding device id. Then look up the user by device id.
        for (const deviceOutput of this.deviceOutputMap.values()) {
            if (deviceOutput.streamId === streamId) {
                return this.allUsersMap.get(deviceOutput.deviceId);
            }
        }

        return null;
    }

    getUserByDeviceId(deviceId) {
        return this.allUsersMap.get(deviceId);
    }

    // constants for meeting status
    MEETING_STATUS = {
        IN_MEETING: 1,
        NOT_IN_MEETING: 6
    }

    getCurrentUsersInMeeting() {
        return Array.from(this.currentUsersMap.values()).filter(user => user.status === this.MEETING_STATUS.IN_MEETING);
    }

    getCurrentUsersInMeetingWhoAreScreenSharing() {
        return this.getCurrentUsersInMeeting().filter(user => user.parentDeviceId);
    }

    singleUserSynced(user) {
      // Create array with new user and existing users, then filter for unique deviceIds
      // keeping the first occurrence (new user takes precedence)
      const allUsers = [...this.currentUsersMap.values(), user];
      const uniqueUsers = Array.from(
        new Map(allUsers.map(user => [user.deviceId, user])).values()
      );
      this.newUsersListSynced(uniqueUsers);
    }

    newUsersListSynced(newUsersListRaw) {
        const newUsersList = newUsersListRaw.map(user => {
            const userStatusMap = {
                1: 'in_meeting',
                6: 'not_in_meeting',
                7: 'removed_from_meeting'
            }

            return {
                ...user,
                humanized_status: userStatusMap[user.status] || "unknown"
            }
        })
        // Get the current user IDs before updating
        const previousUserIds = new Set(this.currentUsersMap.keys());
        const newUserIds = new Set(newUsersList.map(user => user.deviceId));
        const updatedUserIds = new Set([])

        // Update all users map
        for (const user of newUsersList) {
            if (previousUserIds.has(user.deviceId) && JSON.stringify(this.currentUsersMap.get(user.deviceId)) !== JSON.stringify(user)) {
                updatedUserIds.add(user.deviceId);
            }

            this.allUsersMap.set(user.deviceId, {
                deviceId: user.deviceId,
                displayName: user.displayName,
                fullName: user.fullName,
                profile: user.profile,
                status: user.status,
                humanized_status: user.humanized_status,
                parentDeviceId: user.parentDeviceId
            });
        }

        // Calculate new, removed, and updated users
        const newUsers = newUsersList.filter(user => !previousUserIds.has(user.deviceId));
        const removedUsers = Array.from(previousUserIds)
            .filter(id => !newUserIds.has(id))
            .map(id => this.currentUsersMap.get(id));

        // Clear current users map and update with new list
        this.currentUsersMap.clear();
        for (const user of newUsersList) {
            this.currentUsersMap.set(user.deviceId, {
                deviceId: user.deviceId,
                displayName: user.displayName,
                fullName: user.fullName,
                profilePicture: user.profilePicture,
                status: user.status,
                humanized_status: user.humanized_status,
                parentDeviceId: user.parentDeviceId
            });
        }

        const updatedUsers = Array.from(updatedUserIds).map(id => this.currentUsersMap.get(id));

        if (newUsers.length > 0 || removedUsers.length > 0 || updatedUsers.length > 0) {
            this.ws.sendJson({
                type: 'UsersUpdate',
                newUsers: newUsers,
                removedUsers: removedUsers,
                updatedUsers: updatedUsers
            });
        }
    }
}

// Websocket client
class WebSocketClient {
  // Message types
  static MESSAGE_TYPES = {
      JSON: 1,
      VIDEO: 2,
      AUDIO: 3,
      ENCODED_MP4_CHUNK: 4
  };

  constructor() {
      const url = `ws://localhost:${window.initialData.websocketPort}`;
      console.log('WebSocketClient url', url);
      this.ws = new WebSocket(url);
      this.ws.binaryType = 'arraybuffer';
      
      this.ws.onopen = () => {
          console.log('WebSocket Connected');
      };
      
      this.ws.onmessage = (event) => {
          this.handleMessage(event.data);
      };
      
      this.ws.onerror = (error) => {
          console.error('WebSocket Error:', error);
      };
      
      this.ws.onclose = () => {
          console.log('WebSocket Disconnected');
      };

      this.mediaSendingEnabled = false;
      
      /*
      We no longer need this because we're not using MediaStreamTrackProcessor's
      this.lastVideoFrameTime = performance.now();
      this.fillerFrameInterval = null;

      this.lastVideoFrame = this.getBlackFrame();
      this.blackVideoFrame = this.getBlackFrame();
      */
  }

  /*
  We no longer need this because we're not using MediaStreamTrackProcessor's
  getBlackFrame() {
    // Create black frame data (I420 format)
    const width = 1920, height = 1080;
    const yPlaneSize = width * height;
    const uvPlaneSize = (width * height) / 4;

    const frameData = new Uint8Array(yPlaneSize + 2 * uvPlaneSize);
    // Y plane (black = 0)
    frameData.fill(0, 0, yPlaneSize);
    // U and V planes (black = 128)
    frameData.fill(128, yPlaneSize);

    return {width, height, frameData};
  }

  currentVideoStreamIsActive() {
    const result = window.userManager?.deviceForStreamIsActive(window.videoTrackManager?.getStreamIdToSendCached());

    // This avoids a situation where we transition from no video stream to video stream and we send a filler frame from the
    // last time we had a video stream and it's not the same as the current video stream.
    if (!result)
        this.lastVideoFrame = this.blackVideoFrame;

    return result;
  }

  startFillerFrameTimer() {
    if (this.fillerFrameInterval) return; // Don't start if already running
    
    this.fillerFrameInterval = setInterval(() => {
        try {
            const currentTime = performance.now();
            if (currentTime - this.lastVideoFrameTime >= 500 && this.mediaSendingEnabled) {                
                // Fix: Math.floor() the milliseconds before converting to BigInt
                const currentTimeMicros = BigInt(Math.floor(currentTime) * 1000);
                const frameToUse = this.currentVideoStreamIsActive() ? this.lastVideoFrame : this.blackVideoFrame;
                this.sendVideo(currentTimeMicros, '0', frameToUse.width, frameToUse.height, frameToUse.frameData);
            }
        } catch (error) {
            console.error('Error in black frame timer:', error);
        }
    }, 250);
  }

  stopFillerFrameTimer() {
    if (this.fillerFrameInterval) {
        clearInterval(this.fillerFrameInterval);
        this.fillerFrameInterval = null;
    }
  }
  */

  enableMediaSending() {
    this.mediaSendingEnabled = true;
    window.styleManager.start();
    //window.fullCaptureManager.start();

    // No longer need this because we're not using MediaStreamTrackProcessor's
    //this.startFillerFrameTimer();
  }

  async disableMediaSending() {
    window.styleManager.stop();
    //window.fullCaptureManager.stop();
    // Give the media recorder a bit of time to send the final data
    await new Promise(resolve => setTimeout(resolve, 2000));
    this.mediaSendingEnabled = false;

    // No longer need this because we're not using MediaStreamTrackProcessor's
    //this.stopFillerFrameTimer();
  }

  handleMessage(data) {
      const view = new DataView(data);
      const messageType = view.getInt32(0, true); // true for little-endian
      
      // Handle different message types
      switch (messageType) {
          case WebSocketClient.MESSAGE_TYPES.JSON:
              const jsonData = new TextDecoder().decode(new Uint8Array(data, 4));
              console.log('Received JSON message:', JSON.parse(jsonData));
              break;
          // Add future message type handlers here
          default:
              console.warn('Unknown message type:', messageType);
      }
  }
  
  sendJson(data) {
      if (this.ws.readyState !== WebSocket.OPEN) {
          console.error('WebSocket is not connected');
          return;
      }

      try {
          // Convert JSON to string then to Uint8Array
          const jsonString = JSON.stringify(data);
          const jsonBytes = new TextEncoder().encode(jsonString);
          
          // Create final message: type (4 bytes) + json data
          const message = new Uint8Array(4 + jsonBytes.length);
          
          // Set message type (1 for JSON)
          new DataView(message.buffer).setInt32(0, WebSocketClient.MESSAGE_TYPES.JSON, true);
          
          // Copy JSON data after type
          message.set(jsonBytes, 4);
          
          // Send the binary message
          this.ws.send(message.buffer);
      } catch (error) {
          console.error('Error sending WebSocket message:', error);
          console.error('Message data:', data);
      }
  }

  sendClosedCaptionUpdate(item) {
    if (!this.mediaSendingEnabled)
        return;

    this.sendJson({
        type: 'CaptionUpdate',
        caption: item
    });
  }

  sendEncodedMP4Chunk(encodedMP4Data) {
    if (this.ws.readyState !== WebSocket.OPEN) {
      console.error('WebSocket is not connected for video chunk send', this.ws.readyState);
      return;
    }

    if (!this.mediaSendingEnabled) {
      return;
    }

    try {
      // Create a header with just the message type (4 bytes)
      const headerBuffer = new ArrayBuffer(4);
      const headerView = new DataView(headerBuffer);
      headerView.setInt32(0, WebSocketClient.MESSAGE_TYPES.ENCODED_MP4_CHUNK, true);

      // Create a Blob that combines the header and the MP4 data
      const message = new Blob([headerBuffer, encodedMP4Data]);

      // Send the combined Blob directly
      this.ws.send(message);
    } catch (error) {
      console.error('Error sending WebSocket video chunk:', error);
    }
  }

  sendAudio(timestamp, streamId, audioData) {
      if (this.ws.readyState !== WebSocket.OPEN) {
          console.error('WebSocket is not connected for audio send', this.ws.readyState);
          return;
      }


      if (!this.mediaSendingEnabled) {
        return;
      }

      try {
          // Create final message: type (4 bytes) + timestamp (8 bytes) + audio data
          const message = new Uint8Array(4 + 8 + 4 + audioData.buffer.byteLength);
          const dataView = new DataView(message.buffer);
          
          // Set message type (3 for AUDIO)
          dataView.setInt32(0, WebSocketClient.MESSAGE_TYPES.AUDIO, true);
          
          // Set timestamp as BigInt64
          dataView.setBigInt64(4, BigInt(timestamp), true);

          // Set streamId length and bytes
          dataView.setInt32(12, streamId, true);

          // Copy audio data after type and timestamp
          message.set(new Uint8Array(audioData.buffer), 16);
          
          // Send the binary message
          this.ws.send(message.buffer);
      } catch (error) {
          console.error('Error sending WebSocket audio message:', error);
      }
  }

  sendVideo(timestamp, streamId, width, height, videoData) {
      if (this.ws.readyState !== WebSocket.OPEN) {
          console.error('WebSocket is not connected for video send', this.ws.readyState);
          return;
      }

      if (!this.mediaSendingEnabled) {
        return;
      }
      
      this.lastVideoFrameTime = performance.now();
      this.lastVideoFrame = {width, height, frameData: videoData};
      
      try {
          // Convert streamId to UTF-8 bytes
          const streamIdBytes = new TextEncoder().encode(streamId);
          
          // Create final message: type (4 bytes) + timestamp (8 bytes) + streamId length (4 bytes) + 
          // streamId bytes + width (4 bytes) + height (4 bytes) + video data
          const message = new Uint8Array(4 + 8 + 4 + streamIdBytes.length + 4 + 4 + videoData.buffer.byteLength);
          const dataView = new DataView(message.buffer);
          
          // Set message type (2 for VIDEO)
          dataView.setInt32(0, WebSocketClient.MESSAGE_TYPES.VIDEO, true);
          
          // Set timestamp as BigInt64
          dataView.setBigInt64(4, BigInt(timestamp), true);

          // Set streamId length and bytes
          dataView.setInt32(12, streamIdBytes.length, true);
          message.set(streamIdBytes, 16);

          // Set width and height
          const streamIdOffset = 16 + streamIdBytes.length;
          dataView.setInt32(streamIdOffset, width, true);
          dataView.setInt32(streamIdOffset + 4, height, true);

          // Copy video data after headers
          message.set(new Uint8Array(videoData.buffer), streamIdOffset + 8);
          
          // Send the binary message
          this.ws.send(message.buffer);
      } catch (error) {
          console.error('Error sending WebSocket video message:', error);
      }
  }
}

// Interceptors

class FetchInterceptor {
    constructor(responseCallback) {
        this.originalFetch = window.fetch;
        this.responseCallback = responseCallback;
        window.fetch = (...args) => this.interceptFetch(...args);
    }

    async interceptFetch(...args) {
        try {
            // Call the original fetch
            const response = await this.originalFetch.apply(window, args);
            
            // Clone the response since it can only be consumed once
            const clonedResponse = response.clone();
            
            // Call the callback with the cloned response
            await this.responseCallback(clonedResponse);
            
            // Return the original response to maintain normal flow
            return response;
        } catch (error) {
            console.error('Error in intercepted fetch:', error);
            throw error;
        }
    }
}
class RTCInterceptor {
    constructor(callbacks) {
        // Store the original RTCPeerConnection
        const originalRTCPeerConnection = window.RTCPeerConnection;
        
        // Store callbacks
        const onPeerConnectionCreate = callbacks.onPeerConnectionCreate || (() => {});
        const onDataChannelCreate = callbacks.onDataChannelCreate || (() => {});
        
        // Override the RTCPeerConnection constructor
        window.RTCPeerConnection = function(...args) {
            // Create instance using the original constructor
            const peerConnection = Reflect.construct(
                originalRTCPeerConnection, 
                args
            );
            
            // Notify about the creation
            onPeerConnectionCreate(peerConnection);
            
            // Override createDataChannel
            const originalCreateDataChannel = peerConnection.createDataChannel.bind(peerConnection);
            peerConnection.createDataChannel = (label, options) => {
                const dataChannel = originalCreateDataChannel(label, options);
                onDataChannelCreate(dataChannel, peerConnection);
                return dataChannel;
            };
            
            return peerConnection;
        };
    }
}

// Message type definitions
const messageTypes = [
      {
        name: 'CollectionEvent',
        fields: [
            { name: 'body', fieldNumber: 1, type: 'message', messageType: 'CollectionEventBody' }
        ]
    },
    {
        name: 'CollectionEventBody',
        fields: [
            { name: 'userInfoListWrapperAndChatWrapperWrapper', fieldNumber: 2, type: 'message', messageType: 'UserInfoListWrapperAndChatWrapperWrapper' }
        ]
    },
    {
        name: 'UserInfoListWrapperAndChatWrapperWrapper',
        fields: [
            { name: 'deviceInfoWrapper', fieldNumber: 3, type: 'message', messageType: 'DeviceInfoWrapper' },
            { name: 'userInfoListWrapperAndChatWrapper', fieldNumber: 13, type: 'message', messageType: 'UserInfoListWrapperAndChatWrapper' }
        ]
    },
    {
        name: 'UserInfoListWrapperAndChatWrapper',
        fields: [
            { name: 'userInfoListWrapper', fieldNumber: 1, type: 'message', messageType: 'UserInfoListWrapper' },
            { name: 'chatMessageWrapper', fieldNumber: 4, type: 'message', messageType: 'ChatMessageWrapper', repeated: true }
        ]
    },
    {
        name: 'DeviceInfoWrapper',
        fields: [
            { name: 'deviceOutputInfoList', fieldNumber: 2, type: 'message', messageType: 'DeviceOutputInfoList', repeated: true }
        ]
    },
    {
        name: 'DeviceOutputInfoList',
        fields: [
            { name: 'deviceOutputType', fieldNumber: 2, type: 'varint' }, // Speculating that 1 = audio, 2 = video
            { name: 'streamId', fieldNumber: 4, type: 'string' },
            { name: 'deviceId', fieldNumber: 6, type: 'string' },
            { name: 'deviceOutputStatus', fieldNumber: 10, type: 'message', messageType: 'DeviceOutputStatus' }
        ]
    },
    {
        name: 'DeviceOutputStatus',
        fields: [
            { name: 'disabled', fieldNumber: 1, type: 'varint' }
        ]
    },
    // Existing message types
    {
        name: 'UserInfoListResponse',
        fields: [
            { name: 'userInfoListWrapperWrapper', fieldNumber: 2, type: 'message', messageType: 'UserInfoListWrapperWrapper' }
        ]
    },
    {
        name: 'UserInfoListResponse',
        fields: [
            { name: 'userInfoListWrapperWrapper', fieldNumber: 2, type: 'message', messageType: 'UserInfoListWrapperWrapper' }
        ]
    },
    {
        name: 'UserInfoListWrapperWrapper',
        fields: [
            { name: 'userInfoListWrapper', fieldNumber: 2, type: 'message', messageType: 'UserInfoListWrapper' }
        ]
    },
    {
        name: 'UserEventInfo',
        fields: [
            { name: 'eventNumber', fieldNumber: 1, type: 'varint' } // sequence number for the event
        ]
    },
    {
        name: 'UserInfoListWrapper',
        fields: [
            { name: 'userEventInfo', fieldNumber: 1, type: 'message', messageType: 'UserEventInfo' },
            { name: 'userInfoList', fieldNumber: 2, type: 'message', messageType: 'UserInfoList', repeated: true }
        ]
    },
    {
        name: 'UserInfoList',
        fields: [
            { name: 'deviceId', fieldNumber: 1, type: 'string' },
            { name: 'fullName', fieldNumber: 2, type: 'string' },
            { name: 'profilePicture', fieldNumber: 3, type: 'string' },
            { name: 'status', fieldNumber: 4, type: 'varint' }, // in meeting = 1 vs not in meeting = 6. kicked out = 7?
            { name: 'displayName', fieldNumber: 29, type: 'string' },
            { name: 'parentDeviceId', fieldNumber: 21, type: 'string' } // if this is present, then this is a screenshare device. The parentDevice is the person that is sharing
        ]
    },
    {
        name: 'CaptionWrapper',
        fields: [
            { name: 'caption', fieldNumber: 1, type: 'message', messageType: 'Caption' }
        ]
    },
    {
        name: 'Caption',
        fields: [
            { name: 'deviceId', fieldNumber: 1, type: 'string' },
            { name: 'captionId', fieldNumber: 2, type: 'int64' },
            { name: 'version', fieldNumber: 3, type: 'int64' },
            { name: 'text', fieldNumber: 6, type: 'string' },
            { name: 'languageId', fieldNumber: 8, type: 'int64' }
        ]
    },
    {
        name: 'ChatMessageWrapper',
        fields: [
            { name: 'chatMessage', fieldNumber: 2, type: 'message', messageType: 'ChatMessage' }
        ]
    },
    {
        name: 'ChatMessage',
        fields: [
            { name: 'messageId', fieldNumber: 1, type: 'string' },
            { name: 'deviceId', fieldNumber: 2, type: 'string' },
            { name: 'timestamp', fieldNumber: 3, type: 'int64' },
            { name: 'chatMessageContent', fieldNumber: 5, type: 'message', messageType: 'ChatMessageContent' }
        ]
    },
    {
        name: 'ChatMessageContent',
        fields: [
            { name: 'text', fieldNumber: 1, type: 'string' }
        ]
    }
];

// Generic message decoder factory
function createMessageDecoder(messageType) {
    return function decode(reader, length) {
        if (!(reader instanceof protobuf.Reader)) {
            reader = protobuf.Reader.create(reader);
        }

        const end = length === undefined ? reader.len : reader.pos + length;
        const message = {};

        while (reader.pos < end) {
            const tag = reader.uint32();
            const fieldNumber = tag >>> 3;
            
            const field = messageType.fields.find(f => f.fieldNumber === fieldNumber);
            if (!field) {
                reader.skipType(tag & 7);
                continue;
            }

            let value;
            switch (field.type) {
                case 'string':
                    value = reader.string();
                    break;
                case 'int64':
                    value = reader.int64();
                    break;
                case 'varint':
                    value = reader.uint32();
                    break;
                case 'message':
                    value = messageDecoders[field.messageType](reader, reader.uint32());
                    break;
                default:
                    reader.skipType(tag & 7);
                    continue;
            }

            if (field.repeated) {
                if (!message[field.name]) {
                    message[field.name] = [];
                }
                message[field.name].push(value);
            } else {
                message[field.name] = value;
            }
        }

        return message;
    };
}

const ws = new WebSocketClient();
window.ws = ws;
const userManager = new UserManager(ws);
const captionManager = new CaptionManager(ws);
const videoTrackManager = new VideoTrackManager(ws);
const fullCaptureManager = new FullCaptureManager();
const styleManager = new StyleManager();

window.videoTrackManager = videoTrackManager;
window.userManager = userManager;
window.fullCaptureManager = fullCaptureManager;
window.styleManager = styleManager;
// Create decoders for all message types
const messageDecoders = {};
messageTypes.forEach(type => {
    messageDecoders[type.name] = createMessageDecoder(type);
});

function base64ToUint8Array(base64) {
    const binaryString = atob(base64);
    const bytes = new Uint8Array(binaryString.length);
    for (let i = 0; i < binaryString.length; i++) {
        bytes[i] = binaryString.charCodeAt(i);
    }
    return bytes;
}

const syncMeetingSpaceCollectionsUrl = "https://meet.google.com/$rpc/google.rtc.meetings.v1.MeetingSpaceService/SyncMeetingSpaceCollections";
const userMap = new Map();
new FetchInterceptor(async (response) => {
    if (response.url === syncMeetingSpaceCollectionsUrl) {
        const responseText = await response.text();
        const decodedData = base64ToUint8Array(responseText);
        const userInfoListResponse = messageDecoders['UserInfoListResponse'](decodedData);
        const userInfoList = userInfoListResponse.userInfoListWrapperWrapper?.userInfoListWrapper?.userInfoList || [];
        console.log('userInfoList', userInfoList);
        if (userInfoList.length > 0) {
            userManager.newUsersListSynced(userInfoList);
        }
    }
});

const handleCollectionEvent = (event) => {
  const decodedData = pako.inflate(new Uint8Array(event.data));
  //console.log(' handleCollectionEventdecodedData', decodedData);
  // Convert decoded data to base64
  const base64Data = btoa(String.fromCharCode.apply(null, decodedData));
  //console.log('Decoded collection event data (base64):', base64Data);

  const collectionEvent = messageDecoders['CollectionEvent'](decodedData);
  
  const deviceOutputInfoList = collectionEvent.body.userInfoListWrapperAndChatWrapperWrapper?.deviceInfoWrapper?.deviceOutputInfoList;
  if (deviceOutputInfoList) {
    userManager.updateDeviceOutputs(deviceOutputInfoList);
  }

  const chatMessageWrapper = collectionEvent.body.userInfoListWrapperAndChatWrapperWrapper?.userInfoListWrapperAndChatWrapper?.chatMessageWrapper;
  if (chatMessageWrapper) {
    console.log('chatMessageWrapper', chatMessageWrapper);
  }

  //console.log('deviceOutputInfoList', JSON.stringify(collectionEvent.body.userInfoListWrapperAndChatWrapperWrapper?.deviceInfoWrapper?.deviceOutputInfoList));
  //console.log('usermap', userMap.allUsersMap);
  //console.log('userInfoList And Event', collectionEvent.body.userInfoListWrapperAndChatWrapperWrapper.userInfoListWrapperAndChatWrapper.userInfoListWrapper);
  const userInfoList = collectionEvent.body.userInfoListWrapperAndChatWrapperWrapper.userInfoListWrapperAndChatWrapper.userInfoListWrapper?.userInfoList || [];
  console.log('userInfoList in collection event', userInfoList);
  // This event is triggered when a single user joins (or leaves) the meeting
  // generally this array only contains a single user
  // we can't tell whether the event is a join or leave event, so we'll assume it's a join
  // if it's a leave, then we'll pick it up from the periodic call to syncMeetingSpaceCollections
  // so there will be a lag of roughly a minute for leave events
  for (const user of userInfoList) {
    userManager.singleUserSynced(user);
  }
};

// the stream ID, not the track id in the TRACK appears in the payload of the protobuf message somewhere

const handleCaptionEvent = (event) => {
  const decodedData = new Uint8Array(event.data);
  const captionWrapper = messageDecoders['CaptionWrapper'](decodedData);
  const caption = captionWrapper.caption;
  captionManager.singleCaptionSynced(caption);
}

const handleMediaDirectorEvent = (event) => {
  console.log('handleMediaDirectorEvent', event);
  const decodedData = new Uint8Array(event.data);
  //console.log(' handleCollectionEventdecodedData', decodedData);
  // Convert decoded data to base64
  const base64Data = btoa(String.fromCharCode.apply(null, decodedData));
  console.log('Decoded media director event data (base64):', base64Data);
}

const handleVideoTrack = async (event) => {  
  try {
    // Create processor to get raw frames
    const processor = new MediaStreamTrackProcessor({ track: event.track });
    const generator = new MediaStreamTrackGenerator({ kind: 'video' });
    
    // Add track ended listener
    event.track.addEventListener('ended', () => {
        console.log('Video track ended:', event.track.id);
        videoTrackManager.deleteVideoTrack(event.track);
    });
    
    // Get readable stream of video frames
    const readable = processor.readable;
    const writable = generator.writable;

    const firstStreamId = event.streams[0]?.id;

    // Check if of the users who are in the meeting and screensharers
    // if any of them have an associated device output with the first stream ID of this video track
    const isScreenShare = userManager
        .getCurrentUsersInMeetingWhoAreScreenSharing()
        .some(user => firstStreamId && userManager.getDeviceOutput(user.deviceId, DEVICE_OUTPUT_TYPE.VIDEO).streamId === firstStreamId);
    if (firstStreamId) {
        videoTrackManager.upsertVideoTrack(event.track, firstStreamId, isScreenShare);
    }

    // Add frame rate control variables
    const targetFPS = isScreenShare ? 5 : 15;
    const frameInterval = 1000 / targetFPS; // milliseconds between frames
    let lastFrameTime = 0;

    const transformStream = new TransformStream({
        async transform(frame, controller) {
            if (!frame) {
                return;
            }

            try {
                // Check if controller is still active
                if (controller.desiredSize === null) {
                    frame.close();
                    return;
                }

                const currentTime = performance.now();
                
                if (firstStreamId && firstStreamId === videoTrackManager.getStreamIdToSendCached()) {
                    // Check if enough time has passed since the last frame
                    if (currentTime - lastFrameTime >= frameInterval) {
                        // Copy the frame to get access to raw data
                        const rawFrame = new VideoFrame(frame, {
                            format: 'I420'
                        });

                        // Get the raw data from the frame
                        const data = new Uint8Array(rawFrame.allocationSize());
                        rawFrame.copyTo(data);

                        /*
                        const currentFormat = {
                            width: frame.displayWidth,
                            height: frame.displayHeight,
                            dataSize: data.length,
                            format: rawFrame.format,
                            duration: frame.duration,
                            colorSpace: frame.colorSpace,
                            codedWidth: frame.codedWidth,
                            codedHeight: frame.codedHeight
                        };
                        */
                        // Get current time in microseconds (multiply milliseconds by 1000)
                        const currentTimeMicros = BigInt(Math.floor(currentTime * 1000));
                        ws.sendVideo(currentTimeMicros, firstStreamId, frame.displayWidth, frame.displayHeight, data);

                        rawFrame.close();
                        lastFrameTime = currentTime;
                    }
                }
                
                // Always enqueue the frame for the video element
                controller.enqueue(frame);
            } catch (error) {
                console.error('Error processing frame:', error);
                frame.close();
            }
        },
        flush() {
            console.log('Transform stream flush called');
        }
    });

    // Create an abort controller for cleanup
    const abortController = new AbortController();

    try {
        // Connect the streams
        await readable
            .pipeThrough(transformStream)
            .pipeTo(writable, {
                signal: abortController.signal
            })
            .catch(error => {
                if (error.name !== 'AbortError') {
                    console.error('Pipeline error:', error);
                }
            });
    } catch (error) {
        console.error('Stream pipeline error:', error);
        abortController.abort();
    }

  } catch (error) {
      console.error('Error setting up video interceptor:', error);
  }
};

const handleAudioTrack = async (event) => {
  let lastAudioFormat = null;  // Track last seen format
  
  try {
    // Create processor to get raw frames
    const processor = new MediaStreamTrackProcessor({ track: event.track });
    const generator = new MediaStreamTrackGenerator({ kind: 'audio' });
    
    // Get readable stream of audio frames
    const readable = processor.readable;
    const writable = generator.writable;

    const firstStreamId = event.streams[0]?.id;

    // Transform stream to intercept frames
    const transformStream = new TransformStream({
        async transform(frame, controller) {
            if (!frame) {
                return;
            }

            try {
                // Check if controller is still active
                if (controller.desiredSize === null) {
                    frame.close();
                    return;
                }

                // Copy the audio data
                const numChannels = frame.numberOfChannels;
                const numSamples = frame.numberOfFrames;
                const audioData = new Float32Array(numSamples);
                
                // Copy data from each channel
                // If multi-channel, average all channels together
                if (numChannels > 1) {
                    // Temporary buffer to hold each channel's data
                    const channelData = new Float32Array(numSamples);
                    
                    // Sum all channels
                    for (let channel = 0; channel < numChannels; channel++) {
                        frame.copyTo(channelData, { planeIndex: channel });
                        for (let i = 0; i < numSamples; i++) {
                            audioData[i] += channelData[i];
                        }
                    }
                    
                    // Average by dividing by number of channels
                    for (let i = 0; i < numSamples; i++) {
                        audioData[i] /= numChannels;
                    }
                } else {
                    // If already mono, just copy the data
                    frame.copyTo(audioData, { planeIndex: 0 });
                }

                // console.log('frame', frame)
                // console.log('audioData', audioData)

                // Check if audio format has changed
                const currentFormat = {
                    numberOfChannels: 1,
                    originalNumberOfChannels: frame.numberOfChannels,
                    numberOfFrames: frame.numberOfFrames,
                    sampleRate: frame.sampleRate,
                    format: frame.format,
                    duration: frame.duration
                };

                // If format is different from last seen format, send update
                if (!lastAudioFormat || 
                    JSON.stringify(currentFormat) !== JSON.stringify(lastAudioFormat)) {
                    lastAudioFormat = currentFormat;
                    ws.sendJson({
                        type: 'AudioFormatUpdate',
                        format: currentFormat
                    });
                }

                // If the audioData buffer is all zeros, then we don't want to send it
                // Removing this since we implemented 3 audio sources in gstreamer pipeline
                // if (audioData.every(value => value === 0)) {
                //    return;
                // }

                // Send audio data through websocket
                const currentTimeMicros = BigInt(Math.floor(performance.now() * 1000));
                ws.sendAudio(currentTimeMicros, firstStreamId, audioData);

                // Pass through the original frame
                controller.enqueue(frame);
            } catch (error) {
                console.error('Error processing frame:', error);
                frame.close();
            }
        },
        flush() {
            console.log('Transform stream flush called');
        }
    });

    // Create an abort controller for cleanup
    const abortController = new AbortController();

    try {
        // Connect the streams
        await readable
            .pipeThrough(transformStream)
            .pipeTo(writable, {
                signal: abortController.signal
            })
            .catch(error => {
                if (error.name !== 'AbortError') {
                    console.error('Pipeline error:', error);
                }
            });
    } catch (error) {
        console.error('Stream pipeline error:', error);
        abortController.abort();
    }

  } catch (error) {
      console.error('Error setting up audio interceptor:', error);
  }
};

new RTCInterceptor({
    onPeerConnectionCreate: (peerConnection) => {
        console.log('New RTCPeerConnection created:', peerConnection);
        peerConnection.addEventListener('datachannel', (event) => {
            console.log('datachannel', event);
            if (event.channel.label === "collections") {               
                event.channel.addEventListener("message", (messageEvent) => {
                    console.log('RAWcollectionsevent', messageEvent);
                    handleCollectionEvent(messageEvent);
                });
            }
        });

        peerConnection.addEventListener('track', (event) => {
            console.log('New track:', {
                trackId: event.track.id,
                trackKind: event.track.kind,
                streams: event.streams,
            });
            // We need to capture every audio track in the meeting,
            // but we don't need to do anything with the video tracks
            if (event.track.kind === 'audio') {
                window.styleManager.addAudioTrack(event.track);
            }
            if (event.track.kind === 'video') {
                window.styleManager.addVideoTrack(event);
            }
        });

        /*
        We are no longer setting up per-frame MediaStreamTrackProcessor's because it taxes the CPU too much
        For now, we are just using the MediaRecorderReceiver to record the video stream
        but we're keeping this code around for reference
        peerConnection.addEventListener('track', (event) => {
            // Log the track and its associated streams
            console.log('New track:', {
                trackId: event.track.id,
                streams: event.streams,
                streamIds: event.streams.map(stream => stream.id),
                // Get any msid information
                transceiver: event.transceiver,
                // Get the RTP parameters which might contain stream IDs
                rtpParameters: event.transceiver?.sender.getParameters()
            });
            if (event.track.kind === 'audio') {
                handleAudioTrack(event);
            }
            if (event.track.kind === 'video') {
                handleVideoTrack(event);
            }
        });
        */

        // Log the signaling state changes
        peerConnection.addEventListener('signalingstatechange', () => {
            console.log('Signaling State:', peerConnection.signalingState);
        });

        // Log the SDP being exchanged
        const originalSetLocalDescription = peerConnection.setLocalDescription;
        peerConnection.setLocalDescription = function(description) {
            console.log('Local SDP:', description);
            return originalSetLocalDescription.apply(this, arguments);
        };

        const originalSetRemoteDescription = peerConnection.setRemoteDescription;
        peerConnection.setRemoteDescription = function(description) {
            console.log('Remote SDP:', description);
            return originalSetRemoteDescription.apply(this, arguments);
        };

        // Log ICE candidates
        peerConnection.addEventListener('icecandidate', (event) => {
            if (event.candidate) {
                console.log('ICE Candidate:', event.candidate);
            }
        });
    },
    onDataChannelCreate: (dataChannel, peerConnection) => {
        console.log('New DataChannel created:', dataChannel);
        console.log('On PeerConnection:', peerConnection);
        console.log('Channel label:', dataChannel.label);

        //if (dataChannel.label === 'collections') {
          //  dataChannel.addEventListener("message", (event) => {
         //       console.log('collectionsevent', event)
        //    });
        //}


      if (dataChannel.label === 'media-director') {
        dataChannel.addEventListener("message", (mediaDirectorEvent) => {
            handleMediaDirectorEvent(mediaDirectorEvent);
        });
      }

       if (dataChannel.label === 'captions') {
            dataChannel.addEventListener("message", (captionEvent) => {
                handleCaptionEvent(captionEvent);
            });
        }
    }
});

function addClickRipple() {
    document.addEventListener('click', function(e) {
      const ripple = document.createElement('div');
      
      // Apply styles directly to the element
      ripple.style.position = 'fixed';
      ripple.style.borderRadius = '50%';
      ripple.style.width = '20px';
      ripple.style.height = '20px';
      ripple.style.marginLeft = '-10px';
      ripple.style.marginTop = '-10px';
      ripple.style.background = 'red';
      ripple.style.opacity = '0';
      ripple.style.pointerEvents = 'none';
      ripple.style.transform = 'scale(0)';
      ripple.style.transition = 'transform 0.3s, opacity 0.3s';
      ripple.style.zIndex = '9999999';
      
      ripple.style.left = e.pageX + 'px';
      ripple.style.top = e.pageY + 'px';
      document.body.appendChild(ripple);
  
      // Force reflow so CSS transition will play
      getComputedStyle(ripple).transform;
      
      // Animate
      ripple.style.transform = 'scale(3)';
      ripple.style.opacity = '0.7';
  
      // Remove after animation
      setTimeout(() => {
        ripple.remove();
      }, 300);
    }, true);
}

if (window.initialData.addClickRipple) {
    addClickRipple();
}

function clickLanguageOption(languageCode) {
    // Find the element with data-value attribute matching the language code
    const languageElement = document.querySelector(`li[data-value="${languageCode}"]`);

    // Check if the element exists
    if (languageElement) {
        // Click the element
        languageElement.click();
        return true;
    } else {
        return false;
    }
}