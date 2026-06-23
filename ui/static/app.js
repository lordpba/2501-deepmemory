/* ──────────────────────────────────────────
   2501 DeepMemory — frontend logic
   ────────────────────────────────────────── */

// ── State ─────────────────────────────────
const state = {
  currentPage: null,
  editMode: false,
  pendingAttachments: [],   // [{type, content/path, filename, preview?}]
  config: null,
  pauseTimer: null,
  ws: null,
  allPages: [],
  extracting: false,
  voiceSettings: {
    voice_mode: false,
    voice_continuous: false,
    whisper_model: 'base',
    tts_voice: null,
  },
  audioCtx: null,
  micStream: null,
  audioProcessor: null,
  isListening: false,
  speechDetected: false,
  silenceTimer: null,
  recordedSamples: [],
};

function showToast(message, duration = 5000) {
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.innerHTML = message;
  document.body.appendChild(toast);
  setTimeout(() => toast.classList.add('active'), 10);
  setTimeout(() => {
    toast.classList.remove('active');
    setTimeout(() => toast.remove(), 500);
  }, duration);
}

const PAUSE_DELAY = 45_000; // 45 seconds before memory extraction

// ── DOM references ─────────────────────────
const $ = id => document.getElementById(id);
const messages     = $('messages');
const userInput    = $('userInput');
const sendBtn      = $('sendBtn');
const fileInput    = $('fileInput');
const captureBtn   = $('captureBtn');
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
const tabGraph     = $('tabGraph');
const tabPage      = $('tabPage');

// ── Init ───────────────────────────────────
window.addEventListener('DOMContentLoaded', async () => {
  setupWebSocket();
  await loadStatus();
  await loadConfig(); // Load LLM config
  await loadModels();
  await loadPages();
  setupInputHandlers();
  setupConfigHandlers();

  // Auto-greet on fresh startup
  const isFreshStart = messages.querySelectorAll('.message:not(.welcome)').length === 0;
  if (isFreshStart) {
    setTimeout(() => {
      messages.innerHTML = ''; // Remove the hardcoded welcome message
      sendMessage("ciao", true);
    }, 500);
  }
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
    if ($('viewGraph').style.display !== 'none') {
      loadGraph();
    }
  }
}

