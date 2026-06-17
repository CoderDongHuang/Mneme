// ═══════════════════════════════════════════════════════════════
// Mneme 学习助手 — 前端应用主模块
// ═══════════════════════════════════════════════════════════════

const API_BASE = MnemeConfig.baseUrl;
let userId = localStorage.getItem("mneme_user_id") || "";
let sessionId = null;
let abortController = null;      // 用于取消进行中的 SSE 请求
let currentKnowledgeBaseIds = [];

// ── 初始化 ──────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    checkConnection();
    setupLogin();
    setupNewChat();
    setupUpload();
    setupKeyboardShortcuts();
    setupSidebarToggle();
    setupThemeToggle();
    setupSessionTitleEdit();
});

document.getElementById("send-btn").addEventListener("click", sendMessage);
document.getElementById("user-input").addEventListener("keydown", handleInputKeydown);
document.getElementById("user-input").addEventListener("input", autoResizeTextarea);
document.getElementById("stop-btn").addEventListener("click", stopGeneration);

// ── 连接状态 ───────────────────────────────────────────────
async function checkConnection() {
    const dot = document.getElementById("connection-status");
    const text = document.getElementById("connection-text");
    try {
        const res = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(3000) });
        if (res.ok) {
            dot.className = "status-dot online";
            text.textContent = "在线";
            // 在线后再加载数据
            if (userId) { loadSessions(); loadKnowledgeBases(); loadMemories(); }
            return true;
        }
    } catch (e) { /* offline */ }
    dot.className = "status-dot offline";
    text.textContent = "离线";
    return false;
}

// ── 登录 ────────────────────────────────────────────────────
function setupLogin() {
    const overlay = document.getElementById("login-overlay");
    const usernameInput = document.getElementById("login-username");
    const passwordInput = document.getElementById("login-password");
    const loginBtn = document.getElementById("login-btn");
    const skipBtn = document.getElementById("login-skip");
    const errorEl = document.getElementById("login-error");

    // 已登录则跳过
    if (userId && localStorage.getItem("mneme_token")) {
        overlay.style.display = "none";
        loadSessions(); loadKnowledgeBases(); loadMemories();
        return;
    }
    // 开发模式自动填充
    if (MnemeConfig.mode === "dev") {
        usernameInput.value = localStorage.getItem("mneme_user_id") || "test_user";
    }

    const doLogin = async (user, pass) => {
        errorEl.textContent = "";
        // 生产模式调用 Java Gateway 登录
        if (MnemeConfig.authRequired && pass) {
            try {
                const res = await fetch(`${API_BASE}/auth/login`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ username: user, password: pass })
                });
                if (!res.ok) { errorEl.textContent = "登录失败，请检查用户名密码"; return false; }
                const data = await res.json();
                if (data.data && data.data.token) {
                    localStorage.setItem("mneme_token", data.data.token);
                }
            } catch (e) {
                errorEl.textContent = "无法连接到服务器"; return false;
            }
        }
        userId = user || "test_user";
        localStorage.setItem("mneme_user_id", userId);
        overlay.style.display = "none";
        loadSessions(); loadKnowledgeBases(); loadMemories();
        return true;
    };

    loginBtn.addEventListener("click", () => doLogin(usernameInput.value.trim(), passwordInput.value));
    skipBtn.addEventListener("click", () => doLogin("test_user", ""));
    passwordInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") doLogin(usernameInput.value.trim(), passwordInput.value);
    });
    usernameInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") passwordInput.focus();
    });
}

// ── 键盘快捷键 ─────────────────────────────────────────────
function setupKeyboardShortcuts() {
    document.addEventListener("keydown", (e) => {
        // Ctrl+K: 新建对话
        if (e.ctrlKey && e.key === "k") {
            e.preventDefault();
            document.getElementById("new-chat-btn").click();
        }
    });
}

function handleInputKeydown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    } else if (e.key === "Escape") {
        if (abortController) { stopGeneration(); }
        else { e.target.value = ""; autoResizeTextarea(); }
    }
}

function autoResizeTextarea() {
    const ta = document.getElementById("user-input");
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 120) + "px";
}

// ── 侧边栏 ──────────────────────────────────────────────────
function setupSidebarToggle() {
    document.getElementById("hamburger-btn").addEventListener("click", () => {
        document.getElementById("sidebar").classList.toggle("open");
    });
    // 点击主区域关闭侧边栏
    document.getElementById("main").addEventListener("click", () => {
        document.getElementById("sidebar").classList.remove("open");
    });
}

