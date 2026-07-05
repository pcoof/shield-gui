/* ==========================================================================
   Shield GUI — 前端核心：路由 + 全局状态 + 事件总线 + 工具
   ========================================================================== */

// ---------- pywebview API 桥接封装 ----------
// pywebview 在 window.pywebview.api 上挂载 Python 方法，但调用是异步的 Promise。
// 不同 pywebview 版本下，第一次调用可能要等 window.pywebview.readyState == 'loaded'。
const Shield = {
  _ready: false,
  async _waitReady() {
    // 等待 pywebview 注入完成
    let tries = 0;
    while ((!window.pywebview || !window.pywebview.api) && tries < 200) {
      await new Promise(r => setTimeout(r, 50));
      tries++;
    }
    if (window.pywebview && window.pywebview.api) {
      this._ready = true;
      return window.pywebview.api;
    }
    return null;
  },
  async call(method, ...args) {
    const api = await this._waitReady();
    if (!api || typeof api[method] !== 'function') {
      throw new Error(`API 方法不可用: ${method}`);
    }
    return await api[method](...args);
  }
};

// pywebview 加载完成的官方事件
window.addEventListener('pywebviewready', () => { Shield._ready = true; });

// ---------- 全局状态 ----------
const State = {
  env: null,            // get_env() 返回值
  protocols: {},        // 协议元信息
  sessions: [],         // 活动会话
  pollTimer: null,      // 会话轮询定时器
  currentRoute: null,
};

// ---------- 路由表 ----------
const ROUTES = {
  dashboard:  { title: '仪表盘',         subtitle: 'Shield 服务总览',     render: () => Views.dashboard() },
  'tunnel-new': { title: '新建隧道',     subtitle: '创建一个新的安全隧道', render: () => Views.tunnelNew() },
  presets:    { title: '连接预设',       subtitle: '保存与复用隧道配置',   render: () => Views.presets() },
  sessions:   { title: '活动会话',       subtitle: '管理运行中的隧道',     render: () => Views.sessions() },
  protocols:  { title: '协议指南',       subtitle: '8 种协议的用法',       render: () => Views.protocols() },
  plugins:    { title: '插件管理',       subtitle: '扩展协议支持',         render: () => Views.plugins() },
  service:    { title: '系统服务',       subtitle: '安装/启停/卸载',       render: () => Views.service() },
  credentials:{ title: '凭证与安全',     subtitle: '凭证管理与访问模式',   render: () => Views.credentials() },
  settings:   { title: '应用配置',       subtitle: '自定义服务器/缓存',    render: () => Views.settings() },
};

// ---------- 路由导航 ----------
function navigate(route) {
  if (!ROUTES[route]) route = 'dashboard';
  State.currentRoute = route;
  // 高亮导航
  document.querySelectorAll('.nav-item').forEach(el => {
    el.classList.toggle('active', el.dataset.route === route);
  });
  const meta = ROUTES[route];
  document.getElementById('topbar-title').textContent = meta.title;
  document.getElementById('topbar-subtitle').textContent = meta.subtitle;
  const root = document.getElementById('view-root');
  root.innerHTML = '';
  try {
    const html = meta.render();
    if (html) {
      const wrap = document.createElement('div');
      wrap.className = 'view';
      wrap.innerHTML = html;
      root.appendChild(wrap);
    }
    // 调用挂载钩子
    const hookName = '_mount_' + route.replace(/-/g, '_');
    if (typeof Views[hookName] === 'function') Views[hookName]();
  } catch (e) {
    root.innerHTML = `<div class="alert alert-danger"><b>渲染错误</b><pre>${escapeHtml(String(e))}</pre></div>`;
    console.error(e);
  }
}

