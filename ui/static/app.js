/* ──────────────────────────────────────────
   2501 DeepMemory — frontend logic
   ────────────────────────────────────────── */

// ── State ─────────────────────────────────
const state = {
  currentPage: null,
  editMode: false,
  pendingAttachments: [],   // [{type, content/path, filename, preview?}]
  isLoading: false,
  pauseTimer: null,
  ws: null,
  allPages: [],
};

const PAUSE_DELAY = 45_000; // 45 seconds before memory extraction

// ── DOM references ─────────────────────────
const $ = id => document.getElementById(id);
const messages     = $('messages');
const userInput    = $('userInput');
const sendBtn      = $('sendBtn');
const fileInput    = $('fileInput');
const attachments  = $('attachments');
const activityText = $('activityText');
const activityIcon = $('activityIcon');
const ghostDot     = $('ghostDot');
const ghostName    = $('ghostName');
const modelSelect  = $('modelSelect');
const pageList     = $('pageList');
const pageSearch   = $('pageSearch');
const pageContent  = $('pageContent');
const pageEditor   = $('pageEditor');
const editorActions = $('editorActions');
const currentPageName = $('currentPageName');
const tabList      = $('tabList');
const tabPage      = $('tabPage');

// ── Init ───────────────────────────────────
window.addEventListener('DOMContentLoaded', async () => {
  setupWebSocket();
  await loadStatus();
  await loadModels();
  await loadPages();
  setupInputHandlers();
});

// ── WebSocket ──────────────────────────────
function setupWebSocket() {
  const connect = () => {
    state.ws = new WebSocket(`ws://localhost:2501/ws`);

    state.ws.onmessage = e => {
      const msg = JSON.parse(e.data);
      handleWsMessage(msg);
    };

    state.ws.onclose = () => {
      setTimeout(connect, 2000); // reconnect
    };

    // Keep-alive ping every 20s
    state.ws.onopen = () => {
      setInterval(() => {
        if (state.ws.readyState === WebSocket.OPEN) {
          state.ws.send('ping');
        }
      }, 20_000);
    };
  };
  connect();
}

function handleWsMessage(msg) {
  if (msg.type === 'activity') {
    setActivity(msg.message, true);
  } else if (msg.type === 'ghost_updated') {
    loadPages();
    flashPages(msg.pages);
  }
}

// ── Status & models ────────────────────────
async function loadStatus() {
  try {
    const r = await fetch('/api/status');
    const data = await r.json();
    if (data.ghost_name) {
      ghostName.textContent = data.ghost_name;
      $('welcomeMsg').textContent =
        `Hello, ${data.ghost_name}. I'm your Ghost. What's on your mind?`;
    }
    if (!data.model) {
      ghostDot.classList.add('offline');
    }
  } catch {}
}

async function loadModels() {
  try {
    const r = await fetch('/api/models');
    const data = await r.json();
    modelSelect.innerHTML = '';
    if (data.models && data.models.length) {
      data.models.forEach(m => {
        const opt = document.createElement('option');
        opt.value = m;
        opt.textContent = m;
        if (m === data.current) opt.selected = true;
        modelSelect.appendChild(opt);
      });
    } else {
      const opt = document.createElement('option');
      opt.textContent = data.error || 'No models';
      modelSelect.appendChild(opt);
    }
  } catch {}
}

modelSelect.addEventListener('change', async () => {
  await fetch('/api/model', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({model: modelSelect.value}),
  });
});

// ── Input handlers ─────────────────────────
function setupInputHandlers() {
  // Auto-grow textarea
  userInput.addEventListener('input', () => {
    userInput.style.height = 'auto';
    userInput.style.height = Math.min(userInput.scrollHeight, 120) + 'px';
  });

  // Enter to send (Shift+Enter = newline)
  userInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  sendBtn.addEventListener('click', sendMessage);

  // File input
  fileInput.addEventListener('change', async () => {
    const file = fileInput.files[0];
    if (file) await handleFileAttachment(file);
    fileInput.value = '';
  });

  // Drag and drop on chat area
  messages.addEventListener('dragover', e => {
    e.preventDefault();
    messages.style.outline = '2px dashed #7c3aed';
  });
  messages.addEventListener('dragleave', () => {
    messages.style.outline = '';
  });
  messages.addEventListener('drop', async e => {
    e.preventDefault();
    messages.style.outline = '';
    const file = e.dataTransfer.files[0];
    if (file) await handleFileAttachment(file);
  });
}

