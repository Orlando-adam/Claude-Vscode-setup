const vscode = require('vscode');
const http    = require('http');
const { spawn } = require('child_process');
const os   = require('os');
const path = require('path');

function getConfig() {
  const cfg = vscode.workspace.getConfiguration('brainGraph');
  const port = cfg.get('port') || 4322;
  const script = cfg.get('serverScript') ||
    path.join(os.homedir(), 'brain-graph', 'graph_viewer.py');
  return { port, script };
}

let _port = 4322;
let SERVER_SCRIPT = path.join(os.homedir(), 'brain-graph', 'graph_viewer.py');
let SERVER_URL    = `http://localhost:${_port}`;

let panel         = null;
let statusBarItem = null;
let sseReq        = null;

// ── Activate ──────────────────────────────────────────────────────────────────

function activate(context) {
  // Apply config at activation time and on settings change
  const applyConfig = () => {
    const cfg = getConfig();
    _port = cfg.port;
    SERVER_SCRIPT = cfg.script;
    SERVER_URL = `http://localhost:${_port}`;
  };
  applyConfig();
  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration(e => {
      if (e.affectsConfiguration('brainGraph')) applyConfig();
    })
  );

  statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 99);
  statusBarItem.text    = '$(graph) Brain Graph';
  statusBarItem.tooltip = 'Open Brain Graph  (⌘⌥G)';
  statusBarItem.command = 'brainGraph.open';
  statusBarItem.show();
  context.subscriptions.push(statusBarItem);

  context.subscriptions.push(
    vscode.commands.registerCommand('brainGraph.open', () => openGraph(context))
  );
}

// ── Open panel ────────────────────────────────────────────────────────────────

async function openGraph(context) {
  if (panel) { panel.reveal(vscode.ViewColumn.Beside); return; }

  await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: 'Brain Graph', cancellable: false },
    async (p) => {
      p.report({ message: 'Starting server…' });
      await ensureServer();
      p.report({ message: 'Loading graph…' });
    }
  );

  panel = vscode.window.createWebviewPanel(
    'brainGraph', 'Brain Graph', vscode.ViewColumn.Beside,
    { enableScripts: true, retainContextWhenHidden: true }
  );

  panel.webview.html = await buildWebviewHtml();

  // ── Message handler: proxy fetch + file open ──────────────────────────────
  panel.webview.onDidReceiveMessage(async (msg) => {
    switch (msg.type) {

      case 'fetch': {
        try {
          const result = await proxyGet(msg.url);
          panel.webview.postMessage({ type: 'fetch-ok', id: msg.id, body: result.body, ct: result.ct });
        } catch (err) {
          panel.webview.postMessage({ type: 'fetch-err', id: msg.id, error: String(err) });
        }
        break;
      }

      case 'sse-start':
        startSseBridge();
        break;

      case 'open-file': {
        try {
          const uri = vscode.Uri.file(msg.path);
          const doc = await vscode.workspace.openTextDocument(uri);
          await vscode.window.showTextDocument(doc, { preview: false, viewColumn: vscode.ViewColumn.One });
        } catch {
          vscode.window.showErrorMessage(`Brain Graph: cannot open ${msg.path}`);
        }
        break;
      }
    }
  }, undefined, context.subscriptions);

  panel.onDidDispose(() => {
    panel = null;
    if (sseReq) { sseReq.destroy(); sseReq = null; }
  }, undefined, context.subscriptions);
}

// ── SSE bridge: extension listens to server, forwards to webview ──────────────

function startSseBridge() {
  if (sseReq) sseReq.destroy();
  sseReq = http.get(`${SERVER_URL}/events`, (res) => {
    let buf = '';
    res.setEncoding('utf8');
    res.on('data', chunk => {
      buf += chunk;
      const parts = buf.split('\n\n');
      buf = parts.pop();
      for (const part of parts) {
        const line = part.trim();
        if (line.startsWith('data:')) {
          const data = line.slice(5).trim();
          if (panel) panel.webview.postMessage({ type: 'sse-event', data });
        }
      }
    });
    res.on('end', () => { if (panel) setTimeout(startSseBridge, 3000); });
  });
  sseReq.on('error', () => { if (panel) setTimeout(startSseBridge, 3000); });
}

// ── HTTP proxy ────────────────────────────────────────────────────────────────