function setupThemeToggle() {
    document.getElementById("theme-toggle").addEventListener("click", () => {
        const html = document.documentElement;
        const current = html.getAttribute("data-theme");
        const next = current === "dark" ? "light" : "dark";
        html.setAttribute("data-theme", next);
        localStorage.setItem("mneme_theme", next);
        // 切换代码高亮主题
        const hlTheme = document.getElementById("hljs-theme");
        hlTheme.href = next === "dark"
            ? "https://cdn.jsdelivr.net/npm/highlight.js@11/styles/github-dark.min.css"
            : "https://cdn.jsdelivr.net/npm/highlight.js@11/styles/github.min.css";
    });
    // 恢复主题
    const saved = localStorage.getItem("mneme_theme");
    if (saved) document.documentElement.setAttribute("data-theme", saved);
}

document.getElementById("mode-toggle").addEventListener("click", () => {
    const next = MnemeConfig.mode === "dev" ? "prod" : "dev";
    MnemeConfig.setMode(next);
});
// 更新模式标签
(function updateModeLabel() {
    const lbl = document.getElementById("mode-label");
    if (lbl) lbl.textContent = MnemeConfig.mode;
})();

// ── 知识库选择器 ──────────────────────────────────────────
async function loadKnowledgeBases() {
    if (!userId) return;
    try {
        const res = await fetch(`${API_BASE}/knowledge/admin/collections?user_id=${userId}`);
        const data = await res.json();
        const selector = document.getElementById("kb-selector");

        // 保留"全部知识库"选项
        selector.innerHTML = `<label class="kb-chip active" data-kb-id="">
            <input type="checkbox" checked> 全部知识库
        </label>`;

        if (data && typeof data === "object") {
            for (const [name, info] of Object.entries(data)) {
                const kbId = info.kb_id || name.replace(`user_${userId}_kb_`, "");
                const chip = document.createElement("label");
                chip.className = "kb-chip";
                chip.dataset.kbId = kbId;
                chip.innerHTML = `<input type="checkbox"> ${escapeHtml(kbId)} (${info.chunk_count || 0})`;
                selector.appendChild(chip);
            }
        }

        // 绑定切换事件
        selector.querySelectorAll(".kb-chip").forEach(chip => {
            chip.addEventListener("click", () => {
                const isAll = chip.dataset.kbId === "";
                if (isAll) {
                    // 点击"全部"：取消其他选择
                    selector.querySelectorAll(".kb-chip").forEach(c => c.classList.remove("active"));
                    chip.classList.add("active");
                    currentKnowledgeBaseIds = [];
                } else {
                    // 取消"全部"
                    selector.querySelector('.kb-chip[data-kb-id=""]').classList.remove("active");
                    chip.classList.toggle("active");
                    currentKnowledgeBaseIds = [];
                    selector.querySelectorAll(".kb-chip.active:not([data-kb-id=''])").forEach(c => {
                        currentKnowledgeBaseIds.push(c.dataset.kbId);
                    });
                }
            });
        });
    } catch (e) {
        console.error("加载知识库失败:", e);
    }
}

// ── 会话管理 ───────────────────────────────────────────────
async function loadSessions() {
    if (!userId) return;
    const searchTerm = document.getElementById("session-search")?.value?.toLowerCase() || "";
    try {
        const res = await fetch(`${API_BASE}/sessions?user_id=${userId}`);
        const data = await res.json();
        const sessionList = document.getElementById("session-list");

        let sessions = data.sessions || [];
        if (searchTerm) {
            sessions = sessions.filter(s => s.title.toLowerCase().includes(searchTerm));
        }

        if (sessions.length > 0) {
            sessionList.innerHTML = sessions.map(session => `
                <div class="session-item ${session.id === sessionId ? 'active' : ''}" data-id="${session.id}">
                    <div class="session-title">${escapeHtml(session.title)}</div>
                    <div class="session-meta">${session.message_count} 条 · ${formatRelativeTime(session.last_updated)}</div>
                    <button class="session-delete-btn" data-id="${session.id}" title="删除">×</button>
                </div>
            `).join("");

            // 点击切换会话
            sessionList.querySelectorAll(".session-item").forEach(item => {
                item.addEventListener("click", (e) => {
                    if (e.target.classList.contains("session-delete-btn")) return;
                    switchSession(item.dataset.id);
                });
            });
            // 删除按钮
            sessionList.querySelectorAll(".session-delete-btn").forEach(btn => {
                btn.addEventListener("click", (e) => {
                    e.stopPropagation();
                    deleteSession(btn.dataset.id);
                });
            });
        } else {
            sessionList.innerHTML = '<div class="session-empty">暂无历史对话</div>';
        }
    } catch (e) {
        document.getElementById("session-list").innerHTML =
            '<div class="session-empty" style="color:#ff4d4f">加载失败 <button onclick="loadSessions()" class="link-btn">重试</button></div>';
    }
}

