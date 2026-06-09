const PYTHON_AGENT_URL = 'http://localhost:8000/api/v1';
const userId = 'test_user';
let sessionId = 'session_' + Date.now();
let kbIds = [];

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    loadKnowledgeBases();
    setupFileUpload();
    setupAutoResize();
});

document.getElementById('send-btn').addEventListener('click', sendMessage);
document.getElementById('user-input').addEventListener('keypress', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

// 自动调整输入框高度
function setupAutoResize() {
    const textarea = document.getElementById('user-input');
    textarea.addEventListener('input', () => {
        textarea.style.height = 'auto';
        textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
    });
}

// 加载知识库
async function loadKnowledgeBases() {
    try {
        const res = await fetch(`${PYTHON_AGENT_URL}/knowledge/list`);
        const data = await res.json();
        const kbList = document.getElementById('kb-list');
        if (data.knowledge_bases && data.knowledge_bases.length > 0) {
            kbList.innerHTML = data.knowledge_bases.map(kb => `
                <div class="kb-item">
                    <span>${kb.name}</span>
                    <span class="count">${kb.document_count || 0} 文档</span>
                </div>
            `).join('');
            kbIds = data.knowledge_bases.map(kb => kb.id);
        } else {
            kbList.innerHTML = '<div style="color:#999;font-size:13px;">暂无知识库</div>';
        }
    } catch (e) {
        document.getElementById('kb-list').innerHTML = '<div style="color:#ff4d4f;font-size:13px;">加载失败</div>';
    }
}

// 文件上传
function setupFileUpload() {
    const fileInput = document.getElementById('file-input');
    const uploadArea = document.getElementById('upload-area');

    fileInput.addEventListener('change', async (e) => {
        const files = Array.from(e.target.files);
        for (const file of files) {
            await uploadFile(file);
        }
        fileInput.value = '';
    });

    // 拖拽上传
    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.style.borderColor = '#1890ff';
    });

    uploadArea.addEventListener('dragleave', () => {
        uploadArea.style.borderColor = '#d9d9d9';
    });

    uploadArea.addEventListener('drop', async (e) => {
        e.preventDefault();
        uploadArea.style.borderColor = '#d9d9d9';
        const files = Array.from(e.dataTransfer.files);
        for (const file of files) {
            await uploadFile(file);
        }
    });
}

async function uploadFile(file) {
    const status = document.getElementById('upload-status');
    const fileList = document.getElementById('file-list');

    // 添加到文件列表
    const fileItem = document.createElement('div');
    fileItem.className = 'file-item';
    fileItem.innerHTML = `<span>${file.name}</span><span class="status parsing">解析中...</span>`;
    fileList.prepend(fileItem);

    status.className = 'parsing';
    status.textContent = `正在上传 ${file.name}...`;

    try {
        const formData = new FormData();
        formData.append('file', file);

        const res = await fetch(`${PYTHON_AGENT_URL}/knowledge/ingest`, {
            method: 'POST',
            body: formData
        });

        if (res.ok) {
            const data = await res.json();
            fileItem.querySelector('.status').className = 'status done';
            fileItem.querySelector('.status').textContent = '已入库';
            status.className = 'success';
            status.textContent = `${file.name} 上传成功`;
            loadKnowledgeBases();
        } else {
            throw new Error('上传失败');
        }
    } catch (e) {
        fileItem.querySelector('.status').className = 'status';
        fileItem.querySelector('.status').style.color = '#ff4d4f';
        fileItem.querySelector('.status').textContent = '失败';
        status.className = 'error';
        status.textContent = `${file.name} 上传失败`;
    }

    setTimeout(() => { status.textContent = ''; }, 3000);
}

// 发送消息
async function sendMessage() {
    const input = document.getElementById('user-input');
    const sendBtn = document.getElementById('send-btn');
    const message = input.value.trim();
    if (!message) return;

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
                knowledge_base_ids: kbIds
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
