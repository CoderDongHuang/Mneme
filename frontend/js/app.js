const PYTHON_AGENT_URL = 'http://localhost:8000/api/v1';
const userId = 'test_user';
let sessionId = null;

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    loadSessions();
    setupNewChat();
});

document.getElementById('send-btn').addEventListener('click', sendMessage);
document.getElementById('user-input').addEventListener('keypress', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

// 自动调整输入框高度
document.getElementById('user-input').addEventListener('input', () => {
    const textarea = document.getElementById('user-input');
    textarea.style.height = 'auto';
    textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
});

// 加载历史对话列表
async function loadSessions() {
    try {
        const res = await fetch(`${PYTHON_AGENT_URL}/sessions?user_id=${userId}`);
        const data = await res.json();
        const sessionList = document.getElementById('session-list');
        
        if (data.sessions && data.sessions.length > 0) {
            sessionList.innerHTML = data.sessions.map(session => `
                <div class="session-item ${session.id === sessionId ? 'active' : ''}" data-id="${session.id}">
                    <div class="session-title">${session.title}</div>
                    <div class="session-meta">${session.message_count} 条消息</div>
                </div>
            `).join('');
            
            // 添加点击事件
            document.querySelectorAll('.session-item').forEach(item => {
                item.addEventListener('click', () => switchSession(item.dataset.id));
            });
        } else {
            sessionList.innerHTML = '<div style="color:#999;font-size:13px;">暂无历史对话</div>';
        }
    } catch (e) {
        document.getElementById('session-list').innerHTML = '<div style="color:#ff4d4f;font-size:13px;">加载失败</div>';
    }
}

// 新建对话
function setupNewChat() {
    document.getElementById('new-chat-btn').addEventListener('click', () => {
        sessionId = 'session_' + Date.now();
        document.getElementById('messages').innerHTML = '';
        loadSessions();
    });
}

// 切换对话
async function switchSession(id) {
    sessionId = id;
    document.getElementById('messages').innerHTML = '';
    
    try {
        const res = await fetch(`${PYTHON_AGENT_URL}/session/${id}`);
        const data = await res.json();
        
        if (data.messages) {
            data.messages.forEach(msg => {
                appendMessage(msg.role, msg.content);
            });
        }
    } catch (e) {
        console.error('加载对话失败:', e);
    }
    
    loadSessions();
}

// 发送消息
async function sendMessage() {
    const input = document.getElementById('user-input');
    const sendBtn = document.getElementById('send-btn');
    const message = input.value.trim();
    if (!message) return;

    // 如果没有会话，创建新的
    if (!sessionId) {
        sessionId = 'session_' + Date.now();
    }

    appendMessage('user', message);
    input.value = '';
    input.style.height = 'auto';
    sendBtn.disabled = true;

    const assistantDiv = appendMessage('assistant', '');

    try {
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
        
        // 刷新历史列表
        loadSessions();
    } catch (e) {
        assistantDiv.textContent = '请求失败，请检查服务是否运行';
    }

    sendBtn.disabled = false;
    input.focus();
}

function appendMessage(role, content) {
    const messages = document.getElementById('messages');
    const wrapper = document.createElement('div');
    wrapper.className = `message ${role}`;

    const label = document.createElement('div');
    label.className = 'label';
    label.textContent = role === 'user' ? '你' : '助手';

    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    bubble.textContent = content;

    wrapper.appendChild(label);
    wrapper.appendChild(bubble);
    messages.appendChild(wrapper);
    messages.scrollTop = messages.scrollHeight;
    return bubble;
}
