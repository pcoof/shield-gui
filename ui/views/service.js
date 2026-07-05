/* 系统服务视图 */
Views.service = function () {
  return `
    <div class="view-header">
      <h1 class="view-title">系统服务管理</h1>
      <p class="view-desc">将 Shield 安装为 Windows 服务，随系统自动启动；也可直接启动 Web UI</p>
    </div>

    <div class="grid grid-2 mb-4">
      <div class="card">
        <div class="card-header"><h3 class="card-title">📡 服务状态</h3></div>
        <div id="svc-status"><div class="text-muted text-sm">检测中…</div></div>
        <button class="btn btn-sm mt-4" onclick="Views._checkService()">🔄 重新检测</button>
      </div>

      <div class="card">
        <div class="card-header"><h3 class="card-title">🌐 Web UI 模式</h3></div>
        <p class="text-secondary text-sm mb-4">在本地后台启动 Shield 官方 Web 管理面板，长期运行不关闭。</p>
        <div class="form-row">
          <label class="form-label">Web UI 端口</label>
          <input class="input mono" id="webui-port" type="number" value="8181">
        </div>
        <div id="webui-status" class="mb-2"></div>
        <div class="flex gap-2">
          <button class="btn btn-primary btn-sm" onclick="Views._startWebUI()">🚀 启动</button>
          <button class="btn btn-sm" onclick="Views._openWebUI()">🌐 打开浏览器</button>
          <button class="btn btn-sm btn-danger" onclick="Views._stopWebUI()">⏹ 停止</button>
          <button class="btn btn-sm btn-ghost" onclick="Views._checkWebUIStatus()">🔄 刷新状态</button>
        </div>
        <div id="webui-output" class="mt-2"></div>
      </div>
    </div>

    <div class="card mb-4">
      <div class="card-header"><h3 class="card-title">⚙️ 服务安装 / 卸载</h3></div>
      <div class="alert alert-info mb-4">
        <span>ℹ</span>
        <div>
          <b>Windows 服务说明</b><br>
          <span class="text-sm">安装为 Windows 服务后，Shield 会在系统启动时自动运行，Web UI 持续可用。<b>安装操作需要管理员权限</b>。</span>
        </div>
      </div>
      <div class="form-row">
        <label class="form-label">服务端口</label>
        <input class="input mono" id="svc-port" type="number" value="8181" style="max-width:200px">
      </div>
      <div class="flex gap-3 mt-2">
        <button class="btn btn-primary" onclick="Views._installService()">📦 安装服务</button>
        <button class="btn btn-danger" onclick="Views._uninstallService()">🗑 卸载服务</button>
        <button class="btn" onclick="Views._stopService()">⏹ 停止服务</button>
      </div>
      <div id="svc-output" class="mt-4"></div>
    </div>

    <div class="card">
      <div class="card-header"><h3 class="card-title">📖 三种使用模式对比</h3></div>
      <table class="table">
        <thead><tr><th>模式</th><th>启动命令</th><th>适用场景</th><th>特性</th></tr></thead>
        <tbody>
          <tr>
            <td><span class="badge badge-accent">推荐</span> Web UI</td>
            <td class="mono text-sm">shield start [port]</td>
            <td>日常使用、多应用管理</td>
            <td class="text-secondary text-sm">图形面板、加密存储、最多 10 个应用</td>
          </tr>
          <tr>
            <td><span class="badge badge-info">灵活</span> 命令行</td>
            <td class="mono text-sm">shield &lt;protocol&gt; [target]</td>
            <td>一次性连接、脚本自动化</td>
            <td class="text-secondary text-sm">即开即用、返回 Access URL</td>
          </tr>
          <tr>
            <td><span class="badge badge-muted">常驻</span> 系统服务</td>
            <td class="mono text-sm">shield install --port &lt;n&gt;</td>
            <td>长期访问、无人值守</td>
            <td class="text-secondary text-sm">随系统启动、持续运行</td>
          </tr>
        </tbody>
      </table>
      <div class="mt-4">
        <div class="text-muted text-xs mb-2">相关命令</div>
        <div class="cmd-preview mb-2">shield start                      # 启动服务或前台 Web UI（端口 8181）</div>
        <div class="cmd-preview mb-2">shield start 9090                 # 前台运行于端口 9090</div>
        <div class="cmd-preview mb-2">shield start --no-tray            # 前台运行，不显示托盘图标</div>
        <div class="cmd-preview mb-2">shield install --port 8182        # 安装为服务（端口 8182）</div>
        <div class="cmd-preview mb-2">shield stop                       # 停止后台服务</div>
        <div class="cmd-preview">shield uninstall                  # 卸载系统服务（保留配置）</div>
      </div>
    </div>
  `;
};

Views._mount_service = function () {
  Views._checkService();
  Views._checkWebUIStatus();
};

