/* ==========================================================================
   Shield GUI — 前端核心：路由 + 全局状态 + 事件总线 + 工具
   ========================================================================== */

// ---------- 视图容器（必须最先定义） ----------
// 各 views/*.js 会往这个对象里塞方法。显式挂到 window，避免脚本加载顺序
// 或 WebView2 缓存导致视图文件里访问 Views 时拿到旧对象 / undefined。
const Views = {};
window.Views = Views;

// 视图 → 脚本文件（视图未加载时用于自动重载自愈）
const VIEW_SCRIPTS = {
  dashboard:   'views/dashboard.js',
  tunnelNew:   'views/tunnel-new.js',
  presets:     'views/presets.js',
  sessions:    'views/sessions.js',
  protocols:   'views/protocols.js',
  plugins:     'views/plugins.js',
  service:     'views/service.js',
  credentials: 'views/credentials.js',
  backup:      'views/backup.js',
  settings:    'views/settings.js',
};

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

  /** 应用内直接下载新版本并替换（不再跳转 GitHub 页面） */
  downloadGUIUpdate() {
    UpdateUI.start('gui', 'Shield GUI');
  },

  /** 应用内直接下载 Shield CLI 新版本（直链/镜像）并替换 shield.exe */
  downloadShieldUpdate() {
    UpdateUI.start('shield', 'Shield CLI');
  },

  async checkForUpdates() {
    try {
      const res = await Shield.call('check_updates');
      if (!res) return;
      State.updateInfo = res;
      // GUI 更新按钮
      const guiBtn = document.getElementById('btn-gui-update');
      if (guiBtn && res.gui && res.gui.has_update) {
        guiBtn.textContent = `⬆ GUI v${res.gui.latest_version}`;
        guiBtn.title = `下载通道：GitHub 直链 + 镜像（${(res.mirrors || []).join(' / ') || '无'}）`;
        guiBtn.classList.remove('hidden');
      }
      // Shield CLI 更新按钮
      const shieldBtn = document.getElementById('btn-shield-update');
      if (shieldBtn && res.shield && res.shield.has_update) {
        shieldBtn.textContent = `⬆ CLI v${res.shield.latest_version}`;
        shieldBtn.title = `下载通道：GitHub 直链 + 镜像（${(res.mirrors || []).join(' / ') || '无'}）`;
        shieldBtn.classList.remove('hidden');
      }
      if (res.errors && res.errors.length) {
        console.warn('更新检测部分通道失败：', res.errors);
      }
    } catch (e) {
      // 静默失败，不影响主流程
      console.warn('update check failed', e);
    }
  }
};

// ---------- 更新进度条（后端 install_update 主动回调 UpdateUI.onProgress） ----------
const UpdateUI = {
  running: false,
  _hideTimer: null,

  start(target, label) {
    if (this.running) { toast('已有更新任务在进行中，请稍候…', 'info'); return; }
    this.running = true;
    this.label = label || '更新';
    this.show('正在连接更新通道…', 0, true);
    Shield.call('install_update', target).then(res => {
      if (!res || !res.started) {
        this.running = false;
        this.hide(true);
        toast((res && res.error) || '更新启动失败', 'error');
      }
    }).catch(e => {
      this.running = false;
      this.hide(true);
      toast('更新启动失败: ' + e.message, 'error');
    });
  },

  show(text, pct, indeterminate) {
    const wrap = document.getElementById('update-progress');
    if (!wrap) return;
    if (this._hideTimer) { clearTimeout(this._hideTimer); this._hideTimer = null; }
    wrap.classList.remove('hidden');
    wrap.classList.toggle('indeterminate', !!indeterminate);
    const bar = document.getElementById('update-progress-bar');
    const txt = document.getElementById('update-progress-text');
    if (bar) bar.style.width = Math.max(3, Math.min(100, pct || 0)) + '%';
    if (txt) txt.textContent = text || '';
  },

  hide(immediate) {
    const wrap = document.getElementById('update-progress');
    if (!wrap) return;
    if (immediate) {
      wrap.classList.add('hidden');
      wrap.classList.remove('indeterminate');
      return;
    }
    if (this._hideTimer) clearTimeout(this._hideTimer);
    this._hideTimer = setTimeout(() => wrap.classList.add('hidden'), 1800);
  },

  onProgress(d) {
    if (!d) return;
    const stage = d.stage || '';
    const msg = d.message || '';

    if (stage === 'error') {
      this.running = false;
      this.hide(true);
      toast(msg || '更新失败', 'error', 6000);
      return;
    }
    if (stage === 'up_to_date') {
      this.running = false;
      this.hide(true);
      toast(msg || '已是最新版本', 'info');
      return;
    }
    if (stage === 'done') {
      this.running = false;
      this.show(msg || '更新完成', 100, false);
      toast(msg || '更新完成', 'success', 6000);
      this.hide();
      setTimeout(refreshEnv, 600);
      if (d.manual && d.path) {
        confirmDialog('更新已下载', `${msg}\n\n是否打开文件所在文件夹？`)
          .then(ok => { if (ok) Shield.call('open_path', d.path); });
      }
      return;
    }
    // prepare / check / download / stop / extract / restore / replace / restart
    this.show(msg || '更新中…', d.percent || 0, false);
  }
};
window.UpdateUI = UpdateUI;