document.getElementById("session-search")?.addEventListener("input", debounce(loadSessions, 300));

async function deleteSession(id) {
    if (!confirm("确定删除此对话？")) return;
    try {
        await fetch(`${API_BASE}/session/${id}`, { method: "DELETE" });
    } catch (e) { /* session_store 无 delete 端点时静默 */ }
    if (sessionId === id) {
        sessionId = null;
        document.getElementById("messages").innerHTML = "";
        document.getElementById("session-title").textContent = "学习助手";
    }
    loadSessions();
}

function setupNewChat() {
    document.getElementById("new-chat-btn").addEventListener("click", () => {
        sessionId = "session_" + Date.now();
        document.getElementById("messages").innerHTML = "";
        document.getElementById("session-title").textContent = "新对话";
        loadSessions();
    });
}

async function switchSession(id) {
    sessionId = id;
    document.getElementById("messages").innerHTML = "";
    document.getElementById("session-title").textContent = "加载中...";
    try {
        const res = await fetch(`${API_BASE}/session/${id}`);
        const data = await res.json();
        if (data.messages) {
            data.messages.forEach(msg => appendMessage(msg.role, msg.content, msg.timestamp));
        }
        // 获取标题
        const sessions = document.querySelectorAll(".session-item");
        sessions.forEach(s => {
            if (s.dataset.id === id) {
                document.getElementById("session-title").textContent =
                    s.querySelector(".session-title").textContent;
            }
        });
    } catch (e) { console.error("加载对话失败:", e); }
    loadSessions();
}

// 双击编辑标题
function setupSessionTitleEdit() {
    const titleEl = document.getElementById("session-title");
    titleEl.addEventListener("dblclick", () => {
        if (!sessionId) return;
        const current = titleEl.textContent;
        const input = document.createElement("input");
        input.value = current;
        input.className = "title-edit-input";
        input.style.cssText = "font-size:16px;font-weight:600;border:1px solid #1890ff;border-radius:4px;padding:2px 8px;width:200px";
        titleEl.replaceWith(input);
        input.focus();
        input.select();
        const save = () => {
            const newTitle = input.value.trim() || current;
            titleEl.textContent = newTitle;
            input.replaceWith(titleEl);
            // 更新侧边栏
            document.querySelectorAll(".session-item").forEach(s => {
                if (s.dataset.id === sessionId) {
                    s.querySelector(".session-title").textContent = newTitle;
                }
            });
        };
        input.addEventListener("blur", save);
        input.addEventListener("keydown", (e) => { if (e.key === "Enter") save(); });
    });
}

// ── 记忆管理 ───────────────────────────────────────────────
async function loadMemories() {
    if (!userId) return;
    try {
        const res = await fetch(`${API_BASE}/memory/read`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ user_id: userId, memory_types: ["preference", "weak_point"] })
        });
        const data = await res.json();
        const prefsEl = document.getElementById("memory-preferences");
        const wpsEl = document.getElementById("memory-weakpoints");

        const prefs = data.preferences || [];
        const wps = data.weak_points || [];

        prefsEl.innerHTML = prefs.length > 0
            ? prefs.map(p => `<div class="memory-item">${escapeHtml(p.content || p.topic || "")}</div>`).join("")
            : "—";

        wpsEl.innerHTML = wps.length > 0
            ? wps.map(w => `<div class="memory-item">${escapeHtml(w.topic || w.content || "")} <span class="memory-importance">${Math.round((w.importance || 0.5) * 100)}%</span></div>`).join("")
            : "—";
    } catch (e) { console.error("加载记忆失败:", e); }
}

document.getElementById("refresh-memory-btn")?.addEventListener("click", loadMemories);