Views._checkService = async function () {
  const el = document.getElementById('svc-status');
  if (!el) return;
  el.innerHTML = '<div class="text-muted text-sm">检测中…</div>';
  try {
    const s = await Shield.call('service_status');
    if (s.error) {
      el.innerHTML = `<div class="alert alert-warning"><span>⚠</span><div>状态检测失败：${escapeHtml(s.error)}</div></div>`;
      return;
    }
    if (!s.installed) {
      el.innerHTML = `
        <div class="alert alert-warning">
          <span>⚪</span>
          <div><b>未安装为系统服务</b><br>
            <span class="text-sm">可点击下方「安装服务」将其注册为 Windows 服务。</span></div>
        </div>`;
      return;
    }
    el.innerHTML = `
      <div class="alert alert-${s.running ? 'success' : 'info'}">
        <span>${s.running ? '🟢' : '🟡'}</span>
        <div>
          <b>${s.running ? '服务运行中' : '服务已安装但未运行'}</b><br>
          <span class="text-sm mono">服务名: ShieldCLI · 状态: ${s.running ? 'RUNNING' : 'STOPPED'}</span>
        </div>
      </div>`;
  } catch (e) {
    el.innerHTML = `<div class="alert alert-danger">检测失败: ${escapeHtml(e.message)}</div>`;
  }
};

Views._installService = async function () {
  const port = parseInt(document.getElementById('svc-port').value) || 8181;
  const ok = await confirmDialog('安装系统服务',
    `将安装 Shield 为 Windows 服务（端口 ${port}），此操作需要管理员权限。继续？`);
  if (!ok) return;
  Views._setSvcOutput('正在安装服务…', 'info');
  const res = await Shield.call('service_install', port);
  const out = (res.stdout || '') + (res.stderr || '');
  Views._setSvcOutput(out || '（无输出）', res.code === 0 ? 'success' : 'warning');
  Views._checkService();
};

Views._uninstallService = async function () {
  const ok = await confirmDialog('卸载系统服务', '将停止并移除 Shield 系统服务（配置与凭证保留）。继续？');
  if (!ok) return;
  Views._setSvcOutput('正在卸载服务…', 'info');
  const res = await Shield.call('service_uninstall');
  const out = (res.stdout || '') + (res.stderr || '');
  Views._setSvcOutput(out || '（无输出）', res.code === 0 ? 'success' : 'warning');
  Views._checkService();
};

Views._stopService = async function () {
  Views._setSvcOutput('正在停止服务…', 'info');
  const res = await Shield.call('service_stop');
  const out = (res.stdout || '') + (res.stderr || '');
  Views._setSvcOutput(out || '（无输出）', 'success');
  Views._checkService();
};

Views._checkWebUIStatus = async function () {
  const el = document.getElementById('webui-status');
  if (!el) return;
  try {
    const res = await Shield.call('web_ui_status');
    if (res.running) {
      el.innerHTML = `<div class="alert alert-success" style="padding:var(--sp-2) var(--sp-3)"><span>🟢</span><div><b>Web UI 运行中</b><span class="text-xs text-muted" style="margin-left:8px">PID ${res.pid}</span></div></div>`;
    } else {
      el.innerHTML = `<div class="alert alert-muted" style="padding:var(--sp-2) var(--sp-3)"><span>⚪</span><div><b>Web UI 未启动</b><span class="text-xs text-muted" style="margin-left:8px">${res.message || ''}</span></div></div>`;
    }
  } catch {
    el.innerHTML = `<div class="alert alert-warning" style="padding:var(--sp-2) var(--sp-3)"><span>⚠</span><div>状态检测失败</div></div>`;
  }
};

Views._startWebUI = async function () {
  const port = parseInt(document.getElementById('webui-port').value) || 8181;
  const btn = document.querySelectorAll('.card button')[3]; // 启动按钮
  if (btn) { btn.disabled = true; btn.textContent = '⏳ 启动中…'; }
  try {
    const res = await Shield.call('start_web_ui', port);
    const initial = res.initial_output || '';
    const el = document.getElementById('webui-output');
    if (el) {
      el.innerHTML = `<div class="terminal" style="max-height:120px;user-select:text">${escapeHtml(initial || res.message || res.error || '（无输出）')}</div>`;
    }
    if (res.code === 0 && !res.error) {
      toast(`Web UI 已启动于端口 ${port}（PID ${res.pid}）`, 'success');
      Views._checkWebUIStatus();
      // 自动打开浏览器
      setTimeout(() => Views._openWebUI(), 800);
    } else if (res.already_running) {
      toast('Web UI 已在运行', 'info');
      Views._checkWebUIStatus();
      setTimeout(() => Views._openWebUI(), 500);
    } else {
      toast('启动失败: ' + (res.error || '未知错误'), 'error');
    }
  } catch (e) {
    toast('启动出错: ' + e.message, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '🚀 启动'; }
  }
};

Views._stopWebUI = async function () {
  const ok = await confirmDialog('停止 Web UI', '将停止后台运行的 Web UI 进程，确定？');
  if (!ok) return;
  try {
    const res = await Shield.call('stop_web_ui');
    if (res.ok) {
      toast('Web UI 已停止', 'success');
    } else {
      toast(res.message || 'Web UI 未运行', 'info');
    }
    Views._checkWebUIStatus();
  } catch (e) {
    toast('停止出错: ' + e.message, 'error');
  }
};

Views._openWebUI = async function () {
  const port = parseInt(document.getElementById('webui-port').value) || 8181;
  const ok = await Shield.call('open_web_ui', port);
  toast(ok ? `已打开 http://localhost:${port}` : '打开失败，请先启动服务', ok ? 'success' : 'error');
};

Views._setSvcOutput = function (text, type) {
  const el = document.getElementById('svc-output');
  if (!el) return;
  el.innerHTML = `<div class="terminal" style="max-height:180px;user-select:text">${escapeHtml(text)}</div>`;
};
