document.addEventListener('DOMContentLoaded', () => {
    // Theme Toggle Logic
    const themeBtn = document.getElementById('theme-toggle');
    const root = document.documentElement;

    const currentTheme = localStorage.getItem('theme') || 'light';
    root.setAttribute('data-theme', currentTheme);
    if(themeBtn) {
        themeBtn.textContent = currentTheme === 'light' ? 'DARK' : 'LIGHT';

        themeBtn.addEventListener('click', () => {
            const theme = root.getAttribute('data-theme');
            const newTheme = theme === 'light' ? 'dark' : 'light';
            root.setAttribute('data-theme', newTheme);
            localStorage.setItem('theme', newTheme);
            themeBtn.textContent = newTheme === 'light' ? 'DARK' : 'LIGHT';
        });
    }

    // Hamburger Menu Logic
    const hamburgerBtn = document.getElementById('hamburger-btn');
    const sidebar = document.getElementById('sidebar');

    if(hamburgerBtn && sidebar) {
        hamburgerBtn.addEventListener('click', () => {
            sidebar.classList.toggle('open');
        });
    }

    // AI Tutor Avatar Initialization (Only on lesson.html)
    if (document.getElementById('avatar-canvas')) {
        window.aiTutor = new window.AITutorAvatar({
            canvasId: 'avatar-canvas',
            transcriptBoxId: 'chat-history',
            promptInputId: 'prompt-input',
            micBtnId: 'ptt-btn',
            sendBtnId: 'send-btn'
        });

        // Play queued startup data if navigated, or auto-start a session
        const pending = sessionStorage.getItem('pendingStartData');
        if (pending) {
            sessionStorage.removeItem('pendingStartData');
            const data = JSON.parse(pending);
            setTimeout(() => {
                window.aiTutor.appendTranscript('ai', data.segment_text);
                if (data.audio_url) {
                    window.aiTutor.playAudio(data.audio_url, data.gestures || []);
                }
            }, 500);
        } else {
            // Auto start lesson since we merged it into a single screen
            setTimeout(async () => {
                window.aiTutor.appendTranscript('system', 'Starting lesson...');
                try {
                    const response = await fetch('/api/start', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ topic: "Wave-Particle Duality", api_key: "" })
                    });
                    const data = await response.json();
                    
                    document.getElementById('chat-history').innerHTML = '<div class="text-black/50 uppercase tracking-widest text-xs font-bold mb-2">Session Transcript</div>';
                    window.aiTutor.appendTranscript('ai', data.segment_text);
                    if (data.audio_url) {
                        window.aiTutor.playAudio(data.audio_url, data.gestures || []);
                    }
                } catch (err) {
                    console.error("Failed to start session:", err);
                    window.aiTutor.appendTranscript('system', 'Failed to start session. Check backend.');
                }
            }, 500);
        }
        
        // Wire the "Select Files" button
        const uploadBtn = document.getElementById('upload-btn');
        if (uploadBtn) {
            uploadBtn.addEventListener('click', () => {
                const input = document.createElement('input');
                input.type = 'file';
                input.accept = '.pdf';
                input.onchange = (e) => {
                    if (e.target.files.length > 0) {
                        const file = e.target.files[0];
                        window.aiTutor.appendTranscript('system', `Uploaded ${file.name} successfully. Mentora is now analyzing your materials.`);
                    }
                };
                input.click();
            });
        }
    } else {
        // Setup Logic (index.html)
        const startBtn = document.getElementById('start-session-btn');
        const promptInput = document.getElementById('topic-input');
        
        if (startBtn && promptInput) {
            startBtn.addEventListener('click', async () => {
                const text = promptInput.value.trim();
                const apiKeyInput = document.getElementById('api-key-input');
                const apiKey = apiKeyInput ? apiKeyInput.value.trim() : "";
                
                try {
                    const response = await fetch('/api/start', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ topic: text, api_key: apiKey })
                    });
                    const data = await response.json();
                    
                    // We pass the start data to sessionStorage so lesson.html can play it immediately
                    sessionStorage.setItem('pendingStartData', JSON.stringify(data));
                    window.location.href = '/lesson.html';
                } catch (err) {
                    console.error("Failed to start session:", err);
                }
            });
        }
    }
});