// ── 文件上传 ───────────────────────────────────────────────
function setupUpload() {
    const uploadBtn = document.getElementById("upload-btn");
    const fileInput = document.getElementById("file-input");
    const progressBar = document.getElementById("upload-progress");
    const progressFill = progressBar.querySelector(".progress-fill");
    const progressText = document.getElementById("upload-progress-text");

    uploadBtn.addEventListener("click", () => fileInput.click());

    fileInput.addEventListener("change", () => {
        const file = fileInput.files[0];
        if (!file) return;

        // 检查大小 (50MB)
        if (file.size > 50 * 1024 * 1024) {
            appendMessage("assistant", "文件过大，最大支持 50MB");
            fileInput.value = "";
            return;
        }

        const formData = new FormData();
        formData.append("file", file);
        formData.append("user_id", userId);
        formData.append("kb_id", "default_kb");

        appendMessage("user", `📎 上传文件: ${file.name}`);

        // 显示进度条
        progressBar.classList.remove("hidden");
        progressFill.style.width = "0%";
        progressText.textContent = "上传中...";

        const xhr = new XMLHttpRequest();
        xhr.open("POST", `${API_BASE}/knowledge/upload`);

        xhr.upload.addEventListener("progress", (e) => {
            if (e.lengthComputable) {
                const pct = Math.round((e.loaded / e.total) * 100);
                progressFill.style.width = pct + "%";
                progressText.textContent = `上传中 ${pct}%`;
            }
        });

        xhr.addEventListener("load", () => {
            progressFill.style.width = "100%";
            progressText.textContent = "解析中...";
            if (xhr.status === 200) {
                appendMessage("assistant", `✅ "${file.name}" 上传成功，正在解析入库...`);
                // 刷新知识库列表
                setTimeout(loadKnowledgeBases, 3000);
            } else {
                appendMessage("assistant", `❌ 上传失败: ${xhr.status}`);
            }
            setTimeout(() => progressBar.classList.add("hidden"), 2000);
        });

        xhr.addEventListener("error", () => {
            progressText.textContent = "上传失败";
            appendMessage("assistant", "❌ 文件上传失败，请检查网络");
            setTimeout(() => progressBar.classList.add("hidden"), 3000);
        });

        xhr.send(formData);
        fileInput.value = "";
    });
}

// ── 消息发送与接收 ─────────────────────────────────────────
async function sendMessage() {
    const input = document.getElementById("user-input");
    const sendBtn = document.getElementById("send-btn");
    const stopBtn = document.getElementById("stop-btn");
    const message = input.value.trim();
    if (!message) return;

    if (!sessionId) sessionId = "session_" + Date.now();

    appendMessage("user", message);
    input.value = "";
    input.style.height = "auto";
    sendBtn.disabled = true;
    stopBtn.classList.remove("hidden");

    // 添加加载动画
    const loadingDiv = appendLoadingIndicator();

    // 取消之前的请求
    if (abortController) abortController.abort();
    abortController = new AbortController();

    try {
        const response = await fetch(`${API_BASE}/chat/stream`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                user_id: userId,
                session_id: sessionId,
                message: message,
                knowledge_base_ids: currentKnowledgeBaseIds
            }),
            signal: abortController.signal
        });

        // 移除加载动画，准备接收回复
        loadingDiv.remove();
        const assistantBubble = appendMessage("assistant", "");

        // ── 健壮的 SSE 行缓冲解析 ──
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let content = "";
        let lineBuffer = "";

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value, { stream: true });
            lineBuffer += chunk;

            // 按行解析（兼容 \r\n 和 \n）
            while (true) {
                const lfIdx = lineBuffer.indexOf("\n");
                if (lfIdx === -1) break;

                let line = lineBuffer.slice(0, lfIdx).replace(/\r$/, "");
                lineBuffer = lineBuffer.slice(lfIdx + 1);

                if (!line.startsWith("data: ")) continue;
                const data = line.slice(6);

                // ── 结构化信号分发 ──
                if (data === "[DONE]") continue;
                if (data.startsWith("[ERROR]")) {
                    const errMsg = data.slice(8);
                    assistantBubble.innerHTML = renderMarkdown(`⚠️ 生成失败：${escapeHtml(errMsg)}`);
                    continue;
                }
                if (data.startsWith("[PENDING]")) {
                    try {
                        const pending = JSON.parse(data.slice(10));
                        showMemoryConfirmations(pending);
                    } catch (e) { console.error("解析待确认记忆失败:", e); }
                    continue;
                }

                content += data;
                // 使用 Markdown 渲染
                assistantBubble.innerHTML = renderMarkdown(content);
                // 滚动到底部
                document.getElementById("messages").scrollTop =
                    document.getElementById("messages").scrollHeight;
            }
        }

        // 添加时间戳
        const timestamp = document.createElement("div");
        timestamp.className = "message-time";
        timestamp.textContent = new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
        assistantBubble.parentElement.appendChild(timestamp);

        // 添加反馈按钮
        addFeedbackButtons(assistantBubble.parentElement);

        // 添加复制按钮
        addCopyButton(assistantBubble, content);

    } catch (e) {
        loadingDiv.remove();
        if (e.name === "AbortError") {
            appendMessage("assistant", "⏹ 已停止生成");
        } else {
            const errorBubble = appendMessage("assistant",
                `❌ 请求失败 <button class="link-btn" onclick="sendMessage()">重试</button>`);
        }
    } finally {
        abortController = null;
        sendBtn.disabled = false;
        stopBtn.classList.add("hidden");
        input.focus();
        loadSessions();
        // 延迟刷新记忆
        setTimeout(loadMemories, 2000);
    }
}