// ── Status & models ────────────────────────
async function loadStatus() {
  try {
    const r = await fetch('/api/status');
    const data = await r.json();
    if (data.ghost_name) {
      ghostName.textContent = data.ghost_name;
      const welcome = $('welcomeMsg');
      if (welcome) {
        welcome.textContent = `Hello, ${data.ghost_name}. I'm your Ghost. What's on your mind?`;
      }
    }
    if (data.voice_settings) {
      state.voiceSettings = data.voice_settings;
      $('configVoiceMode').checked = state.voiceSettings.voice_mode;
      $('configVoiceContinuous').checked = state.voiceSettings.voice_continuous;
      $('configWhisperModel').value = state.voiceSettings.whisper_model;
      populateTtsVoices();
      toggleVoiceFields();
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
      opt.textContent = '⚠ No models found';
      modelSelect.appendChild(opt);
      
      if (state.config && state.config.provider === 'ollama') {
        showToast('Ollama not found or no models pulled. Visit <a href="https://ollama.com" target="_blank" style="color:var(--accent);text-decoration:underline">ollama.com</a> to install.', 10000);
      }
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

// ── Configuration ──────────────────────────
async function loadConfig() {
  try {
    const r = await fetch('/api/config');
    const data = await r.json();
    state.config = data;
    if (data.provider) {
      $('configProvider').value = data.provider;
      $('configOllamaBase').value = data.ollama_base || '';
      $('configApiKey').value = data.api_key || '';
      if ($('configSerperKey')) {
        $('configSerperKey').value = data.serper_api_key || '';
      }
      if ($('configOllamaThink')) {
        $('configOllamaThink').value = data.ollama_think || 'default';
      }
      toggleConfigFields(data.provider);
    }
  } catch {}
}

function setupConfigHandlers() {
  $('configBtn').addEventListener('click', () => {
    $('configModal').classList.add('active');
    $('configVoiceMode').checked = state.voiceSettings.voice_mode;
    $('configVoiceContinuous').checked = state.voiceSettings.voice_continuous;
    $('configWhisperModel').value = state.voiceSettings.whisper_model;
    if ($('configOllamaThink') && state.config) {
      $('configOllamaThink').value = state.config.ollama_think || 'default';
    }
    populateTtsVoices();
    toggleVoiceFields();
  });

  $('configProvider').addEventListener('change', (e) => {
    toggleConfigFields(e.target.value);
  });
}

function toggleConfigFields(provider) {
  if (provider === 'ollama') {
    $('ollamaFields').style.display = 'block';
    $('apiFields').style.display = 'none';
  } else {
    $('ollamaFields').style.display = 'none';
    $('apiFields').style.display = 'block';
  }
}

async function saveConfig() {
  const provider = $('configProvider').value;
  const config = {
    provider: provider,
    ollama_base: $('configOllamaBase').value,
    ollama_think: $('configOllamaThink') ? $('configOllamaThink').value : 'default',
    api_key: $('configApiKey').value,
    serper_api_key: $('configSerperKey') ? $('configSerperKey').value : ''
  };

  setActivity('Updating configuration...', true);
  try {
    // Save LLM configuration
    const r = await fetch('/api/config', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(config),
    });
    const data = await r.json();

    // Save Voice configuration
    const voiceConfig = {
      voice_mode: $('configVoiceMode').checked,
      voice_continuous: $('configVoiceContinuous').checked,
      whisper_model: $('configWhisperModel').value,
      tts_voice: $('configTtsVoice').value,
    };
    const r2 = await fetch('/api/voice/config', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(voiceConfig),
    });
    const data2 = await r2.json();

    if (data.status === 'ok' && data2.status === 'ok') {
      state.voiceSettings = voiceConfig;
      if (!state.config) state.config = {};
      state.config.ollama_think = config.ollama_think;
      toggleVoiceFields();
      closeModal('configModal');
      await loadModels(); // Refresh models for the new provider/endpoint
      setActivity('Configuration updated.');
    }
  } catch (e) {
    setActivity(`⚠ Config update failed: ${e.message}`);
  }
}

function closeModal(id) {
  $(id).classList.remove('active');
}

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

  // Microphone toggle button
  const micBtn = $('micBtn');
  if (micBtn) {
    micBtn.addEventListener('click', toggleListening);
  }

  // File input
  fileInput.addEventListener('change', async () => {
    const file = fileInput.files[0];
    if (file) await handleFileAttachment(file);
    fileInput.value = '';
  });

  // Screen Capture
  if (captureBtn) {
    captureBtn.addEventListener('click', captureScreen);
  }

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

// ── Screen Capture ─────────────────────────
async function captureScreen() {
  try {
    const stream = await navigator.mediaDevices.getDisplayMedia({ video: true });
    const track = stream.getVideoTracks()[0];
    
    // Create a hidden video element to render the stream
    const video = document.createElement('video');
    video.srcObject = stream;
    await video.play();

    // Create a canvas to draw the video frame
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    // Stop the stream immediately after capture
    stream.getTracks().forEach(t => t.stop());

    // Convert canvas to File object and attach
    canvas.toBlob(async blob => {
      if (blob) {
        const file = new File([blob], `Screenshot_${new Date().toISOString().replace(/[:.]/g, '-')}.png`, { type: 'image/png' });
        await handleFileAttachment(file);
      }
    }, 'image/png');

  } catch (err) {
    console.warn("Screen capture cancelled or failed: ", err);
  }
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
async function sendMessage(overrideText = null, hidden = false) {
  const text = typeof overrideText === 'string' ? overrideText : userInput.value.trim();
  if ((!text && state.pendingAttachments.length === 0) || state.isLoading) return;

  // Build display content
  let displayContent = text;
  const attachLabels = hidden ? [] : state.pendingAttachments.map(a => a.filename);

  // Collect payload data
  const injectedTexts = hidden ? "" : state.pendingAttachments
    .filter(a => a.type === 'text')
    .map(a => `[File: ${a.filename}]\n${a.content}`)
    .join('\n\n---\n\n');

  const imagePaths = hidden ? [] : state.pendingAttachments
    .filter(a => a.type === 'image')
    .map(a => a.path);

  // Render user message
  if (!hidden) {
    appendMessage('user', displayContent, attachLabels);
  }

  // Clear input
  if (overrideText === null) {
    userInput.value = '';
    userInput.style.height = 'auto';
    state.pendingAttachments = [];
    attachments.innerHTML = '';
  }

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

    // Speak the response if voice mode is enabled
    if (state.voiceSettings.voice_mode && data.reply) {
      speakText(data.reply);
    }

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

async function loadRaw() {
  try {
    const r = await fetch('/api/ghost/raw');
    const data = await r.json();
    const list = $('rawList');
    list.innerHTML = '';
    
    if (!data.files || data.files.length === 0) {
      list.innerHTML = '<div class="page-list-empty">No raw files. Upload some sources.</div>';
      return;
    }
    
    data.files.forEach(file => {
      const el = document.createElement('div');
      el.className = 'tree-item page-item';
      el.innerHTML = `<span class="page-icon">📦</span><span class="page-name">${file}</span>`;
      el.onclick = () => window.open('/api/ghost/raw/' + encodeURIComponent(file), '_blank');
      list.appendChild(el);
    });
  } catch {}
}

// Ensure rawUploadInput works
document.addEventListener('DOMContentLoaded', () => {
  const rawInput = $('rawUploadInput');
  if (rawInput) {
    rawInput.addEventListener('change', async () => {
      if (!rawInput.files.length) return;
      setActivity('Uploading raw files...', true);
      
      for (const file of rawInput.files) {
        const formData = new FormData();
        formData.append('file', file);
        try {
          await fetch('/api/ghost/raw/upload', {
            method: 'POST',
            body: formData
          });
        } catch (e) {
          console.error(e);
        }
      }
      rawInput.value = '';
      setActivity('Upload complete.');
      await loadRaw();
    });
  }
});

function renderPageList(pages) {
  if (!pages.length) {
    pageList.innerHTML = '<div class="page-list-empty">No pages yet — start a conversation.</div>';
    return;
  }

  // Build tree structure from flat list (split by '/')
  const tree = {};
  pages.forEach(name => {
    const parts = name.split('/');
    let current = tree;
    parts.forEach((part, i) => {
      if (i === parts.length - 1) {
        current[part] = { _isPage: true, fullName: name };
      } else {
        if (!current[part]) current[part] = {};
        current = current[part];
      }
    });
  });

  pageList.innerHTML = '';
  renderTree(tree, pageList, 0);
}

function renderTree(node, container, depth) {
  const sortedKeys = Object.keys(node).sort((a, b) => {
    const aIsPage = node[a]._isPage;
    const bIsPage = node[b]._isPage;
    if (aIsPage !== bIsPage) return aIsPage ? 1 : -1;
    return a.localeCompare(b);
  });

  sortedKeys.forEach(key => {
    const item = node[key];
    const el = document.createElement('div');
    el.className = 'tree-item';
    el.style.paddingLeft = `${depth * 12 + 10}px`;

    if (item._isPage) {
      el.classList.add('page-item');
      el.id = `page-item-${item.fullName}`;
      
      let icon = '📄';
      if (item.fullName === 'index' || item.fullName === 'log') icon = '🔖';
      else if (item.fullName.startsWith('raw/')) icon = '📦';
      
      el.innerHTML = `<span class="page-icon">${icon}</span><span class="page-name">${key}</span>`;
      el.onclick = () => {
        if (item.fullName.startsWith('raw/')) {
          const rawPath = item.fullName.substring(4); // Remove 'raw/'
          window.open('/api/ghost/raw/' + encodeURIComponent(rawPath), '_blank');
        } else {
          openPage(item.fullName);
        }
      };
    } else {
      el.classList.add('folder-item');
      el.innerHTML = `<span class="folder-icon">📁</span><span class="folder-name">${key}</span>`;
      const subContainer = document.createElement('div');
      subContainer.className = 'tree-sub-container';
      subContainer.style.display = 'none'; // Collapsed by default
      
      el.onclick = (e) => {
        e.stopPropagation();
        const isOpen = subContainer.style.display !== 'none';
        subContainer.style.display = isOpen ? 'none' : 'block';
        el.querySelector('.folder-icon').textContent = isOpen ? '📁' : '📂';
      };
      
      container.appendChild(el);
      container.appendChild(subContainer);
      renderTree(item, subContainer, depth + 1);
      return;
    }
    container.appendChild(el);
  });
}

function filterPages() {
  const q = pageSearch.value.toLowerCase();
  const filtered = q
    ? state.allPages.filter(p => p.includes(q))
    : state.allPages;
  renderPageList(filtered);
}

function switchTab(tab) {
  $('viewList').style.display = 'none';
  $('viewPage').style.display = 'none';
  $('viewGraph').style.display = 'none';
  $('viewRaw').style.display = 'none';
  
  $('tabList').classList.remove('active');
  $('tabGraph').classList.remove('active');
  $('tabPage').classList.remove('active');
  $('tabRaw').classList.remove('active');
  
  if (tab === 'list') {
    $('viewList').style.display = 'block';
    $('tabList').classList.add('active');
    tabPage.style.display = 'none';
    pageSearch.style.display = 'block';
  } else if (tab === 'raw') {
    $('viewRaw').style.display = 'block';
    $('tabRaw').classList.add('active');
    tabPage.style.display = 'none';
    pageSearch.style.display = 'none';
    loadRaw();
  } else if (tab === 'graph') {
    $('viewGraph').style.display = 'block';
    $('tabGraph').classList.add('active');
    tabPage.style.display = 'none';
    pageSearch.style.display = 'none';
    loadGraph();
  } else if (tab === 'page') {
    $('viewPage').style.display = 'flex';
    $('viewPage').style.flexDirection = 'column';
    $('tabPage').classList.add('active');
    tabPage.style.display = 'inline-block';
    pageSearch.style.display = 'none';
  }
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



// ── Graph rendering (D3.js) ────────────────
let simulation = null;

async function loadGraph() {
  try {
    const r = await fetch('/api/ghost/graph');
    const data = await r.json();
    renderGraph(data);
  } catch (e) {
    console.error("Graph error:", e);
  }
}

function renderGraph(data) {
  const container = $('graphContainer');
  const width = container.clientWidth;
  const height = container.clientHeight;

  // Clear previous
  container.innerHTML = '';

  const svg = d3.select(container)
    .append('svg')
    .attr('width', '100%')
    .attr('height', '100%')
    .attr('viewBox', [0, 0, width, height]);

  const g = svg.append('g');

  // Zoom
  svg.call(d3.zoom().on('zoom', (e) => {
    g.attr('transform', e.transform);
  }));

  if (simulation) simulation.stop();

  simulation = d3.forceSimulation(data.nodes)
    .force('link', d3.forceLink(data.links).id(d => d.id).distance(80))
    .force('charge', d3.forceManyBody().strength(-150))
    .force('center', d3.forceCenter(width / 2, height / 2))
    .force('x', d3.forceX(width / 2).strength(0.05))
    .force('y', d3.forceY(height / 2).strength(0.05));

  const link = g.append('g')
    .attr('class', 'links')
    .selectAll('line')
    .data(data.links)
    .join('line')
    .attr('class', 'link');

  const node = g.append('g')
    .attr('class', 'nodes')
    .selectAll('g')
    .data(data.nodes)
    .join('g')
    .attr('class', 'node-group')
    .call(drag(simulation));

  node.append('circle')
    .attr('class', 'node')
    .attr('r', d => (d.id === 'index' || d.id === 'log') ? 8 : 5)
    .attr('fill', d => (d.id === 'index' || d.id === 'log') ? '#a78bfa' : '#7c3aed')
    .on('click', (e, d) => {
      openPage(d.id);
    });

  node.append('text')
    .attr('class', 'label')
    .attr('dy', 15)
    .text(d => d.label);

  simulation.on('tick', () => {
    link
      .attr('x1', d => d.source.x)
      .attr('y1', d => d.source.y)
      .attr('x2', d => d.target.x)
      .attr('y2', d => d.target.y);

    node
      .attr('transform', d => `translate(${d.x},${d.y})`);
  });

  function drag(sim) {
    function dragstarted(event) {
      if (!event.active) sim.alphaTarget(0.3).restart();
      event.subject.fx = event.subject.x;
      event.subject.fy = event.subject.y;
    }
    function dragged(event) {
      event.subject.fx = event.x;
      event.subject.fy = event.y;
    }
    function dragended(event) {
      if (!event.active) sim.alphaTarget(0);
      event.subject.fx = null;
      event.subject.fy = null;
    }
    return d3.drag()
      .on('start', dragstarted)
      .on('drag', dragged)
      .on('end', dragended);
  }
}

// ── Maintenance ────────────────────────────
async function organizeWiki() {
  const btn = $('organizeWikiBtn');
  const originalText = btn.innerText;
  btn.disabled = true;
  btn.innerText = 'Organizing...';
  try {
    const r = await fetch('/api/ghost/organize', {method: 'POST'});
    const data = await r.json();
    if (data.error) {
      alert('Error: ' + data.error);
    } else {
      alert(data.message);
      await loadPages();
    }
  } catch (err) {
    alert('Failed to organize: ' + err);
  } finally {
    btn.disabled = false;
    btn.innerText = originalText;
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

async function deletePage() {
  if (!state.currentPage) return;
  if (!confirm(`Are you sure you want to delete ${state.currentPage}? This action cannot be undone.`)) return;
  
  try {
    const r = await fetch(`/api/ghost/page/${encodeURIComponent(state.currentPage)}`, {
      method: 'DELETE'
    });
    
    if (r.ok) {
      setActivity(`Deleted ${state.currentPage}.md`);
      state.currentPage = null;
      switchTab('list');
      await loadPages();
    } else {
      const data = await r.json();
      setActivity(`⚠ Delete failed: ${data.error}`);
    }
  } catch (e) {
    setActivity(`⚠ Delete failed: ${e.message}`);
  }
}

// ── Voice Control Logic ────────────────────
function toggleVoiceFields() {
  const enabled = state.voiceSettings.voice_mode;
  const modelGroup = $('voiceModelGroup');
  const ttsGroup = $('voiceTtsGroup');
  const micBtn = $('micBtn');
  if (modelGroup) modelGroup.style.display = enabled ? 'block' : 'none';
  if (ttsGroup) ttsGroup.style.display = enabled ? 'block' : 'none';
  if (micBtn) micBtn.style.display = enabled ? 'flex' : 'none';
}

function populateTtsVoices() {
  const synth = window.speechSynthesis;
  if (!synth || !synth.getVoices) return;

  const getVoices = () => {
    const voices = synth.getVoices();
    if (!voices) return;
    const italianVoices = voices.filter(v => v && v.lang && v.lang.startsWith('it'));
    const dropdown = $('configTtsVoice');
    if (!dropdown) return;
    dropdown.innerHTML = '';

    if (italianVoices.length === 0) {
      const opt = document.createElement('option');
      opt.value = '';
      opt.textContent = 'No Italian voice found (system default)';
      dropdown.appendChild(opt);
      return;
    }

    italianVoices.forEach(v => {
      const opt = document.createElement('option');
      opt.value = v.name;
      opt.textContent = `${v.name} (${v.lang})`;
      if (v.name === state.voiceSettings.tts_voice) {
        opt.selected = true;
      }
      dropdown.appendChild(opt);
    });
  };

  getVoices();
  if (synth.onvoiceschanged !== undefined) {
    synth.onvoiceschanged = getVoices;
  }
}

function speakText(text) {
  const synth = window.speechSynthesis;
  if (!synth) return;

  synth.cancel();

  // Clean code blocks and markdown formatting to make reading natural
  let clean = text
    .replace(/```[\s\S]*?```/g, '') // remove code blocks
    .replace(/`[^`]+`/g, '') // remove inline code
    .replace(/\[\[([^\]]+)\]\]/g, '$1') // replace [[page]] with page
    .replace(/ACTION:\s*(SEARCH|READ)\s+\[(.*?)\]/gi, '')
    .replace(/ACTION:\s*(SEARCH|READ)\s+(.*)/gi, '')
    .replace(/[*_#\-|>]/g, '') // remove markdown symbols
    .trim();

  if (!clean) return;

  const utterance = new SpeechSynthesisUtterance(clean);
  const voices = synth.getVoices();
  let selected = voices.find(v => v.name === state.voiceSettings.tts_voice);
  if (!selected) {
    selected = voices.find(v => v.lang && v.lang.startsWith('it'));
  }

  if (selected) {
    utterance.voice = selected;
  } else {
    utterance.lang = 'it-IT';
  }

  utterance.onend = () => {
    if (state.voiceSettings.voice_mode && state.voiceSettings.voice_continuous) {
      setTimeout(startListening, 300);
    }
  };

  synth.speak(utterance);
}

function startListening() {
  if (state.isListening) return;

  window.speechSynthesis.cancel();

  navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      sampleRate: 16000,
      echoCancellation: true,
      noiseSuppression: true
    }
  }).then(stream => {
    state.micStream = stream;
    state.audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });

    const source = state.audioCtx.createMediaStreamSource(stream);
    state.audioProcessor = state.audioCtx.createScriptProcessor(4096, 1, 1);

    state.recordedSamples = [];
    state.speechDetected = false;
    if (state.silenceTimer) clearTimeout(state.silenceTimer);
    state.silenceTimer = null;

    const SILENCE_THRESHOLD = 0.015;
    const SILENCE_DURATION = 1500;

    state.audioProcessor.onaudioprocess = function(e) {
      if (!state.isListening) return;
      const inputData = e.inputBuffer.getChannelData(0);
      state.recordedSamples.push(new Float32Array(inputData));

      let sum = 0;
      for (let i = 0; i < inputData.length; i++) {
        sum += inputData[i] * inputData[i];
      }
      let rms = Math.sqrt(sum / inputData.length);

      if (state.voiceSettings.voice_continuous) {
        if (rms > SILENCE_THRESHOLD) {
          state.speechDetected = true;
          if (state.silenceTimer) {
            clearTimeout(state.silenceTimer);
            state.silenceTimer = null;
          }
        } else if (state.speechDetected) {
          if (!state.silenceTimer) {
            state.silenceTimer = setTimeout(() => {
              console.log("VAD: silence detected, sending...");
              stopListeningAndSend();
            }, SILENCE_DURATION);
          }
        }
      }
    };

    source.connect(state.audioProcessor);
    state.audioProcessor.connect(state.audioCtx.destination);

    state.isListening = true;
    $('micBtn').style.color = '#ef4444';
    $('micRecordIndicator').style.display = 'block';
    setActivity('Listening...', false);
  }).catch(err => {
    console.error("Microphone access failed:", err);
    showToast("Microphone access failed: " + err.message);
  });
}

async function stopListeningAndSend() {
  if (!state.isListening) return;

  state.isListening = false;
  $('micBtn').style.color = 'var(--text-dim)';
  $('micRecordIndicator').style.display = 'none';
  setActivity('Processing voice...', true);

  if (state.audioProcessor) state.audioProcessor.disconnect();
  if (state.audioCtx) state.audioCtx.close();
  if (state.micStream) {
    state.micStream.getTracks().forEach(t => t.stop());
  }
  if (state.silenceTimer) clearTimeout(state.silenceTimer);

  const totalLength = state.recordedSamples.reduce((acc, buf) => acc + buf.length, 0);
  if (totalLength === 0) {
    setActivity('No audio recorded.');
    return;
  }

  const samples = new Float32Array(totalLength);
  let offset = 0;
  for (const buf of state.recordedSamples) {
    samples.set(buf, offset);
    offset += buf.length;
  }

  const wavBlob = encodeWav(samples, 16000);
  const formData = new FormData();
  formData.append('file', wavBlob, 'recording.wav');

  try {
    const r = await fetch('/api/voice/transcribe', {
      method: 'POST',
      body: formData
    });
    const data = await r.json();

    if (data.error) {
      setActivity(`STT Error: ${data.error}`);
    } else if (data.text && data.text.trim()) {
      setActivity('Transcribed: ' + data.text);
      userInput.value = data.text;
      userInput.dispatchEvent(new Event('input'));
      sendMessage();
    } else {
      setActivity('No speech detected.');
    }
  } catch (e) {
    setActivity(`Voice error: ${e.message}`);
  }
}

function toggleListening() {
  if (state.isListening) {
    stopListeningAndSend();
  } else {
    startListening();
  }
}

function encodeWav(samples, sampleRate) {
  let buffer = new ArrayBuffer(44 + samples.length * 2);
  let view = new DataView(buffer);

  writeString(view, 0, 'RIFF');
  view.setUint32(4, 36 + samples.length * 2, true);
  writeString(view, 8, 'WAVE');
  writeString(view, 12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(view, 36, 'data');
  view.setUint32(40, samples.length * 2, true);

  for (let i = 0; i < samples.length; i++) {
    let s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
  }

  return new Blob([view], { type: 'audio/wav' });
}

function writeString(view, offset, string) {
  for (let i = 0; i < string.length; i++) {
    view.setUint8(offset + i, string.charCodeAt(i));
  }
}

// Inject custom pulse style for microphone recording indicator
const micStyle = document.createElement('style');
micStyle.innerHTML = `
  @keyframes mic-pulse {
    0% { transform: scale(0.9); opacity: 1; }
    50% { transform: scale(1.3); opacity: 0.7; }
    100% { transform: scale(0.9); opacity: 1; }
  }
  #micRecordIndicator {
    animation: mic-pulse 1.2s infinite ease-in-out;
  }
`;
document.head.appendChild(micStyle);

// First interaction listener to bypass browser audio autoplay restrictions
const unlockAudio = () => {
  if (state.voiceSettings.voice_mode) {
    console.log("Audio unlocked by user interaction");
    const synth = window.speechSynthesis;
    if (synth) {
      const u = new SpeechSynthesisUtterance("");
      synth.speak(u);
    }
    if (state.voiceSettings.voice_continuous && !state.isListening) {
      startListening();
    }
  }
  window.removeEventListener('click', unlockAudio);
  window.removeEventListener('keydown', unlockAudio);
};
window.addEventListener('click', unlockAudio);
window.addEventListener('keydown', unlockAudio);