// ── File handling ──────────────────────────
async function handleFileAttachment(file) {
  setActivity(`Uploading ${file.name}...`, true);
  const formData = new FormData();
  formData.append('file', file);

  try {
    const r = await fetch('/api/upload', {method: 'POST', body: formData});
    const data = await r.json();

    if (data.error) {
      setActivity(`⚠ ${data.error}`);
      return;
    }

    if (data.type === 'text') {
      state.pendingAttachments.push({
        type: 'text',
        content: data.content,
        filename: data.filename,
      });
      addAttachmentTag(`📄 ${data.filename}`);
      setActivity(`Attached: ${data.filename}`);

    } else if (data.type === 'image') {
      if (!data.multimodal_supported) {
        setActivity(`⚠ Current model doesn't support images. Switch to a vision model.`);
        return;
      }
      state.pendingAttachments.push({
        type: 'image',
        path: data.path,
        filename: data.filename,
      });
      addAttachmentTag(`🖼 ${data.filename}`);
      setActivity(`Image attached: ${data.filename}`);
    }
  } catch (e) {
    setActivity(`⚠ Upload failed: ${e.message}`);
  }
}

function addAttachmentTag(label) {
  const tag = document.createElement('div');
  tag.className = 'attachment-tag';
  tag.innerHTML = `<span>${label}</span><span class="remove" onclick="removeAttachment(this)">×</span>`;
  attachments.appendChild(tag);
}

function removeAttachment(el) {
  const idx = [...attachments.children].indexOf(el.closest('.attachment-tag'));
  if (idx >= 0) state.pendingAttachments.splice(idx, 1);
  el.closest('.attachment-tag').remove();
}

// ── Chat ───────────────────────────────────
async function sendMessage() {
  const text = userInput.value.trim();
  if ((!text && state.pendingAttachments.length === 0) || state.isLoading) return;

  // Build display content
  let displayContent = text;
  const attachLabels = state.pendingAttachments.map(a => a.filename);

  // Collect payload data
  const injectedTexts = state.pendingAttachments
    .filter(a => a.type === 'text')
    .map(a => `[File: ${a.filename}]\n${a.content}`)
    .join('\n\n---\n\n');

  const imagePaths = state.pendingAttachments
    .filter(a => a.type === 'image')
    .map(a => a.path);

  // Render user message
  appendMessage('user', displayContent, attachLabels);

  // Clear input
  userInput.value = '';
  userInput.style.height = 'auto';
  state.pendingAttachments = [];
  attachments.innerHTML = '';

  // Show typing indicator
  const typingEl = appendMessage('assistant', '', [], true);
  state.isLoading = true;
  sendBtn.disabled = true;
  clearPauseTimer();

  try {
    const r = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        message: text,
        injected_text: injectedTexts,
        images: imagePaths,
      }),
    });
    const data = await r.json();

    typingEl.classList.remove('typing');
    const msgContent = typingEl.querySelector('.msg-content');
    msgContent.innerHTML = renderMarkdown(data.reply || data.error || '⚠ No response');

    // Wire up wiki-links in response
    wireWikiLinks(msgContent);

  } catch (e) {
    typingEl.classList.remove('typing');
    typingEl.querySelector('.msg-content').textContent = `⚠ Error: ${e.message}`;
  } finally {
    state.isLoading = false;
    sendBtn.disabled = false;
    scrollToBottom();
    startPauseTimer();
  }
}

function appendMessage(role, content, attachLabels = [], typing = false) {
  const wrap = document.createElement('div');
  wrap.className = `message ${role}${typing ? ' typing' : ''}`;

  const roleEl = document.createElement('div');
  roleEl.className = 'msg-role';
  roleEl.textContent = role === 'user' ? 'You' : 'Ghost';

  if (attachLabels.length) {
    const attachEl = document.createElement('div');
    attachEl.className = 'msg-attachment';
    attachEl.textContent = '📎 ' + attachLabels.join(', ');
    wrap.appendChild(attachEl);
  }

  const contentEl = document.createElement('div');
  contentEl.className = 'msg-content';

  if (typing) {
    contentEl.textContent = '';
  } else if (role === 'assistant') {
    contentEl.innerHTML = renderMarkdown(content);
    wireWikiLinks(contentEl);
  } else {
    contentEl.textContent = content;
  }

  wrap.appendChild(roleEl);
  wrap.appendChild(contentEl);

  // Remove welcome message if present
  const welcome = messages.querySelector('.welcome');
  if (welcome) welcome.remove();

  messages.appendChild(wrap);
  scrollToBottom();
  return wrap;
}

function scrollToBottom() {
  messages.scrollTop = messages.scrollHeight;
}

// ── Markdown ───────────────────────────────
function renderMarkdown(text) {
  if (typeof marked === 'undefined') return escapeHtml(text);
  return marked.parse(text);
}

function escapeHtml(t) {
  return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function wireWikiLinks(container) {
  // Convert [[page-name]] text nodes into clickable spans
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
  const nodes = [];
  let n;
  while ((n = walker.nextNode())) nodes.push(n);

  nodes.forEach(node => {
    if (!node.textContent.includes('[[')) return;
    const span = document.createElement('span');
    span.innerHTML = node.textContent.replace(
      /\[\[([^\]]+)\]\]/g,
      (_, name) => `<span class="wiki-link" onclick="openPage('${name}')">${name}</span>`
    );
    node.parentNode.replaceChild(span, node);
  });
}

