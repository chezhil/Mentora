class AITutorAvatar {
    constructor(config) {
        this.config = config;
        this.chatHistory = document.getElementById(config.transcriptBoxId);
        this.promptInput = document.getElementById(config.promptInputId);
        this.micBtn = document.getElementById(config.micBtnId);
        this.sendBtn = document.getElementById(config.sendBtnId);

        // State
        this.isListening = false;
        this.audioCtx = null;
        this.analyser = null;
        this.targetMouthScale = 1;
        
        // Gesture State
        this.currentGesture = null;
        this.gestureTimer = 0;
        this.activeGestures = [];

        this.init3D();
        this.initSTT();
        this.bindEvents();
    }

    // --------------------------------------------------------
    // 1. 3D Canvas & Model (Procedural Placeholder)
    // --------------------------------------------------------
    init3D() {
        this.canvas = document.getElementById(this.config.canvasId);
        const parent = this.canvas.parentElement;

        this.scene = new THREE.Scene();
        this.scene.background = new THREE.Color(0x09090b); // Academic dark mode bg

        this.camera = new THREE.PerspectiveCamera(45, parent.clientWidth / parent.clientHeight, 0.1, 100);
        this.camera.position.z = 5;
        this.camera.position.y = 1;

        this.renderer = new THREE.WebGLRenderer({ canvas: this.canvas, antialias: true });
        this.renderer.setSize(parent.clientWidth, parent.clientHeight);
        this.renderer.setPixelRatio(window.devicePixelRatio);

        // Lights
        const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
        this.scene.add(ambientLight);
        const dirLight = new THREE.DirectionalLight(0xffffff, 0.8);
        dirLight.position.set(5, 5, 5);
        this.scene.add(dirLight);

        // Procedural Avatar
        this.avatarGroup = new THREE.Group();
        this.scene.add(this.avatarGroup);

        // Head
        const headGeo = new THREE.BoxGeometry(1.5, 1.5, 1.5);
        const headMat = new THREE.MeshStandardMaterial({ color: 0x52525b }); // Zinc 600
        this.head = new THREE.Mesh(headGeo, headMat);
        this.head.position.y = 1.5;
        this.avatarGroup.add(this.head);

        // Eyes
        const eyeGeo = new THREE.BoxGeometry(0.2, 0.2, 0.1);
        const eyeMat = new THREE.MeshStandardMaterial({ color: 0x27272a }); // Zinc 800
        const leftEye = new THREE.Mesh(eyeGeo, eyeMat);
        leftEye.position.set(-0.4, 1.7, 0.76);
        const rightEye = new THREE.Mesh(eyeGeo, eyeMat);
        rightEye.position.set(0.4, 1.7, 0.76);
        this.avatarGroup.add(leftEye);
        this.avatarGroup.add(rightEye);

        // Mouth (Jaw bone equivalent)
        const mouthGeo = new THREE.BoxGeometry(0.8, 0.1, 0.1);
        const mouthMat = new THREE.MeshStandardMaterial({ color: 0x09090b });
        this.mouth = new THREE.Mesh(mouthGeo, mouthMat);
        this.mouth.position.set(0, 1.1, 0.76);
        this.avatarGroup.add(this.mouth);
        
        // Body
        const bodyGeo = new THREE.CylinderGeometry(0.8, 0.8, 2, 16);
        const bodyMat = new THREE.MeshStandardMaterial({ color: 0x3f3f46 }); // Zinc 700
        this.body = new THREE.Mesh(bodyGeo, bodyMat);
        this.body.position.y = -0.5;
        this.avatarGroup.add(this.body);

        window.addEventListener('resize', () => this.onResize());
        setTimeout(() => this.onResize(), 100);

        this.animate();
    }

    onResize() {
        if (!this.canvasContainer) return;
        this.camera.aspect = this.canvasContainer.clientWidth / this.canvasContainer.clientHeight;
        this.camera.updateProjectionMatrix();
        this.renderer.setSize(this.canvasContainer.clientWidth, this.canvasContainer.clientHeight);
    }

    animate() {
        requestAnimationFrame(() => this.animate());
        this.updateLipSync();
        this.updateGestures();
        this.renderer.render(this.scene, this.camera);
    }

    // --------------------------------------------------------
    // 2. UI Overlay (STT & Input)
    // --------------------------------------------------------
    initSTT() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (SpeechRecognition) {
            this.recognition = new SpeechRecognition();
            this.recognition.continuous = false;
            this.recognition.interimResults = false;
            
            this.recognition.onstart = () => {
                this.isListening = true;
                this.micBtn.style.backgroundColor = 'var(--text-primary)';
                this.micBtn.style.color = 'var(--bg-color)';
                this.micBtn.textContent = '🎙️ LSTN';
            };
            
            this.recognition.onresult = (event) => {
                const transcript = event.results[0][0].transcript;
                this.promptInput.value = transcript;
                this.submitQuery(transcript);
            };
            
            this.recognition.onend = () => {
                this.isListening = false;
                this.micBtn.style.backgroundColor = '';
                this.micBtn.style.color = '';
                this.micBtn.textContent = '🎤 PTT';
            };
        } else {
            this.micBtn.style.display = 'none'; // Not supported
        }
    }

    bindEvents() {
        if (this.micBtn && this.recognition) {
            // Toggle recording on click
            this.micBtn.addEventListener('click', () => {
                if (this.isListening) {
                    this.recognition.stop();
                } else {
                    this.recognition.start();
                }
            });
        }

        if (this.sendBtn && this.promptInput) {
            this.sendBtn.addEventListener('click', () => this.submitQuery());
            this.promptInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    this.submitQuery();
                }
            });
        }
    }

    appendTranscript(role, text) {
        if (!this.chatHistory) return;
        const msg = document.createElement('div');
        msg.className = `message ${role}`;
        
        const roleLabel = role === 'user' ? 'USR' : role === 'ai' ? 'MENTORA' : 'SYS';
        msg.innerHTML = `<strong>${roleLabel}</strong> ${text}`;
        
        this.chatHistory.appendChild(msg);
        this.chatHistory.scrollTop = this.chatHistory.scrollHeight;
    }

    // --------------------------------------------------------
    // 3. API Integration
    // --------------------------------------------------------
    async submitQuery(overrideText = null) {
        const text = overrideText !== null ? overrideText : this.promptInput.value.trim();
        if (!text) return;

        this.appendTranscript('user', text);
        this.promptInput.value = '';

        try {
            const response = await fetch('/api/ask', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ question: text })
            });
            const data = await response.json();
            
            if (data.error) throw new Error(data.error);

            this.appendTranscript('ai', data.reply);
            
            // Step 4 & 5 Trigger
            if (data.audio_url) {
                this.playAudio(data.audio_url, data.gestures || []);
            } else if (data.gestures && data.gestures.length > 0) {
                // Fallback if TTS fails
                this.triggerGesture(data.gestures[0].type); 
            }
            
        } catch (error) {
            this.appendTranscript('system', `Error connecting to backend: ${error.message}`);
        }
    }

    // --------------------------------------------------------
    // 4. Audio & Lip-Sync
    // --------------------------------------------------------
    playAudio(audioUrl, gestureTimeline) {
        if (!this.audioCtx) {
            this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        }
        
        this.audioEl = new Audio(audioUrl);
        this.audioEl.crossOrigin = "anonymous";
        
        const source = this.audioCtx.createMediaElementSource(this.audioEl);
        this.analyser = this.audioCtx.createAnalyser();
        this.analyser.fftSize = 256;
        this.dataArray = new Uint8Array(this.analyser.frequencyBinCount);
        
        source.connect(this.analyser);
        this.analyser.connect(this.audioCtx.destination);
        
        this.activeGestures = [...gestureTimeline];
        this.audioEl.play();
    }

    updateLipSync() {
        if (!this.mouth) return;
        
        // Default idle scale
        let target = 1;
        
        if (this.audioEl && !this.audioEl.paused && !this.audioEl.ended && this.analyser) {
            this.analyser.getByteFrequencyData(this.dataArray);
            
            let sum = 0;
            for (let i = 0; i < this.dataArray.length; i++) {
                sum += this.dataArray[i];
            }
            let average = sum / this.dataArray.length;
            let volume = average / 255.0; // 0.0 to 1.0
            
            target = 1.0 + (volume * 8.0);
            if (target > 6.0) target = 6.0;

            // Step 5 trigger: Synchronize gestures based on audio playback time
            if (this.activeGestures.length > 0) {
                const estCharIndex = this.audioEl.currentTime * 15; // 15 chars/sec heuristic
                if (estCharIndex >= this.activeGestures[0].index) {
                    const g = this.activeGestures.shift();
                    this.triggerGesture(g.type);
                }
            }
        }
        
        // Smoothly interpolate mouth scale
        const currentScale = this.mouth.scale.y;
        this.mouth.scale.y = currentScale + (target - currentScale) * 0.3;
    }

    // --------------------------------------------------------
    // 5. Gesture Synchronization
    // --------------------------------------------------------
    triggerGesture(gestureName) {
        console.log(`[AITutorAvatar] Triggering gesture: ${gestureName}`);
        this.currentGesture = gestureName;
        this.gestureTimer = 0;
    }

    updateGestures() {
        if (!this.currentGesture) return;
        
        this.gestureTimer += 0.05;
        const t = this.gestureTimer;
        
        // Blend skeletal/mesh morphs procedurally based on tags
        if (this.currentGesture === 'nod') {
            this.head.rotation.x = Math.sin(t * 5) * 0.2; 
            if (t > 2) this.clearGesture();
        } 
        else if (this.currentGesture === 'shake') {
            this.head.rotation.y = Math.sin(t * 6) * 0.3; 
            if (t > 2) this.clearGesture();
        }
        else if (this.currentGesture === 'point_board') {
            this.avatarGroup.rotation.y = Math.sin(t * 2) * 0.3; 
            if (t > 3) this.clearGesture();
        }
        else if (this.currentGesture === 'smile') {
            this.mouth.scale.x = 1 + Math.sin(t * 3) * 0.5; // Widen mouth
            if (t > 2) this.clearGesture();
        }
    }

    clearGesture() {
        this.currentGesture = null;
        this.gestureTimer = 0;
        
        // Smoothly reset rotations - in a full rig, we'd use AnimationMixer
        this.head.rotation.set(0, 0, 0);
        this.avatarGroup.rotation.set(0, 0, 0);
        this.mouth.scale.x = 1;
    }
}

// Export to global scope
window.AITutorAvatar = AITutorAvatar;