// ---------- 环境信息刷新（更新完成后刷新版本号显示） ----------
async function refreshEnv() {
  try {
    const env = await Shield.call('get_env');
    State.env = env || State.env;
    if (env && env.gui_version) {
      const el = document.getElementById('titlebar-version');
      if (el) el.textContent = 'v' + env.gui_version;
    }
    if (env && env.version) {
      const nav = document.getElementById('nav-version');
      if (nav) nav.textContent = env.version;
    }
  } catch (e) { /* 静默 */ }
}

// ---------- 全局状态 ----------
const State = {
  env: null,            // get_env() 返回值
  protocols: {},        // 协议元信息
  sessions: [],         // 活动会话（含 Web 面板会话）
  limits: null,         // 容量上限占用（多 10 个 / 并发 3）
  updateInfo: null,     // 最近一次 check_updates 结果
  pollTimer: null,      // 会话轮询定时器
  currentRoute: null,
  pendingPreset: null,  // 待填充的预设（内置常用端口预设用）
};

// ---------- 路由表 ----------
const ROUTES = {
  dashboard:  { title: '仪表盘',         subtitle: 'Shield 服务总览',     view: 'dashboard' },
  'tunnel-new': { title: '新建隧道',     subtitle: '创建一个新的安全隧道', view: 'tunnelNew' },
  presets:    { title: '连接预设',       subtitle: '保存与复用隧道配置',   view: 'presets' },
  sessions:   { title: '活动会话',       subtitle: '管理运行中的隧道',     view: 'sessions' },
  protocols:  { title: '协议指南',       subtitle: '8 种协议的用法',       view: 'protocols' },
  plugins:    { title: '插件管理',       subtitle: '扩展协议支持',         view: 'plugins' },
  service:    { title: '系统服务',       subtitle: '安装/启停/卸载',       view: 'service' },
  credentials:{ title: '凭证与安全',     subtitle: '凭证管理与访问模式',   view: 'credentials' },
  backup:     { title: '备份恢复',       subtitle: '本地/远程/定时备份',  view: 'backup' },
  settings:   { title: '应用配置',       subtitle: '自定义服务器/缓存',    view: 'settings' },
};

// ---------- 视图脚本自愈 ----------
/** 视图函数缺失时，带随机参数重新加载对应脚本，绕开 WebView2 的坏缓存副本。 */
function reloadViewScript(view) {
  const src = VIEW_SCRIPTS[view];
  if (!src) return Promise.resolve(false);
  return new Promise(resolve => {
    let done = false;
    const finish = ok => {
      if (done) return;
      done = true;
      resolve(ok && typeof Views[view] === 'function');
    };
    const s = document.createElement('script');
    s.src = src + '?reload=' + Date.now() + '_' + Math.floor(Math.random() * 100000);
    s.onload = () => finish(true);
    s.onerror = () => finish(false);
    document.head.appendChild(s);
    setTimeout(() => finish(false), 4000);
  });
}