// ---------- 工具函数 ----------
function escapeHtml(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
function escapeAttr(s) { return escapeHtml(s); }

function fmtTime(ts) {
  if (!ts) return '—';
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString('zh-CN', { hour12: false });
}
function fmtDuration(start, end) {
  if (!start) return '—';
  const sec = Math.floor(((end || Date.now()/1000) - start));
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec/60)}m${sec%60}s`;
  return `${Math.floor(sec/3600)}h${Math.floor((sec%3600)/60)}m`;
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast('已复制到剪贴板', 'success');
  } catch {
    // 回退
    const ta = document.createElement('textarea');
    ta.value = text; document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); toast('已复制', 'success'); }
    catch { toast('复制失败', 'error'); }
    document.body.removeChild(ta);
  }
}

// ---------- Toast ----------
function toast(msg, type = 'info', ms = 3000) {
  const stack = document.getElementById('toast-stack');
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  const icon = {success:'✓', error:'✕', warning:'!', info:'ℹ'}[type] || 'ℹ';
  el.innerHTML = `<span>${icon}</span><span>${escapeHtml(msg)}</span>`;
  stack.appendChild(el);
  setTimeout(() => {
    el.style.opacity = '0';
    el.style.transition = 'opacity .3s';
    setTimeout(() => el.remove(), 300);
  }, ms);
}

// ---------- 确认对话框 ----------
function confirmDialog(title, body) {
  return new Promise(resolve => {
    const mask = document.createElement('div');
    mask.className = 'modal-mask';
    mask.innerHTML = `
      <div class="modal">
        <h3 class="modal-title">${escapeHtml(title)}</h3>
        <div class="modal-body">${escapeHtml(body)}</div>
        <div class="modal-actions">
          <button class="btn" data-act="cancel">取消</button>
          <button class="btn btn-primary" data-act="ok">确认</button>
        </div>
      </div>`;
    document.body.appendChild(mask);
    mask.addEventListener('click', e => {
      if (e.target === mask || e.target.dataset.act === 'cancel') {
        mask.remove(); resolve(false);
      } else if (e.target.dataset.act === 'ok') {
        mask.remove(); resolve(true);
      }
    });
  });
}

// ---------- 会话轮询 ----------
function startSessionPolling() {
  if (State.pollTimer) return;
  State.pollTimer = setInterval(refreshSessions, 2000);
  refreshSessions();
}
function stopSessionPolling() {
  if (State.pollTimer) { clearInterval(State.pollTimer); State.pollTimer = null; }
}
async function refreshSessions() {
  try {
    const res = await Shield.call('list_sessions');
    State.sessions = Array.isArray(res) ? res : [];
    // 更新导航徽章
    const badge = document.getElementById('nav-sessions-badge');
    const running = State.sessions.filter(s => s.status === 'running').length;
    if (running > 0) {
      badge.textContent = running;
      badge.classList.remove('hidden');
    } else {
      badge.classList.add('hidden');
    }
    // 如果当前在会话页，触发增量刷新
    if (State.currentRoute === 'sessions' && typeof Views._refresh_sessions === 'function') {
      Views._refresh_sessions();
    }
  } catch (e) { /* 静默 */ }
}

// ---------- 启动 ----------
async function boot() {
  // 绑定导航点击
  document.querySelectorAll('.nav-item').forEach(el => {
    el.addEventListener('click', () => navigate(el.dataset.route));
  });
  // 顶栏按钮
  document.getElementById('btn-quick-connect').addEventListener('click', () => navigate('tunnel-new'));
  document.getElementById('btn-open-webui').addEventListener('click', async () => {
    // 先启动 Web UI（如已在运行则直接打开）
    const startRes = await Shield.call('start_web_ui', 8181);
    const started = startRes.code === 0 || startRes.already_running;
    const ok = await Shield.call('open_web_ui', 8181);
    if (ok) toast(started ? 'Web UI 已启动并打开' : '已打开浏览器', 'success');
    else toast('打开失败', 'error');
  });

  // 检测环境
  try {
    State.env = await Shield.call('get_env');
    if (!State.env.installed) {
      document.getElementById('nav-footer').innerHTML =
        '<span class="text-danger">⚠ 未找到 shield.exe</span>';
      navigate('dashboard');
      return;
    }
    State.protocols = State.env.protocols || {};
    // 版本号显示
    const ver = State.env.version || '';
    document.getElementById('nav-version').textContent = ver || 'Shield CLI';
    // 配置目录提示
    const cfg = State.env.config || {};
    if (cfg.needs_trigger) {
      document.getElementById('nav-footer').innerHTML =
        `<span class="text-warning">⏳ 配置目录待生成</span><br>` +
        `<span class="text-xs">首次连接时自动触发</span>`;
    } else {
      document.getElementById('nav-footer').textContent = '配置: ' + (cfg.effective_dir || '');
    }
  } catch (e) {
    console.error('boot env failed', e);
    toast('环境检测失败: ' + e.message, 'error');
  }

  navigate('dashboard');
  startSessionPolling();
}

// 视图容器（各 views 文件往里塞方法）
const Views = {};

document.addEventListener('DOMContentLoaded', boot);