function stopGeneration() {
    if (abortController) {
        abortController.abort();
        abortController = null;
    }
}

// ── Markdown 渲染 ──────────────────────────────────────────
function renderMarkdown(text) {
    if (!text) return "";
    try {
        // 配置 marked
        if (typeof marked !== "undefined") {
            marked.setOptions?.({ breaks: true, gfm: true });
            const html = marked.parse(text);
            return html;
        }
    } catch (e) { /* fall through to plain text */ }
    return escapeHtml(text).replace(/\n/g, "<br>");
}

// ── 辅助 UI 函数 ───────────────────────────────────────────
function appendMessage(role, content, timestamp) {
    const messages = document.getElementById("messages");
    const wrapper = document.createElement("div");
    wrapper.className = `message ${role}`;

    const label = document.createElement("div");
    label.className = "label";
    label.textContent = role === "user" ? "你" : "助手";

    const bubble = document.createElement("div");
    bubble.className = "bubble";
    if (role === "assistant" && content) {
        bubble.innerHTML = renderMarkdown(content);
    } else {
        bubble.textContent = content;
    }

    wrapper.appendChild(label);
    wrapper.appendChild(bubble);

    if (timestamp) {
        const time = document.createElement("div");
        time.className = "message-time";
        time.textContent = formatRelativeTime(timestamp);
        wrapper.appendChild(time);
    }

    messages.appendChild(wrapper);
    messages.scrollTop = messages.scrollHeight;
    return bubble;
}

function appendLoadingIndicator() {
    const messages = document.getElementById("messages");
    const wrapper = document.createElement("div");
    wrapper.className = "message assistant";
    const label = document.createElement("div");
    label.className = "label";
    label.textContent = "助手";
    const bubble = document.createElement("div");
    bubble.className = "bubble typing-indicator";
    bubble.innerHTML = "<span></span><span></span><span></span>";
    wrapper.appendChild(label);
    wrapper.appendChild(bubble);
    messages.appendChild(wrapper);
    messages.scrollTop = messages.scrollHeight;
    return wrapper;
}

function addCopyButton(bubble, content) {
    // 避免重复添加
    if (bubble.parentElement.querySelector(".copy-btn")) return;

    const btn = document.createElement("button");
    btn.className = "copy-btn";
    btn.textContent = "📋";
    btn.title = "复制";
    btn.addEventListener("click", () => {
        navigator.clipboard.writeText(content).then(() => {
            btn.textContent = "✓";
            setTimeout(() => { btn.textContent = "📋"; }, 1500);
        });
    });
    bubble.parentElement.appendChild(btn);
}

function addFeedbackButtons(wrapper) {
    if (wrapper.querySelector(".feedback-btn")) return;

    const container = document.createElement("div");
    container.className = "feedback-container";

    const upBtn = document.createElement("button");
    upBtn.className = "feedback-btn";
    upBtn.textContent = "👍";
    upBtn.title = "有帮助";
    upBtn.addEventListener("click", () => {
        upBtn.classList.toggle("active");
        wrapper.querySelector(".feedback-btn.down")?.classList.remove("active");
    });

    const downBtn = document.createElement("button");
    downBtn.className = "feedback-btn down";
    downBtn.textContent = "👎";
    downBtn.title = "无帮助";
    downBtn.addEventListener("click", () => {
        downBtn.classList.toggle("active");
        wrapper.querySelector(".feedback-btn:not(.down)")?.classList.remove("active");
    });

    container.appendChild(upBtn);
    container.appendChild(downBtn);
    wrapper.appendChild(container);
}

