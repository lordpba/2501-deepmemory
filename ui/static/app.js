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

// ── Configuration ──────────────────────────
async function loadConfig() {
  try {
    const r = await fetch('/api/config');
    const data = await r.json();
    if (data.provider) {
      $('configProvider').value = data.provider;
      $('configOllamaBase').value = data.ollama_base || '';
      $('configApiKey').value = data.api_key || '';
      if ($('configSerperKey')) {
        $('configSerperKey').value = data.serper_api_key || '';
      }
      toggleConfigFields(data.provider);
    }
  } catch {}
}

function setupConfigHandlers() {
  $('configBtn').addEventListener('click', () => {
    $('configModal').classList.add('active');
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
    api_key: $('configApiKey').value,
    serper_api_key: $('configSerperKey') ? $('configSerperKey').value : ''
  };

  setActivity('Updating configuration...', true);
  try {
    const r = await fetch('/api/config', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(config),
    });
    const data = await r.json();
    if (data.status === 'ok') {
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
      const icon = (item.fullName === 'index' || item.fullName === 'log') ? '🔖' : '📄';
      el.innerHTML = `<span class="page-icon">${icon}</span><span class="page-name">${key}</span>`;
      el.onclick = () => openPage(item.fullName);
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
    $('viewGraph').style.display = 'none';
    tabList.classList.add('active');
    tabGraph.classList.remove('active');
    tabPage.classList.remove('active');
    tabPage.style.display = 'none';
    pageSearch.style.display = 'block';
  } else if (tab === 'graph') {
    $('viewList').style.display = 'none';
    $('viewPage').style.display = 'none';
    $('viewGraph').style.display = 'block';
    tabList.classList.remove('active');
    tabGraph.classList.add('active');
    tabPage.classList.remove('active');
    tabPage.style.display = 'none';
    pageSearch.style.display = 'none';
    loadGraph();
  } else {
    $('viewList').style.display = 'none';
    $('viewPage').style.display = 'flex';
    $('viewPage').style.flexDirection = 'column';
    $('viewGraph').style.display = 'none';
    tabList.classList.remove('active');
    tabGraph.classList.remove('active');
    tabPage.classList.add('active');
    tabPage.style.display = 'inline-block';
    pageSearch.style.display = 'none';
  }
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
