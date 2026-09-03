document.addEventListener('DOMContentLoaded', () => {
    // Theme Toggle Logic
    const themeBtn = document.getElementById('theme-toggle');
    const root = document.documentElement;

    // Check local storage for theme
    const currentTheme = localStorage.getItem('theme') || 'light';
    root.setAttribute('data-theme', currentTheme);
    if(themeBtn) {
        themeBtn.textContent = currentTheme === 'light' ? 'DARK MODE' : 'LIGHT MODE';

        themeBtn.addEventListener('click', () => {
            const theme = root.getAttribute('data-theme');
            const newTheme = theme === 'light' ? 'dark' : 'light';
            root.setAttribute('data-theme', newTheme);
            localStorage.setItem('theme', newTheme);
            themeBtn.textContent = newTheme === 'light' ? 'DARK MODE' : 'LIGHT MODE';
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

    // Chat Interface Logic (Only applicable on Active Lesson page)
    const sendBtn = document.getElementById('send-btn');
    const promptInput = document.getElementById('prompt-input');
    const chatHistory = document.getElementById('chat-history');

    function sendMessage() {
        if (!promptInput || !chatHistory) return;
        const text = promptInput.value.trim();
        if (!text) return;

        // Append User Message
        const userMsg = document.createElement('div');
        userMsg.className = 'message user';
        userMsg.innerHTML = `<strong>USR:</strong> ${text}`;
        chatHistory.appendChild(userMsg);

        promptInput.value = '';
        chatHistory.scrollTop = chatHistory.scrollHeight;

        // Simulate AI Response
        setTimeout(() => {
            const aiMsg = document.createElement('div');
            aiMsg.className = 'message ai';
            aiMsg.innerHTML = `<strong>MENTORA:</strong> YOU SAID "${text}". AS A DEMO, I CANNOT PROCESS THIS.`;
            chatHistory.appendChild(aiMsg);
            chatHistory.scrollTop = chatHistory.scrollHeight;
        }, 1000);
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