// ── 记忆确认卡片 ──────────────────────────────────────────
function showMemoryConfirmations(pendingMemories) {
    if (!pendingMemories || pendingMemories.length === 0) return;

    const messages = document.getElementById("messages");
    const cardWrapper = document.createElement("div");
    cardWrapper.className = "memory-confirm-card";

    const title = document.createElement("div");
    title.className = "memory-confirm-title";
    title.textContent = `💡 我注意到 ${pendingMemories.length} 条关于你的信息，要记住吗？`;

    cardWrapper.appendChild(title);

    for (const mem of pendingMemories) {
        const row = document.createElement("div");
        row.className = "memory-confirm-row";
        const categoryLabel = { preference: "偏好", weak_point: "薄弱点", progress: "进度" }[mem.category] || mem.category;
        const confidencePercent = Math.round((mem.confidence || 0.7) * 100);

        row.innerHTML = `
            <span class="memory-confirm-tag">${categoryLabel}</span>
            <span class="memory-confirm-content">${escapeHtml(mem.content)}</span>
            <span class="memory-confirm-confidence">${confidencePercent}%</span>
            <button class="memory-confirm-btn confirm" data-temp-id="${escapeHtml(mem.temp_id)}"
                data-category="${escapeHtml(mem.category)}"
                data-content="${escapeHtml(mem.content)}"
                data-topic="${escapeHtml(mem.topic || "")}">✓</button>
            <button class="memory-confirm-btn dismiss" data-temp-id="${escapeHtml(mem.temp_id)}">✗</button>
        `;
        cardWrapper.appendChild(row);
    }

    // 渐入动画
    cardWrapper.style.opacity = "0";
    cardWrapper.style.transition = "opacity 0.3s";
    messages.appendChild(cardWrapper);
    requestAnimationFrame(() => { cardWrapper.style.opacity = "1"; });
    messages.scrollTop = messages.scrollHeight;

    // 绑定确认/拒绝
    const handleConfirm = async (btn, action) => {
        const { tempId, category, content, topic } = btn.dataset;
        try {
            await fetch(`${API_BASE}/memory/confirm`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    user_id: userId, temp_id: tempId, action,
                    category: action === "confirm" ? category : "",
                    content: action === "confirm" ? content : "",
                    topic: action === "confirm" ? (topic || "") : ""
                })
            });
        } catch (e) { console.error("记忆确认失败:", e); }

        // 渐隐动画
        const row = btn.closest(".memory-confirm-row");
        row.style.opacity = "0";
        row.style.height = row.offsetHeight + "px";
        row.style.transition = "opacity 0.3s, height 0.3s";
        requestAnimationFrame(() => { row.style.opacity = "0"; row.style.height = "0"; });
        setTimeout(() => {
            row.remove();
            if (cardWrapper.querySelectorAll(".memory-confirm-row").length === 0) {
                cardWrapper.style.opacity = "0";
                setTimeout(() => cardWrapper.remove(), 300);
            }
        }, 300);
    };

    cardWrapper.querySelectorAll(".memory-confirm-btn.confirm").forEach(btn => {
        btn.addEventListener("click", () => handleConfirm(btn, "confirm"));
    });
    cardWrapper.querySelectorAll(".memory-confirm-btn.dismiss").forEach(btn => {
        btn.addEventListener("click", () => handleConfirm(btn, "dismiss"));
    });
}

// ── 工具函数 ──────────────────────────────────────────────
function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str || "";
    return div.innerHTML;
}

function formatRelativeTime(timestamp) {
    if (!timestamp) return "";
    try {
        const date = new Date(timestamp);
        const now = new Date();
        const diffMs = now - date;
        const diffMin = Math.floor(diffMs / 60000);
        if (diffMin < 1) return "刚刚";
        if (diffMin < 60) return `${diffMin} 分钟前`;
        const diffHour = Math.floor(diffMin / 60);
        if (diffHour < 24) return `${diffHour} 小时前`;
        const diffDay = Math.floor(diffHour / 24);
        if (diffDay < 7) return `${diffDay} 天前`;
        return date.toLocaleDateString("zh-CN");
    } catch (e) { return ""; }
}

function debounce(fn, delay) {
    let timer;
    return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), delay); };
}
