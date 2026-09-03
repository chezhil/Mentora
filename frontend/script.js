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

    // Connect to Backend API for Chat
    const sendBtn = document.getElementById('send-btn');
    const promptInput = document.getElementById('prompt-input');
    const chatHistory = document.getElementById('chat-history');

    async function sendMessage() {
        if (!promptInput || !chatHistory) return;
        const text = promptInput.value.trim();
        if (!text) return;

        // Append User Message
        const userMsg = document.createElement('div');
        userMsg.className = 'message user';
        userMsg.innerHTML = `<strong>USR</strong> ${text}`;
        chatHistory.appendChild(userMsg);

        promptInput.value = '';
        chatHistory.scrollTop = chatHistory.scrollHeight;

        try {
            // Check if we are on the setup page starting a lesson
            if(window.location.pathname.includes('index.html') || window.location.pathname === '/') {
                const response = await fetch('/api/start', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ topic: text })
                });
                const data = await response.json();
                window.location.href = '/lesson.html';
                return;
            }

            // Normal lesson question
            const response = await fetch('/api/ask', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ question: text })
            });
            const data = await response.json();
            
            const aiMsg = document.createElement('div');
            aiMsg.className = 'message ai';
            aiMsg.innerHTML = `<strong>MENTORA</strong> ${data.reply || "ERROR: NO RESPONSE"}`;
            chatHistory.appendChild(aiMsg);
            chatHistory.scrollTop = chatHistory.scrollHeight;
        } catch (error) {
            const aiMsg = document.createElement('div');
            aiMsg.className = 'message system';
            aiMsg.innerHTML = `<strong>SYS</strong> Error connecting to backend: ${error.message}`;
            chatHistory.appendChild(aiMsg);
        }
    }

    if (sendBtn && promptInput) {
        sendBtn.addEventListener('click', sendMessage);
        promptInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });
    }
});
