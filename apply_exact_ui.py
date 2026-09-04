from bs4 import BeautifulSoup

with open('frontend/superdesign_chat.html', 'r', encoding='utf-8') as f:
    soup = BeautifulSoup(f.read(), 'html.parser')

# Clean preview scripts
for script in soup.find_all('script'):
    if not script.get('src') and 'tailwind' not in script.text and 'window.addEventListener' in script.text:
        script.extract()

# 1. Avatar Container
avatar_icon = soup.find('iconify-icon', icon='ph:student-bold')
if avatar_icon:
    # Add the canvas
    canvas = soup.new_tag('canvas', id='avatar-canvas', **{'class': 'w-full h-full block absolute inset-0 z-10 opacity-90'})
    avatar_icon.parent.insert(0, canvas)

# 2. Chat Transcript Container
chat_history = None
for div in soup.find_all('div'):
    if 'overflow-y-auto' in div.get('class', []) and 'p-6' in div.get('class', []):
        chat_history = div
        break

if chat_history:
    chat_history['id'] = 'chat-history'
    chat_history.clear() # clear dummy messages

# 3. Inputs & Buttons
input_field = soup.find('input', placeholder='Ask Mentora a follow-up question...')
if input_field:
    input_field['id'] = 'prompt-input'

send_btn = soup.find('iconify-icon', icon='ph:paper-plane-right-bold')
if send_btn and send_btn.parent.name == 'button':
    send_btn.parent['id'] = 'send-btn'

mic_btn = soup.find('iconify-icon', icon='ph:microphone-bold')
if mic_btn and mic_btn.parent.name == 'button':
    mic_btn.parent['id'] = 'ptt-btn'

# Append required scripts
body = soup.find('body')
if body:
    scripts_html = """
    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
    <script src="/AITutorAvatar.js"></script>
    <script src="/script.js"></script>
    """
    body.append(BeautifulSoup(scripts_html, 'html.parser'))

with open('frontend/index.html', 'w', encoding='utf-8') as f:
    f.write(str(soup))
