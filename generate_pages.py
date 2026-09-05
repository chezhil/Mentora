import os

pages = {
    "index.html": {
        "title": "SETUP LESSON",
        "content": """
                <div class="panel">
                    <h2 class="panel-title">CONFIGURE LESSON</h2>
                    <div class="panel-box">
                        <p>Upload a document (PDF/TXT) or enter a topic to begin personalized learning.</p>
                        <input type="text" id="topic-input" class="brutal-input" placeholder="ENTER TOPIC (e.g. Electricity)">
                        
                        <p style="margin-top: 20px; font-weight: bold;">Study Material (Optional):</p>
                        <input type="file" id="doc-upload" class="brutal-input" style="padding: 10px; cursor: pointer;">
                        
                        <p style="margin-top: 20px; font-weight: bold;">API Configuration:</p>
                        <input type="password" id="api-key-input" class="brutal-input" placeholder="ENTER GROQ API KEY">
                        
                        <button id="start-session-btn" class="brutal-btn action-btn" style="margin-top: 20px;">START SESSION</button>
                    </div>
                </div>
        """
    },
    "lesson.html": {
        "title": "ACTIVE LESSON",
        "content": """
                <div class="panel chat-interface">
                    <div class="lesson-layout">
                        <div class="video-container">
                            <div class="video-placeholder">AVATAR FEED [OFFLINE]</div>
                            <div class="visual-placeholder">DIAGRAM / EQUATION VIEWER</div>
                        </div>
                        <div class="chat-history" id="chat-history">
                            <div class="message system">
                                <strong>SYS</strong> TEACHING SEGMENT 1: VOLTAGE & CURRENT.
                            </div>
                            <div class="message ai">
                                <strong>MENTORA</strong> Voltage is the push that moves the charge, like pressure in a hose. Does that make sense?
                            </div>
                        </div>
                    </div>

                    <div class="input-area">
                        <textarea id="prompt-input" placeholder="ASK A FOLLOW-UP QUESTION..."></textarea>
                        <button id="send-btn" class="action-btn">SEND</button>
                    </div>
                </div>
        """
    },
    "quiz.html": {
        "title": "FINAL QUIZ",
        "content": """
                <div class="panel">
                    <h2 class="panel-title">FINAL ASSESSMENT</h2>
                    <div class="panel-box">
                        <p><strong>Q1:</strong> If resistance increases, what happens to current?</p>
                        <textarea class="brutal-input" placeholder="ENTER ANSWER..." style="height: 100px; resize: none;"></textarea>
                        <button class="brutal-btn action-btn" style="margin-top: 20px;">SUBMIT QUIZ</button>
                    </div>
                </div>
        """
    },
    "progress.html": {
        "title": "PROGRESS & ANALYTICS",
        "content": """
                <div class="panel">
                    <h2 class="panel-title">PROGRESS & ANALYTICS</h2>
                    <div class="panel-box">
                        <div class="widget">
                            <div class="widget-title">AVERAGE SCORE</div>
                            <div class="widget-data">87.5%</div>
                        </div>
                        <div class="widget" style="margin-top: 20px;">
                            <div class="widget-title">LEARNING PATH</div>
                            <p style="margin-top: 10px; line-height: 1.8;">
                            1. Electricity Foundation <br> 
                            2. Series & Parallel Circuits <br> 
                            3. Electromagnetism</p>
                        </div>
                    </div>
                </div>
        """
    },
    "report.html": {
        "title": "LESSON REPORT",
        "content": """
                <div class="panel">
                    <h2 class="panel-title">LESSON REPORT</h2>
                    <div class="panel-box">
                        <h3>SCORE: 92%</h3>
                        <br>
                        <p><strong>STRONG AREAS:</strong> Current, Voltage</p>
                        <br>
                        <p><strong>MISCONCEPTIONS:</strong> Believes current and resistance are directly proportional.</p>
                        <button class="brutal-btn action-btn" style="margin-top: 20px;">WATCH FULL LESSON VIDEO</button>
                    </div>
                </div>
        """
    }
}

template = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MENTORA - {title}</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <div class="app-container">
        <!-- Header -->
        <header class="header">
            <div class="header-left">
                <button id="hamburger-btn" class="hamburger">
                    <span class="bar"></span>
                    <span class="bar"></span>
                    <span class="bar"></span>
                </button>
                <div class="logo">MENTORA</div>
            </div>
            <div class="header-right">
                <div class="user-profile">USR // NAMAN</div>
                <button id="theme-toggle" class="theme-btn">DARK</button>
            </div>
        </header>

        <div class="main-content">
            <!-- Sidebar -->
            <aside class="sidebar" id="sidebar">
                <nav class="nav-menu">
                    <div class="nav-header">SYSTEM MODULES</div>
                    <a href="index.html" class="nav-btn {active_index}">SETUP LESSON</a>
                    <a href="lesson.html" class="nav-btn {active_lesson}">ACTIVE LESSON</a>
                    <a href="quiz.html" class="nav-btn {active_quiz}">FINAL QUIZ</a>
                    <a href="progress.html" class="nav-btn {active_progress}">PROGRESS & ANALYTICS</a>
                    <a href="report.html" class="nav-btn {active_report}">LESSON REPORT</a>
                </nav>
            </aside>

            <!-- Main Features Area -->
            <main class="content-area">
{content}
            </main>
        </div>
    </div>
    <script src="script.js"></script>
</body>
</html>
"""

for filename, data in pages.items():
    html_content = template.format(
        title=data["title"],
        content=data["content"],
        active_index="active" if filename == "index.html" else "",
        active_lesson="active" if filename == "lesson.html" else "",
        active_quiz="active" if filename == "quiz.html" else "",
        active_progress="active" if filename == "progress.html" else "",
        active_report="active" if filename == "report.html" else ""
    )
    # Output to the new frontend folder
    with open(os.path.join("frontend", filename), "w", encoding="utf-8") as f:
        f.write(html_content)
