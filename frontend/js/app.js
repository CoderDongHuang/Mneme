/* ═════════════════════════════════════════════
   Mneme — App
   ═════════════════════════════════════════════ */

const API = MnemeConfig.baseUrl;
let uid = '';
let sid = null;
let ac = null;
let kbIds = [];
const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);

// ═══════ Init ═══════
document.addEventListener('DOMContentLoaded', () => {
  if (MnemeConfig.mode === 'dev') {
    uid = localStorage.getItem('mneme_user_id') || 'test_user';
    localStorage.setItem('mneme_user_id', uid);
    showApp(); return;
  }
  if (localStorage.getItem('mneme_token')) {
    uid = localStorage.getItem('mneme_user_id') || '';
    showApp(); return;
  }
  setupAuth();
});
(() => { const t = localStorage.getItem('mneme_theme'); if (t) document.documentElement.setAttribute('data-theme', t); })();

// ═══════ Auth ═══════
function setupAuth() {
  $$('.auth-tab').forEach(t => t.onclick = () => {
    $$('.auth-tab').forEach(x => x.classList.remove('active'));
    t.classList.add('active');
    $('#login-form').classList.toggle('hidden', t.dataset.tab !== 'login');
    $('#register-form').classList.toggle('hidden', t.dataset.tab !== 'register');
  });

  $('#login-form').onsubmit = async e => {
    e.preventDefault();
    const u = $('#login-user').value.trim(), p = $('#login-pass').value;
    const err = $('#login-error'); err.textContent = '';
    if (!u || !p) { err.textContent = '请填写用户名和密码'; return; }
    try {
      const r = await fetch(API+'/auth/login', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({username:u,password:p}) });
      if (!r.ok) { err.textContent = '用户名或密码错误'; return; }
      const d = await r.json(), token = d.data?.token || d.token;
      if (token) { localStorage.setItem('mneme_token',token); localStorage.setItem('mneme_user_id',u); uid=u; showApp(); }
      else err.textContent = '服务器异常';
    } catch { err.textContent = '无法连接服务器'; }
  };

  $('#register-form').onsubmit = async e => {
    e.preventDefault();
    const u = $('#reg-user').value.trim(), p = $('#reg-pass').value, p2 = $('#reg-pass2').value;
    const err = $('#register-error'); err.textContent = '';
    if (u.length<3) { err.textContent='用户名至少3个字符'; return; }
    if (p.length<6) { err.textContent='密码至少6个字符'; return; }
    if (p!==p2) { err.textContent='两次密码不一致'; return; }
    try {
      const r = await fetch(API+'/auth/register', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({username:u,password:p}) });
      if (!r.ok) { err.textContent = (await r.json().catch(()=>({}))).message||'注册失败'; return; }
      err.style.color='#22c55e'; err.textContent='注册成功！请登录';
      setTimeout(()=>$$('.auth-tab')[0].click(), 1000);
    } catch { err.textContent='无法连接服务器'; }
  };

  $('#auth-skip').onclick = () => { uid='test_user'; localStorage.setItem('mneme_user_id',uid); showApp(); };
}

// ═══════ App ═══════
function showApp() {
  $('#auth-overlay').classList.add('hidden');
  $('#app').classList.remove('hidden');
  $('#new-chat-btn').onclick = newChat;
  $('#send-btn').onclick = sendMsg;
  $('#stop-btn').onclick = stopGen;
  $('#user-input').onkeydown = onKey;
  $('#user-input').oninput = onInput;
  $('#menu-btn').onclick = () => $('#sidebar').classList.toggle('open');
  $('#theme-toggle').onclick = toggleTheme;
  $('#session-search').oninput = debounce(loadSessions,300);
  setupUpload();
  checkHealth();
  loadSessions();
  loadKBs();
  loadMem();
}

// ═══════ Health ═══════
async function checkHealth() {
  try {
    const r = await fetch(API+'/health',{signal:AbortSignal.timeout(3000)});
    $('#conn-dot').className = r.ok ? 'conn-dot on' : 'conn-dot off';
  } catch { $('#conn-dot').className='conn-dot off'; }
}

