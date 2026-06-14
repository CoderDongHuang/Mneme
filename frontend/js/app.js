const API_BASE = MnemeConfig.baseUrl;
const userId = 'test_user';
let sessionId = null;

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    loadSessions();
    setupNewChat();
    setupUpload();
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
        const res = await fetch(`${API_BASE}/sessions?user_id=${userId}`);
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
        const res = await fetch(`${API_BASE}/session/${id}`);
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
        const response = await fetch(`${API_BASE}/chat/stream`, {
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
                    if (data.startsWith('[PENDING] ')) {
                        // 待确认记忆 — 展示确认卡片
                        const pendingJson = data.slice(10);
                        try {
                            const pendingMemories = JSON.parse(pendingJson);
                            showMemoryConfirmations(pendingMemories);
                        } catch (e) {
                            console.error('解析待确认记忆失败:', e);
                        }
                        continue;
                    }
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

// 文件上传
function setupUpload() {
    const uploadBtn = document.getElementById('upload-btn');
    const fileInput = document.getElementById('file-input');
    
    uploadBtn.addEventListener('click', () => {
        fileInput.click();
    });
    
    fileInput.addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        
        const formData = new FormData();
        formData.append('file', file);
        formData.append('user_id', userId);
        formData.append('kb_id', 'default_kb');
        
        appendMessage('user', `📎 上传文件: ${file.name}`);
        
        try {
            const response = await fetch(`${API_BASE}/knowledge/upload`, {
                method: 'POST',
                body: formData
            });
            
            const result = await response.json();
            appendMessage('assistant', `文件 "${file.name}" 上传成功，正在解析中...`);
        } catch (err) {
            appendMessage('assistant', `文件上传失败: ${err.message}`);
        }
        
        // 重置 input，允许重复上传同一文件
        fileInput.value = '';
    });
}

// ── 记忆确认 ──────────────────────────────────────────

function showMemoryConfirmations(pendingMemories) {
    if (!pendingMemories || pendingMemories.length === 0) return;

    const messages = document.getElementById('messages');
    const cardWrapper = document.createElement('div');
    cardWrapper.className = 'memory-confirm-card';

    const title = document.createElement('div');
    title.className = 'memory-confirm-title';
    title.textContent = `💡 我注意到了 ${pendingMemories.length} 条关于你的信息，要记住吗？`;

    cardWrapper.appendChild(title);

    for (const mem of pendingMemories) {
        const row = document.createElement('div');
        row.className = 'memory-confirm-row';

        const categoryLabel = {
            'preference': '偏好',
            'weak_point': '薄弱点',
            'progress': '进度'
        }[mem.category] || mem.category;

        const confidencePercent = Math.round((mem.confidence || 0.7) * 100);

        row.innerHTML = `
            <span class="memory-confirm-tag">${categoryLabel}</span>
            <span class="memory-confirm-content">${escapeHtml(mem.content)}</span>
            <span class="memory-confirm-confidence">${confidencePercent}%</span>
            <button class="memory-confirm-btn confirm" data-temp-id="${escapeHtml(mem.temp_id)}"
                data-category="${escapeHtml(mem.category)}"
                data-content="${escapeHtml(mem.content)}"
                data-topic="${escapeHtml(mem.topic || '')}">✓</button>
            <button class="memory-confirm-btn dismiss" data-temp-id="${escapeHtml(mem.temp_id)}">✗</button>
        `;
        cardWrapper.appendChild(row);
    }

    messages.appendChild(cardWrapper);
    messages.scrollTop = messages.scrollHeight;

    // 绑定确认/拒绝按钮事件
    cardWrapper.querySelectorAll('.memory-confirm-btn.confirm').forEach(btn => {
        btn.addEventListener('click', async () => {
            const { tempId, category, content, topic } = btn.dataset;
            try {
                await fetch(`${API_BASE}/memory/confirm`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        user_id: userId,
                        temp_id: tempId,
                        action: 'confirm',
                        category, content, topic
                    })
                });
            } catch (e) { console.error('记忆确认失败:', e); }
            btn.closest('.memory-confirm-row').remove();
            checkAllConfirmed(cardWrapper);
        });
    });

    cardWrapper.querySelectorAll('.memory-confirm-btn.dismiss').forEach(btn => {
        btn.addEventListener('click', async () => {
            const { tempId } = btn.dataset;
            try {
                await fetch(`${API_BASE}/memory/confirm`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        user_id: userId,
                        temp_id: tempId,
                        action: 'dismiss'
                    })
                });
            } catch (e) { console.error('记忆拒绝失败:', e); }
            btn.closest('.memory-confirm-row').remove();
            checkAllConfirmed(cardWrapper);
        });
    });
}

function checkAllConfirmed(cardWrapper) {
    // 所有条目处理完毕后移除卡片
    if (cardWrapper.querySelectorAll('.memory-confirm-row').length === 0) {
        cardWrapper.remove();
    }
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}
