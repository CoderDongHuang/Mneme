const API_BASE = 'http://localhost:8080/api/v1';
const PYTHON_AGENT_URL = 'http://localhost:8000/api/v1';
const userId = 'test_user';
let sessionId = 'session_' + Date.now();

document.getElementById('send-btn').addEventListener('click', sendMessage);
document.getElementById('user-input').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') sendMessage();
});

async function sendMessage() {
    const input = document.getElementById('user-input');
    const sendBtn = document.getElementById('send-btn');
    const message = input.value.trim();
    if (!message) return;

    appendMessage('user', message);
    input.value = '';
    sendBtn.disabled = true;

    // 使用 SSE 流式响应
    const response = await fetch(`${PYTHON_AGENT_URL}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            user_id: userId,
            session_id: sessionId,
            message: message,
            knowledge_base_ids: []
        })
    });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let assistantDiv = appendMessage('assistant', '');
    let content = '';

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value);
        const lines = chunk.split('\n\n');

        for (const line of lines) {
            if (line.startsWith('data: ')) {
                const data = line.slice(6);
                if (data === '[DONE]') continue;
                content += data;
                assistantDiv.textContent = content;
            }
        }
    }

    sendBtn.disabled = false;
    input.focus();
}

function appendMessage(role, content) {
    const messages = document.getElementById('messages');
    const div = document.createElement('div');
    div.className = `message ${role}`;
    div.textContent = content;
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
    return div;
}