// ═══════ Sessions ═══════
async function loadSessions() {
  if (!uid) return;
  const q = ($('#session-search')?.value||'').toLowerCase();
  try {
    const r = await fetch(API+'/sessions?user_id='+uid), d = await r.json();
    let ss = d.sessions||[];
    if (q) ss = ss.filter(s => s.title.toLowerCase().includes(q));
    const el = $('#session-list');
    if (!ss.length) { el.innerHTML='<div style="color:var(--c-muted);font-size:12px;padding:6px">暂无对话</div>'; return; }
    el.innerHTML = ss.map(s => '<div class="session-item'+(s.id===sid?' active':'')+'" data-id="'+s.id+'"><span class="session-item-title">'+esc(s.title)+'</span><button class="session-item-del" data-id="'+s.id+'">&times;</button></div>').join('');
    el.querySelectorAll('.session-item').forEach(it => it.onclick = e => { if (e.target.classList.contains('session-item-del')) return; switchSession(it.dataset.id); });
    el.querySelectorAll('.session-item-del').forEach(b => b.onclick = e => { e.stopPropagation(); delSession(b.dataset.id); });
  } catch { $('#session-list').innerHTML='<div style="color:var(--c-danger);font-size:12px;padding:6px">加载失败</div>'; }
}

async function switchSession(id) { sid=id; $('#messages').innerHTML=''; try { const r=await fetch(API+'/session/'+id); const d=await r.json(); if(d.messages)d.messages.forEach(m=>addMsg(m.role,m.content,m.timestamp)); } catch{} loadSessions(); }
async function delSession(id) { if (!confirm('删除此对话？')) return; try{await fetch(API+'/session/'+id,{method:'DELETE'});}catch{} if(sid===id){sid=null;showEmpty();} loadSessions(); }
function newChat() { sid='session_'+Date.now(); showEmpty(); loadSessions(); }
function showEmpty() { $('#messages').innerHTML='<div class="empty-state"><h1>Mneme</h1><p>上传课件、提问、复习——我会记住你的学习轨迹</p></div>'; }

// ═══════ KB ═══════
async function loadKBs() {
  if (!uid) return;
  try {
    const r = await fetch(API+'/knowledge/admin/collections?user_id='+uid), d = await r.json();
    const el = $('#kb-list');
    el.innerHTML = '<label class="kb-chip active" data-kb=""><input type="checkbox" checked>全部知识库</label>';
    if (d && typeof d === 'object') for (const [name,info] of Object.entries(d)) { const kid = info.kb_id || name.replace('user_'+uid+'_kb_',''); el.innerHTML += '<label class="kb-chip" data-kb="'+esc(kid)+'"><input type="checkbox">'+esc(kid)+' ('+(info.chunk_count||0)+')</label>'; }
    el.querySelectorAll('.kb-chip').forEach(ch => ch.onclick = () => {
      const k = ch.dataset.kb;
      if (k==='') { el.querySelectorAll('.kb-chip').forEach(c=>c.classList.remove('active')); ch.classList.add('active'); kbIds=[]; }
      else { el.querySelector('.kb-chip[data-kb=""]').classList.remove('active'); ch.classList.toggle('active'); kbIds=[...el.querySelectorAll('.kb-chip.active:not([data-kb=""]))'].map(c=>c.dataset.kb); }
    });
  } catch {}
}

// ═══════ Memory ═══════
async function loadMem() {
  if (!uid) return;
  try {
    const r = await fetch(API+'/memory/read',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:uid,memory_types:['preference','weak_point','progress']})});
    const d = await r.json();
    const prefs = (d.preferences||[]).map(p=>p.content||p.topic||'').filter(Boolean);
    const wps = (d.weak_points||[]).map(w=>w.topic||w.content||'').filter(Boolean);
    const prog = d.progress?.topic||'';
    let parts = []; if (prefs.length) parts.push('偏好:'+prefs.length); if (wps.length) parts.push('薄弱点:'+wps.length); if (prog) parts.push('进度:'+prog);
    $('#memory-brief').textContent = parts.length ? parts.join(' · ') : '暂无记忆数据';
  } catch {}
}