function proxyGet(url) {
  return new Promise((resolve, reject) => {
    const req = http.get(url, (res) => {
      const ct = res.headers['content-type'] || '';
      let body = '';
      res.setEncoding('utf8');
      res.on('data', c => { body += c; });
      res.on('end', () => resolve({ body, ct }));
    });
    req.on('error', reject);
    req.setTimeout(10000, () => { req.destroy(); reject(new Error('timeout')); });
  });
}

// ── Build webview HTML ────────────────────────────────────────────────────────
// Fetches the graph page, strips scripts that use fetch/EventSource,
// injects a proxy layer that routes all requests through VS Code messages.

async function buildWebviewHtml() {
  let html = await proxyGet(SERVER_URL).then(r => r.body);

  // Inject proxy + VS Code bridge before </body>
  const bridge = `
<script>
(function () {
  // ── Fetch proxy ───────────────────────────────────────────────────────────
  // VS Code webview CSP blocks direct HTTP. Route everything via postMessage.
  const _vscode  = acquireVsCodeApi();
  const _pending = {};

  function vscFetch(url, _opts) {
    // Resolve relative URLs against server root
    if (typeof url === 'string' && !url.startsWith('http')) {
      url = 'http://localhost:${PORT}' + (url.startsWith('/') ? url : '/' + url);
    }
    return new Promise((res, rej) => {
      const id = Math.random().toString(36).slice(2);
      _pending[id] = { res, rej };
      _vscode.postMessage({ type: 'fetch', id, url });
    });
  }
  window.fetch = vscFetch;

  // ── SSE proxy ─────────────────────────────────────────────────────────────
  const _esInstances = [];
  function FakeES(url) {
    this.readyState  = 0;
    this.onmessage   = null;
    this._listeners  = {};
    _vscode.postMessage({ type: 'sse-start' });
    _esInstances.push(this);
  }
  FakeES.prototype.addEventListener = function(t, fn) {
    (this._listeners[t] = this._listeners[t] || []).push(fn);
  };
  FakeES.prototype.close = function() { this.readyState = 2; };
  window.EventSource = FakeES;

  // ── Message handler ───────────────────────────────────────────────────────
  window.addEventListener('message', e => {
    const msg = e.data;

    if ((msg.type === 'fetch-ok' || msg.type === 'fetch-err') && _pending[msg.id]) {
      const { res, rej } = _pending[msg.id];
      delete _pending[msg.id];
      if (msg.type === 'fetch-err') {
        rej(new TypeError(msg.error));
      } else {
        // Build a minimal Response-like object
        const headers = new Headers({ 'content-type': msg.ct || 'text/plain' });
        const r = new Response(msg.body, { status: 200, headers });
        res(r);
      }
    }

    if (msg.type === 'sse-event') {
      for (const es of _esInstances) {
        const ev = new MessageEvent('message', { data: msg.data });
        if (es.onmessage) es.onmessage(ev);
        (es._listeners['message'] || []).forEach(fn => fn(ev));
      }
    }
  });

  // ── "Open in VS Code" button on node click ────────────────────────────────
  function patchGraph() {
    if (typeof showFileInfo === 'undefined') { setTimeout(patchGraph, 100); return; }
    const orig = window.showFileInfo;
    window.showFileInfo = function(d) {
      orig(d);
      const actions = document.getElementById('file-actions');
      if (!actions) return;
      const old = actions.querySelector('.btn-vscode');
      if (old) old.remove();
      const btn = document.createElement('button');
      btn.className = 'btn-primary btn-vscode';
      btn.textContent = '↗ Open in VS Code';
      btn.style.marginLeft = 'auto';
      btn.onclick = () => _vscode.postMessage({ type: 'open-file', path: d.path });
      actions.appendChild(btn);
    };
  }
  patchGraph();
})();
</script>`;

  return html.replace('</body>', bridge + '\n</body>');
}

// ── Server management ─────────────────────────────────────────────────────────

async function ensureServer() {
  if (await isServerRunning()) return;
  const proc = spawn('python3', [SERVER_SCRIPT], { detached: true, stdio: 'ignore' });
  proc.unref();
  for (let i = 0; i < 40; i++) {
    await sleep(500);
    if (await isServerRunning()) return;
  }
  throw new Error('Brain Graph server did not start within 20 seconds');
}

function isServerRunning() {
  return new Promise(resolve => {
    const req = http.get(`${SERVER_URL}/api/nodes`, res => { res.resume(); resolve(res.statusCode === 200); });
    req.on('error', () => resolve(false));
    req.setTimeout(2000, () => { req.destroy(); resolve(false); });
  });
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
function deactivate() { if (sseReq) sseReq.destroy(); }
module.exports = { activate, deactivate };