// ---------- 路由导航 ----------
/** 启动时检查所有视图函数，缺失的脚本自动重载一次（绕开坏缓存 / 打包资源缺失）。 */
async function recoverViews() {
  const missing = Object.keys(VIEW_SCRIPTS).filter(v => typeof Views[v] !== 'function');
  if (!missing.length) return [];
  console.warn('[Shield GUI] 视图脚本未加载，尝试恢复:', missing.join(', '));
  const results = await Promise.all(missing.map(v => reloadViewScript(v)));
  const still = missing.filter((v, i) => !results[i]);
  try {
    if (still.length) {
      console.error('[Shield GUI] 恢复失败的视图:', still.join(', '));
      toast('部分页面资源未加载：' + still.join('、') + '，请重启程序', 'error');
    } else {
      toast('已自动恢复 ' + missing.length + ' 个页面脚本', 'success');
    }
  } catch { /* toast 容器尚未就绪时忽略 */ }
  return still;
}

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

  const render = () => {
    const fn = Views[meta.view];
    if (typeof fn !== 'function') {
      const err = new Error(`视图 ${meta.view} 未加载（${VIEW_SCRIPTS[meta.view] || '未知脚本'}）`);
      err.code = 'VIEW_MISSING';
      throw err;
    }
    return fn();
  };
  const mount = html => {
    if (html) {
      const wrap = document.createElement('div');
      wrap.className = 'view';
      wrap.innerHTML = html;
      root.appendChild(wrap);
    }
    // 调用挂载钩子（钩子出错不应把整页替换成错误卡片）
    const hookName = '_mount_' + route.replace(/-/g, '_');
    if (typeof Views[hookName] === 'function') {
      try { Views[hookName](); } catch (e) { console.error('mount hook failed', hookName, e); }
    }
  };
  const showError = e => {
    root.innerHTML = `<div class="alert alert-danger"><b>渲染错误</b><pre>${escapeHtml(String(e))}</pre></div>`;
    console.error(e);
  };

  try {
    mount(render());
  } catch (e) {
    if (!e || e.code !== 'VIEW_MISSING') {
      showError(e);
      return;
    }
    // 脚本没加载成功：自动重载一次，避免用户只看到一句 TypeError
    root.innerHTML = `<div class="alert alert-info"><b>正在恢复页面…</b><div class="text-sm">视图脚本未加载，正在重新加载 ${escapeHtml(VIEW_SCRIPTS[meta.view] || meta.view)}</div></div>`;
    reloadViewScript(meta.view).then(ok => {
      if (State.currentRoute !== route) return;  // 用户已切走，别覆盖新页面
      if (!ok) {
        root.innerHTML = `<div class="alert alert-danger"><b>页面资源缺失</b><pre>${escapeHtml(
          '未能加载 ' + (VIEW_SCRIPTS[meta.view] || meta.view) +
          '\n请重启程序；若仍失败，请用源码运行 python main.py，或重新打包 exe（WebView2 可能缓存了损坏的脚本）。'
        )}</pre></div>`;
        return;
      }
      try { mount(render()); } catch (e2) { showError(e2); }
    });
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
        <div class="modal-body">${escapeHtml(body).replace(/\n/g, '<br>')}</div>
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

/**
 * 启动隧道（统一处理启动前的网络预检）。
 * 预检失败时给出中文诊断并询问是否仍要启动，不硬拦用户。
 * 返回 { ok, res, cancelled }。
 */
async function startTunnelWithPreflight(params) {
  let res = await Shield.call('start_tunnel', params, false);
  if (res && res.need_confirm) {
    const d = res.diagnosis || {};
    const lines = [
      d.title || '控制台不可达',
      d.reason || '',
      '',
      '建议：',
      ...(d.advice || []).map(a => '· ' + a),
      '',
      '仍要启动隧道吗？（CLI 内部仍会自动重试 5 次）',
    ];
    const go = await confirmDialog('网络检测未通过', lines.join('\n'));
    if (!go) return { ok: false, cancelled: true, res };
    res = await Shield.call('start_tunnel', params, true);
  }
  if (!res || res.error) return { ok: false, cancelled: false, res };
  return { ok: true, cancelled: false, res };
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
    const [res, limits] = await Promise.all([
      Shield.call('list_sessions'),
      Shield.call('session_limits').catch(() => null),
    ]);
    State.sessions = Array.isArray(res) ? res : [];
    if (limits) State.limits = limits;
    // 更新导航徽章（运行中 / 并发上限）
    const badge = document.getElementById('nav-sessions-badge');
    const running = State.sessions.filter(s => s.status === 'running').length;
    if (running > 0) {
      badge.textContent = running;
      badge.classList.remove('hidden');
      badge.title = `运行中 ${running}/${(State.limits && State.limits.max_running) || 3}`;
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
  // 先自愈未加载的视图脚本，再绑定事件与渲染首个页面
  await recoverViews();

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
    // 面板里的应用会同步到「活动会话」，稍后刷新一次
    setTimeout(refreshSessions, 1500);
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
    // 移除底部配置目录提示（用户要求不要显示）
    const footer = document.getElementById('nav-footer');
    if (footer) footer.textContent = '';
  } catch (e) {
    console.error('boot env failed', e);
    toast('环境检测失败: ' + e.message, 'error');
  }

  navigate('dashboard');
  startSessionPolling();

  // 延迟检测更新（避免启动时并发请求过多）
  setTimeout(() => TitleBar.checkForUpdates(), 3000);
}

// 视图容器与 VIEW_SCRIPTS 已在文件顶部定义
document.addEventListener('DOMContentLoaded', boot);