// ═══════ Upload ═══════
function setupUpload() {
  const fi = $('#file-input'), us = $('#upload-status'), uf = us.querySelector('.upload-bar-fill'), ut = us.querySelector('.upload-text');
  $('#upload-btn').onclick = () => fi.click();
  fi.onchange = () => {
    const f = fi.files[0]; if (!f) return;
    if (f.size > 50*1024*1024) { addMsg('ai','文件过大，最大50MB'); fi.value=''; return; }
    const fd = new FormData(); fd.append('file',f); fd.append('user_id',uid); fd.append('kb_id','default_kb');
    addMsg('user','📎 上传: '+f.name);
    us.classList.remove('hidden'); uf.style.width='0%'; ut.textContent='上传中...';
    const x = new XMLHttpRequest(); x.open('POST',API+'/knowledge/upload');
    x.upload.onprogress = e => { if(e.lengthComputable){ const pct=Math.round(e.loaded/e.total*100); uf.style.width=pct+'%'; ut.textContent='上传中 '+pct+'%'; } };
    x.onload = () => { if(x.status===200){ const resp=JSON.parse(x.responseText); addMsg('ai','✅ "'+f.name+'" 上传成功，解析中...'); pollTask(resp.task_id,uf,ut,us); } else { addMsg('ai','❌ 上传失败: '+x.status); setTimeout(()=>us.classList.add('hidden'),2000); } };
    x.onerror = () => { addMsg('ai','❌ 上传失败'); setTimeout(()=>us.classList.add('hidden'),2000); };
    x.send(fd); fi.value='';
  };
}
async function pollTask(tid, uf, ut, us) {
  try {
    const r = await fetch(API+'/knowledge/task/'+tid), t = await r.json();
    if (t.status==='done') { uf.style.width='100%'; ut.textContent='完成'; setTimeout(()=>us.classList.add('hidden'),2000); loadKBs(); }
    else if (t.status==='failed') { ut.textContent='失败'; addMsg('ai','❌ 解析失败: '+(t.error||'')); setTimeout(()=>us.classList.add('hidden'),3000); }
    else setTimeout(()=>pollTask(tid,uf,ut,us),2000);
  } catch { setTimeout(()=>pollTask(tid,uf,ut,us),3000); }
}

// ═══════ Chat ═══════
async function sendMsg() {
  const inp = $('#user-input'), msg = inp.value.trim();
  if (!msg) return;
  if (!sid) sid = 'session_'+Date.now();
  addMsg('user', msg);
  inp.value=''; inp.style.height='auto'; $('#send-btn').disabled=true;
  $('#stop-btn').classList.remove('hidden');
  const empty = $('.empty-state'); if (empty) empty.remove();
  const typing = addTyping();
  if (ac) ac.abort(); ac = new AbortController();

  try {
    const r = await fetch(API+'/chat/stream', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({user_id:uid,session_id:sid,message:msg,knowledge_base_ids:kbIds}), signal:ac.signal });
    typing.remove();
    if (!r.ok) { addMsg('ai','❌ 服务器错误 '+r.status); return; }

    const row = mkMsgRow('ai'), bubble = row.querySelector('.msg-bubble');
    const reader = r.body.getReader(), dec = new TextDecoder();
    let content='', buf='';
    while (true) {
      const {done,value} = await reader.read();
      if (done) break;
      buf += dec.decode(value,{stream:true});
      while (true) {
        const idx = buf.indexOf('\n'); if (idx===-1) break;
        let line = buf.slice(0,idx).replace(/\r$/,''); buf = buf.slice(idx+1);
        if (!line.startsWith('data: ')) continue;
        const data = line.slice(6);
        if (data==='[DONE]') continue;
        if (data.startsWith('[ERROR]')) { bubble.innerHTML = md('⚠️ '+esc(data.slice(8))); continue; }
        if (data.startsWith('[PENDING]')) { try{showMemCard(JSON.parse(data.slice(10)));}catch{} continue; }
        content += data;
        bubble.innerHTML = md(content);
        $('#messages').scrollTop = $('#messages').scrollHeight;
      }
    }
    addCopyBtn(row);
    loadSessions(); setTimeout(loadMem,2000);
  } catch(e) {
    typing?.remove();
    if (e.name==='AbortError') addMsg('ai','⏹ 已停止');
    else if (e.message?.includes('fetch')) addMsg('ai','❌ 无法连接后端，请确认 python main.py 已启动');
    else addMsg('ai','❌ '+(e.message||'').substring(0,100));
  } finally { ac=null; $('#send-btn').disabled=false; $('#stop-btn').classList.add('hidden'); inp.focus(); }
}
function stopGen() { if(ac){ac.abort();ac=null;} }

