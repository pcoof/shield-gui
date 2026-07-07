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

// ---------- 自定义标题栏控制 ----------
const TitleBar = {
  // 拖拽
  _dragging: false,
  _lastX: 0,
  _lastY: 0,
  _lastCall: 0,
  // 边缘 resize
  _resizing: false,
  _resizeEdge: '',
  _startBounds: null,
  _startMouseX: 0,
  _startMouseY: 0,

  startDrag(e) {
    this._dragging = true;
    this._lastX = e.screenX;
    this._lastY = e.screenY;
  },

  startResize(e) {
    const edge = e.currentTarget.dataset.edge;
    if (!edge) return;
    this._resizing = true;
    this._resizeEdge = edge;
    this._startMouseX = e.screenX;
    this._startMouseY = e.screenY;
    // 冻结当前 bounds 避免重复查询
    Shield.call('window_get_bounds').then(b => { this._startBounds = b; });
    e.preventDefault();
  },

  /** 限频 ~60fps，返回 true = 可以执行 */
  _passThrottle() {
    const now = Date.now();
    if (now - this._lastCall < 16) return false;
    this._lastCall = now;
    return true;
  },

  onMouseMove(e) {
    if (!this._resizing && !this._dragging) return;
    e.preventDefault();
    if (!this._passThrottle()) return;

    if (this._resizing) {
      const b = this._startBounds;
      if (!b) return;
      const edge = this._resizeEdge;
      const dx = e.screenX - this._startMouseX;
      const dy = e.screenY - this._startMouseY;

      let x = b.x, y = b.y, w = b.w, h = b.h;
      if (edge.includes('t')) { y = b.y + dy; h = b.h - dy; }
      if (edge.includes('b')) { h = b.h + dy; }
      if (edge.includes('l')) { x = b.x + dx; w = b.w - dx; }
      if (edge.includes('r')) { w = b.w + dx; }

      Shield.call('window_set_bounds', x, y, w, h);
      return;
    }

    // 拖拽
    const dx = e.screenX - this._lastX;
    const dy = e.screenY - this._lastY;
    if (dx === 0 && dy === 0) return;
    this._lastX = e.screenX;
    this._lastY = e.screenY;
    Shield.call('window_move_by', dx, dy);
  },

  stopDrag() {
    this._dragging = false;
    this._resizing = false;
    this._startBounds = null;
  },

  minimize() { Shield.call('window_minimize'); },
  maximize() { Shield.call('window_maximize'); },
  close()    { Shield.call('window_close'); },

  openGitHub() {
    window.open('https://github.com/pcoof/shield-gui', '_blank');
  },

  async downloadGUIUpdate() {
    try {
      const res = await Shield.call('check_updates');
      const info = res && res.gui;
      if (info && info.download_url) {
        Shield.call('open_web_ui', 0);
        toast('已打开 GitHub Release 页', 'info');
        window.open(info.release_url || info.download_url, '_blank');
      } else {
        toast('暂无可用更新', 'info');
      }
    } catch (e) {
      toast('检查更新失败: ' + e.message, 'error');
    }
  },

  async downloadShieldUpdate() {
    try {
      const res = await Shield.call('check_updates');
      const info = res && res.shield;
      if (info && info.download_url) {
        window.open(info.download_url, '_blank');
        toast('已打开下载页', 'info');
      } else {
        toast('暂无可用更新', 'info');
      }
    } catch (e) {
      toast('检查更新失败: ' + e.message, 'error');
    }
  },

  async checkForUpdates() {
    try {
      const res = await Shield.call('check_updates');
      if (!res) return;
      // GUI 更新按钮
      const guiBtn = document.getElementById('btn-gui-update');
      if (guiBtn && res.gui && res.gui.has_update) {
        guiBtn.textContent = `⬆ GUI v${res.gui.latest_version}`;
        guiBtn.classList.remove('hidden');
      }
      // Shield CLI 更新按钮
      const shieldBtn = document.getElementById('btn-shield-update');
      if (shieldBtn && res.shield && res.shield.has_update) {
        shieldBtn.textContent = `⬆ CLI v${res.shield.latest_version}`;
        shieldBtn.classList.remove('hidden');
      }
    } catch (e) {
      // 静默失败，不影响主流程
      console.warn('update check failed', e);
    }
  }
};

// ---------- 全局状态 ----------
const State = {
  env: null,            // get_env() 返回值
  protocols: {},        // 协议元信息
  sessions: [],         // 活动会话
  pollTimer: null,      // 会话轮询定时器
  currentRoute: null,
  pendingPreset: null,  // 待填充的预设（内置常用端口预设用）
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
  backup:     { title: '备份恢复',       subtitle: '本地/远程/定时备份',  render: () => Views.backup() },
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

// ---------- 填充预设到新建隧道页（内置常用端口用） ----------
function fillPreset(protocol, target, displayName) {
  State.pendingPreset = { protocol, target, display_name: displayName };
  navigate('tunnel-new');
}

// ---------- 最大化状态检测 ----------
function checkMaximized() {
  // 当窗口外宽≈屏幕宽时判定为最大化
  const isMax = window.outerWidth >= screen.width && window.outerHeight >= screen.height;
  document.body.classList.toggle('is-maximized', isMax);
}

// ---------- 启动 ----------
async function boot() {
  // 最大化检测 + 窗口 resize 时重新检测
  checkMaximized();
  window.addEventListener('resize', checkMaximized);

  // 标题栏拖拽（mousedown → mousemove → mouseup）
  const dragEl = document.getElementById('titlebar-drag');
  if (dragEl) {
    dragEl.addEventListener('mousedown', (e) => {
      const tag = e.target.tagName;
      if (tag === 'BUTTON' || tag === 'INPUT' || tag === 'A' || tag === 'SELECT') return;
      TitleBar.startDrag(e);
      // 阻止选中文本
      e.preventDefault();
    });
  }
  document.addEventListener('mousemove', (e) => TitleBar.onMouseMove(e));
  document.addEventListener('mouseup', () => TitleBar.stopDrag());

  // 边缘 resize 手柄绑定
  document.querySelectorAll('.resize-handle').forEach(el => {
    el.addEventListener('mousedown', (e) => TitleBar.startResize(e));
  });

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
    // 更新标题栏版本号
    const guiVerEl = document.getElementById('titlebar-version');
    const guiVersion = State.env.gui_version || '1.0.0';
    if (guiVerEl) guiVerEl.textContent = 'v' + guiVersion;

    if (!State.env.installed) {
      document.getElementById('nav-footer').innerHTML =
        '<span class="text-danger">⚠ 未找到 shield.exe</span>';
      // 即使未安装也检测 GUI 更新
      TitleBar.checkForUpdates();
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

  // 延迟检测更新（避免启动时并发请求过多）
  setTimeout(() => TitleBar.checkForUpdates(), 3000);
}

// 视图容器（各 views 文件往里塞方法）
const Views = {};

document.addEventListener('DOMContentLoaded', boot);