// ── Pause timer & memory extraction ────────
function startPauseTimer() {
  clearPauseTimer();
  state.pauseTimer = setTimeout(triggerExtraction, PAUSE_DELAY);
}

function clearPauseTimer() {
  if (state.pauseTimer) {
    clearTimeout(state.pauseTimer);
    state.pauseTimer = null;
  }
}

// Reset timer on any user typing
userInput.addEventListener('keydown', () => {
  if (state.pauseTimer) startPauseTimer(); // reset if already running
});

async function triggerExtraction() {
  setActivity('Ghost is processing memories...', true);
  try {
    await fetch('/api/extract', {method: 'POST'});
  } catch {}
}

// ── Activity bar ───────────────────────────
const SPINNER_CHARS = ['◌', '○', '◎', '●', '◎', '○'];
let spinnerInterval = null;
let spinnerIdx = 0;

function setActivity(text, spinning = false) {
  activityText.textContent = text;

  if (spinning) {
    if (!spinnerInterval) {
      spinnerInterval = setInterval(() => {
        activityIcon.textContent = SPINNER_CHARS[spinnerIdx % SPINNER_CHARS.length];
        spinnerIdx++;
      }, 150);
    }
    ghostDot.classList.add('active');
  } else {
    clearInterval(spinnerInterval);
    spinnerInterval = null;
    activityIcon.textContent = '○';
    ghostDot.classList.remove('active');
  }
}

// ── Ghost viewer ───────────────────────────
async function loadPages() {
  try {
    const r = await fetch('/api/ghost/pages');
    const data = await r.json();
    state.allPages = data.pages || [];
    renderPageList(state.allPages);
  } catch {}
}

function renderPageList(pages) {
  if (!pages.length) {
    pageList.innerHTML = '<div class="page-list-empty">No pages yet — start a conversation.</div>';
    return;
  }

  const icons = {index: '🗂', log: '📋'};
  const defaultIcon = '📄';

  pageList.innerHTML = pages.map(name => `
    <div class="page-item" id="page-item-${name}" onclick="openPage('${name}')">
      <span class="page-icon">${icons[name] || defaultIcon}</span>
      <span class="page-name">${name}</span>
    </div>
  `).join('');
}

function filterPages() {
  const q = pageSearch.value.toLowerCase();
  const filtered = q
    ? state.allPages.filter(p => p.includes(q))
    : state.allPages;
  renderPageList(filtered);
}

function flashPages(pages) {
  pages.forEach(name => {
    const el = document.getElementById(`page-item-${name}`);
    if (el) {
      el.classList.remove('new-flash');
      void el.offsetWidth; // reflow
      el.classList.add('new-flash');
    }
  });
}

async function openPage(name) {
  try {
    const r = await fetch(`/api/ghost/page/${encodeURIComponent(name)}`);
    const data = await r.json();
    if (data.error) return;

    state.currentPage = name;
    state.editMode = false;

    currentPageName.textContent = name + '.md';
    pageContent.innerHTML = renderMarkdown(data.content);
    wireWikiLinks(pageContent);
    pageEditor.value = data.content;
    pageEditor.style.display = 'none';
    editorActions.style.display = 'none';
    pageContent.style.display = 'block';
    $('editBtn').textContent = 'Edit';

    switchTab('page');
  } catch {}
}

function switchTab(tab) {
  if (tab === 'list') {
    $('viewList').style.display = 'block';
    $('viewPage').style.display = 'none';
    tabList.classList.add('active');
    tabPage.classList.remove('active');
    tabPage.style.display = 'none';
  } else {
    $('viewList').style.display = 'none';
    $('viewPage').style.display = 'flex';
    $('viewPage').style.flexDirection = 'column';
    tabList.classList.remove('active');
    tabPage.classList.add('active');
    tabPage.style.display = 'inline-block';
  }
}

function toggleEdit() {
  state.editMode = !state.editMode;
  if (state.editMode) {
    pageContent.style.display = 'none';
    pageEditor.style.display = 'block';
    editorActions.style.display = 'flex';
    $('editBtn').textContent = 'Preview';
  } else {
    pageContent.innerHTML = renderMarkdown(pageEditor.value);
    wireWikiLinks(pageContent);
    pageContent.style.display = 'block';
    pageEditor.style.display = 'none';
    editorActions.style.display = 'none';
    $('editBtn').textContent = 'Edit';
  }
}

async function savePage() {
  if (!state.currentPage) return;
  const content = pageEditor.value;
  try {
    await fetch(`/api/ghost/page/${encodeURIComponent(state.currentPage)}`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({content}),
    });
    pageContent.innerHTML = renderMarkdown(content);
    wireWikiLinks(pageContent);
    state.editMode = false;
    pageContent.style.display = 'block';
    pageEditor.style.display = 'none';
    editorActions.style.display = 'none';
    $('editBtn').textContent = 'Edit';
    setActivity(`Saved ${state.currentPage}.md`);
  } catch (e) {
    setActivity(`⚠ Save failed: ${e.message}`);
  }
}