// ═══════ Messages ═══════
function addMsg(role, content, ts) {
  const row = mkMsgRow(role);
  const b = row.querySelector('.msg-bubble');
  if (role==='ai' && content) b.innerHTML = md(content); else b.textContent = content||'';
  if (ts) { const t = document.createElement('div'); t.className='msg-time'; t.textContent=fmTime(ts); row.querySelector('.msg-content').appendChild(t); }
  return b;
}
function mkMsgRow(role) {
  const row = document.createElement('div');
  row.className = 'msg '+(role==='user'?'msg-user':'msg-ai');
  row.innerHTML = '<div class="msg-avatar">'+(role==='user'?'👤':'🤖')+'</div><div class="msg-content"><div class="msg-bubble"></div></div>';
  $('#messages').appendChild(row);
  $('#messages').scrollTop = $('#messages').scrollHeight;
  return row;
}
function addTyping() {
  const row = document.createElement('div'); row.className = 'msg msg-ai';
  row.innerHTML = '<div class="msg-avatar">🤖</div><div class="msg-content"><div class="msg-bubble typing-dots"><span></span><span></span><span></span></div></div>';
  $('#messages').appendChild(row); return row;
}
function addCopyBtn(row) {
  const act = row.querySelector('.msg-actions');
  if (act) return;
  const div = document.createElement('div'); div.className='msg-actions';
  div.innerHTML = '<button>📋</button>';
  const content = row.querySelector('.msg-bubble').textContent;
  div.querySelector('button').onclick = () => navigator.clipboard.writeText(content).then(()=>{div.querySelector('button').textContent='✓';setTimeout(()=>div.querySelector('button').textContent='📋',1500);});
  row.querySelector('.msg-content').appendChild(div);
}

// ═══════ Memory card ═══════
function showMemCard(mems) {
  if (!mems?.length) return;
  const card = document.createElement('div'); card.className='mem-card';
  card.innerHTML = '<div class="mem-card-title">💡 我注意到 '+mems.length+' 条关于你的信息</div>';
  mems.forEach(m => {
    const tag = {preference:'偏好',weak_point:'薄弱点',progress:'进度'}[m.category]||m.category;
    card.innerHTML += '<div class="mem-row"><span class="mem-tag">'+tag+'</span><span class="mem-content">'+esc(m.content)+'</span><span class="mem-pct">'+Math.round((m.confidence||.7)*100)+'%</span><button class="mem-btn yes" data-id="'+esc(m.temp_id)+'" data-cat="'+esc(m.category)+'" data-content="'+esc(m.content)+'" data-topic="'+esc(m.topic||'')+'">✓</button><button class="mem-btn no" data-id="'+esc(m.temp_id)+'">✗</button></div>';
  });
  $('#messages').appendChild(card);
  card.querySelectorAll('.mem-btn.yes').forEach(b=>b.onclick=()=>memAction(b,'confirm'));
  card.querySelectorAll('.mem-btn.no').forEach(b=>b.onclick=()=>memAction(b,'dismiss'));
}
async function memAction(btn,action) {
  const {id,cat,content,topic}=btn.dataset;
  try{await fetch(API+'/memory/confirm',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:uid,temp_id:id,action,category:action==='confirm'?cat:'',content:action==='confirm'?content:'',topic:action==='confirm'?(topic||''):''})});}catch{}
  const row=btn.closest('.mem-row'); row.style.opacity='0'; row.style.transition='.3s';
  setTimeout(()=>{row.remove(); const c=btn.closest('.mem-card'); if(!c.querySelectorAll('.mem-row').length){c.style.opacity='0';setTimeout(()=>c.remove(),300);}},300);
}

// ═══════ Utils ═══════
function esc(s) { const d=document.createElement('div'); d.textContent=s||''; return d.innerHTML; }
function md(t) { if(!t)return''; try{return typeof marked!=='undefined'?marked.parse(t,{breaks:true}):esc(t).replace(/\n/g,'<br>');}catch{return esc(t).replace(/\n/g,'<br>');} }
function fmTime(ts) { if(!ts)return''; try{return new Date(ts).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'});}catch{return'';} }
function debounce(fn,ms) { let t; return (...a)=>{clearTimeout(t);t=setTimeout(()=>fn(...a),ms);}; }
function onKey(e) {
  if (e.key==='Enter'&&!e.shiftKey) { e.preventDefault(); sendMsg(); }
  else if (e.key==='Escape') { if(ac) stopGen(); else { e.target.value=''; onInput(); } }
}
function onInput() { const ta=$('#user-input'); ta.style.height='auto'; ta.style.height=Math.min(ta.scrollHeight,160)+'px'; $('#send-btn').disabled=!ta.value.trim(); }
function toggleTheme() {
  const n = document.documentElement.getAttribute('data-theme')==='dark'?'light':'dark';
  document.documentElement.setAttribute('data-theme',n);
  localStorage.setItem('mneme_theme',n);
  const hl = $('#hljs-theme');
  if (hl) hl.href = n==='dark' ? 'https://cdn.jsdelivr.net/npm/highlight.js@11/styles/github-dark.min.css' : 'https://cdn.jsdelivr.net/npm/highlight.js@11/styles/github.min.css';
}
