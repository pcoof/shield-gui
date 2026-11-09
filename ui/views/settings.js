/* 应用配置视图 — 自定义服务器 / 网络诊断 / 默认参数 / 缓存 */
Views.settings = function () {
  return `
    <div class="view-header">
      <h1 class="view-title">应用配置</h1>
      <p class="view-desc">自定义 Shield 服务器、网络与代理、启动重试策略、缓存管理</p>
    </div>

    <div class="grid grid-2">
      <!-- 自定义服务器 -->
      <div class="card">
        <div class="card-header"><h3 class="card-title">🌍 自定义服务器</h3></div>
        <p class="text-secondary text-sm mb-4">
          默认连接公共服务 <code class="mono">console.yishield.com</code>。
          此处保存的地址会作为<b>所有新建隧道</b>的默认 <span class="mono">--server</span>
          （新建隧道表单里单独填写时以表单为准）。
        </p>
        <div class="form-row">
          <label class="form-label">API 服务器 URL ：<a href="https://console.yishield.com/enter" target="_blank" class="text-sm">控制台</a></label>
          <input class="input mono" id="set-server" placeholder="https://console.yishield.com/raas">
          <div class="form-hint">通过 <code class="mono">-H / --server</code> 参数传递；留空使用官方默认地址</div>
        </div>
        <button class="btn btn-primary btn-sm" onclick="Views._saveSettings()">💾 保存</button>
      </div>

      <!-- 网络与连接 -->
      <div class="card">
        <div class="card-header"><h3 class="card-title">🔌 网络与连接</h3></div>
        <p class="text-secondary text-sm mb-4">
          每次启动隧道都要调用控制台 <span class="mono">quick-setup</span> 接口。
          链路不通时会出现响应超时；此处可指定代理（通过环境变量传给 shield CLI）。
        </p>
        <div class="form-row">
          <label class="form-label">HTTP 代理（留空沿用系统代理）</label>
          <input class="input mono" id="set-proxy" placeholder="http://127.0.0.1:7890">
          <div class="form-hint">支持 <span class="mono">http://</span> / <span class="mono">socks5://</span>；本地回环与 Web 面板自动绕过</div>
        </div>
        <div class="form-row">
          <label class="checkbox">
            <input type="checkbox" id="set-preflight" checked>
            启动前检测控制台连通性（失败时提示，可仍要启动）
          </label>
        </div>
        <div class="form-row">
          <label class="form-label">超时失败后自动重试次数</label>
          <select class="input" id="set-retry">
            <option value="0">不自动重试</option>
            <option value="1" selected>1 次（推荐）</option>
            <option value="2">2 次</option>
            <option value="3">3 次</option>
          </select>
          <div class="form-hint">仅对超时 / 服务端 5xx 等可恢复错误生效，也可在会话里手动重试</div>
        </div>
        <div class="flex gap-2 mt-3">
          <button class="btn btn-primary btn-sm" onclick="Views._saveSettings()">💾 保存</button>
          <button class="btn btn-sm" onclick="Views._testNetwork()">🔌 测试连接</button>
        </div>
        <div id="net-probe-result" class="mt-3"></div>
      </div>

      <!-- 默认 AC 节点 -->
      <div class="card">
        <div class="card-header"><h3 class="card-title">🌐 默认 AC 节点</h3></div>
        <p class="text-secondary text-sm mb-4">
          指定默认的访问节点（区域），影响 Access URL 的就近性。
        </p>
        <div class="form-row">
          <label class="form-label">visable 节点过滤</label>
          <input class="input mono" id="set-visable" value="visable" placeholder="visable / HK / US ...">
        </div>
        <div class="form-row">
          <label class="form-label">默认隧道端口</label>
          <input class="input mono" id="set-tunnelport" type="number" placeholder="62888">
        </div>
        <button class="btn btn-primary btn-sm" onclick="Views._saveSettings()">💾 保存</button>
      </div>

      <!-- 行为偏好 -->
      <div class="card">
        <div class="card-header"><h3 class="card-title">⚙️ 行为偏好</h3></div>
        <div style="display:flex;flex-direction:column;gap:var(--sp-3);margin-top:var(--sp-2)">
          <label class="checkbox">
            <input type="checkbox" id="set-invisible">
            默认启用隐身模式（--invisible）
          </label>
          <label class="checkbox">
            <input type="checkbox" id="set-verbose">
            默认详细日志（-v）
          </label>
          <label class="checkbox">
            <input type="checkbox" id="set-autostart-sessions">
            启动后自动恢复活动会话
          </label>
          <label class="checkbox">
            <input type="checkbox" id="set-tray-enabled" checked>
            启用系统托盘（关闭窗口时隐藏到托盘）
          </label>
        </div>
        <button class="btn btn-primary btn-sm mt-4" onclick="Views._saveSettings()">💾 保存</button>
      </div>

      <!-- 更新通道 -->
      <div class="card">
        <div class="card-header"><h3 class="card-title">🔄 更新通道</h3></div>
        <p class="text-secondary text-sm mb-4">
          更新不再跳转 GitHub 页面：直接下载 Release 直链，并自动测速选择最快镜像；
          GUI 下载完成后自替换并重启，CLI 下载 zip 后替换 <span class="mono">shield.exe</span>。
        </p>
        <div class="form-row">
          <label class="form-label">镜像前缀（每行一个，留空恢复默认）</label>
          <textarea class="input mono" id="set-mirrors" rows="3"
                    placeholder="https://ghproxy.net/&#10;https://v4.gh-proxy.org/"></textarea>
          <div class="form-hint">
            拼在 GitHub 直链前，例如 <span class="mono">https://ghproxy.net/https://github.com/...</span>
          </div>
        </div>
        <div class="flex gap-2" style="flex-wrap:wrap">
          <button class="btn btn-primary btn-sm" onclick="Views._saveMirrors()">💾 保存镜像</button>
          <button class="btn btn-sm" onclick="Views._checkUpdatesNow()">🔍 检查更新</button>
          <button class="btn btn-sm btn-info" onclick="TitleBar.downloadGUIUpdate()">⬆ 更新 GUI</button>
          <button class="btn btn-sm" onclick="TitleBar.downloadShieldUpdate()">⬆ 更新 CLI</button>
        </div>
        <div id="update-check-result" class="mt-3"></div>
        <div class="form-hint mt-3" style="line-height:1.7">
          注意：更新 Shield CLI 时会先<b>结束所有 shield.exe 进程</b>（隧道、Web 面板、
          系统托盘、Windows 服务），确认目标文件解除占用后才替换，避免替换失败或
          内存里仍跑旧版本。完成后按原端口自动重启 Web 面板并恢复之前的会话
          （受 3 个并发上限约束）；旧版本保留为 <span class="mono">shield.exe.bak</span>，
          新版本校验不通过会自动回滚。
        </div>
      </div>

      <!-- 会话容量 -->
      <div class="card">
        <div class="card-header"><h3 class="card-title">📊 会话容量</h3></div>
        <table class="table">
          <tr><td class="text-muted">同时连接</td><td>最多 <b>3</b> 个（运行中 + 启动中）</td></tr>
          <tr><td class="text-muted">活动会话</td><td>最多 <b>10</b> 个（桌面 + Web 面板应用）</td></tr>
          <tr><td class="text-muted">当前占用</td><td id="set-limits">—</td></tr>
          <tr><td class="text-muted">Web 面板</td><td id="set-webinfo">—</td></tr>
        </table>
        <div class="form-row mt-2">
          <label class="form-label">Web 面板端口（用于同步面板里的应用）</label>
          <div class="input-group">
            <input class="input mono" id="set-webport" type="number" value="8181">
            <button class="btn" onclick="Views._saveSettings()">保存</button>
          </div>
        </div>
        <div class="alert alert-info mt-2">
          <span>ℹ</span>
          <div class="text-sm">
            在 <span class="mono">http://localhost:8181/</span> 添加的应用会自动出现在「活动会话」，
            并与桌面端共用同一份 3 并发 / 10 会话额度。
          </div>
        </div>
      </div>

      <!-- 缓存管理 -->
      <div class="card">
        <div class="card-header"><h3 class="card-title">🧹 缓存管理</h3></div>
        <p class="text-secondary text-sm mb-4">Shield 在本地缓存连接会话、Access URL、临时凭证。</p>
        <div class="flex gap-2">
          <button class="btn btn-danger btn-sm" onclick="Views._clearCreds()">🧹 清除凭证缓存</button>
        </div>
        <div class="alert alert-info mt-4">
          <span>ℹ</span>
          <div class="text-sm">
            <b>清除范围：</b>仅清除本地缓存的凭证与会话记录，不会删除保存的连接预设。
          </div>
        </div>
      </div>
    </div>

    <!-- 关于 -->
    <div class="card mt-4">
      <div class="card-header"><h3 class="card-title">ℹ️ 关于 Shield GUI</h3></div>
      <table class="table">
        <tr><td class="text-muted">GUI 版本</td><td class="mono" id="about-gui">—</td></tr>
        <tr><td class="text-muted">Shield CLI</td><td class="mono" id="about-shield">—</td></tr>
        <tr><td class="text-muted">可执行文件</td><td class="mono text-sm" id="about-path">—</td></tr>
        <tr><td class="text-muted">配置目录</td><td class="mono text-sm" id="about-cfg">—</td></tr>
        <tr><td class="text-muted">技术栈</td><td>Python 3 + pywebview + 原生 HTML/CSS/JS</td></tr>
        <tr><td class="text-muted">官方文档</td><td><a href="https://docs.yishield.com" class="copyable" target="_blank">https://docs.yishield.com</a></td></tr>
      </table>
    </div>
  `;
};

Views._mount_settings = async function () {
  // 加载已保存的设置
  try {
    const s = await Shield.call('load_settings');
    if (s.server) document.getElementById('set-server').value = s.server;
    if (s.proxy) document.getElementById('set-proxy').value = s.proxy;
    const pfEl = document.getElementById('set-preflight');
    if (pfEl) pfEl.checked = s.preflight !== false;
    const retryEl = document.getElementById('set-retry');
    if (retryEl) retryEl.value = String(s.auto_retry == null ? 1 : s.auto_retry);
    if (s.visable) document.getElementById('set-visable').value = s.visable;
    if (s.tunnel_port) document.getElementById('set-tunnelport').value = s.tunnel_port;
    document.getElementById('set-invisible').checked = !!s.invisible;
    document.getElementById('set-verbose').checked = !!s.verbose;
    document.getElementById('set-autostart-sessions').checked = !!s.autostart_sessions;
    // tray_enabled 默认 true，只有明确 false 才取消勾选
    const trayEl = document.getElementById('set-tray-enabled');
    if (s.tray_enabled === false) trayEl.checked = false;
    if (s.web_ui_port) document.getElementById('set-webport').value = s.web_ui_port;
  } catch {}
  // 更新通道配置
  try {
    const cfg = await Shield.call('get_update_config');
    const ta = document.getElementById('set-mirrors');
    if (ta) ta.value = (cfg.mirrors || []).join('\n');
  } catch {}
  // 会话容量 + Web 面板状态
  try {
    const lim = await Shield.call('session_limits');
    if (lim) {
      State.limits = lim;
      const a = document.getElementById('set-limits');
      if (a) a.innerHTML = `并发 <b class="mono">${lim.running}/${lim.max_running}</b> · 会话 <b class="mono">${lim.sessions}/${lim.max_sessions}</b>
        <span class="text-muted text-xs">（桌面 ${lim.gui_sessions} / Web ${lim.web_sessions}）</span>`;
      const b = document.getElementById('set-webinfo');
      if (b) b.innerHTML = lim.web_ui_online
        ? `<span class="badge badge-success">已连接</span> <span class="mono text-sm">${escapeHtml(lim.web_ui_url)}</span>`
        : `<span class="badge badge-muted">未运行</span> <span class="text-muted text-xs">端口 ${lim.web_ui_port}</span>`;
    }
  } catch {}
  // 填充关于信息
  if (State.env) {
    const guiVer = State.env.gui_version || '1.0.0';
    document.getElementById('about-gui').textContent = guiVer;
    document.getElementById('about-shield').textContent = State.env.version || '—';
    document.getElementById('about-path').textContent = State.env.path || '—';
    document.getElementById('about-cfg').textContent = State.env.config?.effective_dir || '—';
  }
};

Views._saveSettings = async function () {
  const settings = {
    server: document.getElementById('set-server').value.trim(),
    proxy: document.getElementById('set-proxy').value.trim(),
    preflight: document.getElementById('set-preflight').checked,
    auto_retry: parseInt(document.getElementById('set-retry').value, 10) || 0,
    visable: document.getElementById('set-visable').value.trim(),
    tunnel_port: document.getElementById('set-tunnelport').value.trim(),
    invisible: document.getElementById('set-invisible').checked,
    verbose: document.getElementById('set-verbose').checked,
    autostart_sessions: document.getElementById('set-autostart-sessions').checked,
    tray_enabled: document.getElementById('set-tray-enabled').checked,
  };
  const wp = document.getElementById('set-webport');
  if (wp && wp.value) {
    const port = parseInt(wp.value, 10);
    if (port >= 1 && port <= 65535) settings.web_ui_port = port;
  }
  const ok = await Shield.call('save_settings', settings);
  toast(ok ? '设置已保存' : '保存失败', ok ? 'success' : 'error');
};

/* ---------- 网络连通性测试 ---------- */
Views._testNetwork = async function () {
  const el = document.getElementById('net-probe-result');
  const srvEl = document.getElementById('set-server');
  const pxEl = document.getElementById('set-proxy');
  const srv = srvEl ? srvEl.value.trim() : '';
  const px = pxEl ? pxEl.value.trim() : '';
  if (el) el.innerHTML = '<div class="text-muted text-sm">正在检测 DNS / TCP / TLS / HTTP …（最多 6 秒）</div>';
  try {
    const r = await Shield.call('probe_server', srv, px);
    if (!r) { if (el) el.innerHTML = '<div class="text-danger text-sm">检测无返回</div>'; return; }
    const row = (label, ms) => ms == null ? '' :
      `<tr><td class="text-muted">${label}</td><td class="mono">${ms} ms</td></tr>`;
    const advice = (r.advice || []).length
      ? `<div class="diag-advice mt-2"><b>建议：</b><ol>${r.advice.map(a => `<li>${escapeHtml(a)}</li>`).join('')}</ol></div>`
      : '';
    if (el) el.innerHTML = `
      <div class="alert ${r.ok ? 'alert-success' : 'alert-danger'}">
        <span>${r.ok ? '✓' : '✕'}</span>
        <div class="text-sm">
          <b>${escapeHtml(r.message || '')}</b>
          <div class="text-xs mt-2">${escapeHtml(r.server || '')}
            · ${r.via === 'proxy' ? '经代理' : '直连'}
            · 阶段：${escapeHtml(r.stage_label || '—')}
            ${r.http_code ? `· HTTP ${r.http_code}` : ''}</div>
        </div>
      </div>
      <table class="table mt-2">
        ${row('DNS 解析', r.dns_ms)}${row('TCP 连接', r.connect_ms)}
        ${row('TLS 握手', r.tls_ms)}${row('HTTP 响应', r.http_ms)}
        <tr><td class="text-muted">总耗时</td><td class="mono">${r.elapsed_ms} ms</td></tr>
      </table>
      ${advice}
      ${r.detail ? `<div class="text-xs text-muted mono mt-2" style="word-break:break-all">${escapeHtml(r.detail)}</div>` : ''}`;
    toast(r.ok ? '控制台可达' : '控制台不可达，请查看诊断建议', r.ok ? 'success' : 'warning');
  } catch (e) {
    if (el) el.innerHTML = `<div class="alert alert-danger"><span>✕</span><div>${escapeHtml(e.message)}</div></div>`;
  }
};

/* ---------- 更新通道 ---------- */
Views._saveMirrors = async function () {
  const ta = document.getElementById('set-mirrors');
  const lines = (ta ? ta.value : '').split(/\r?\n/).map(s => s.trim()).filter(Boolean);
  const res = await Shield.call('save_update_mirrors', lines);
  if (res && res.ok) {
    toast('镜像已保存：' + (res.mirrors || []).join(' · '), 'success');
    refreshEnv();
  } else {
    toast('镜像保存失败', 'error');
  }
};

Views._checkUpdatesNow = async function () {
  const el = document.getElementById('update-check-result');
  if (el) el.innerHTML = '<div class="text-muted text-sm">正在检测（GitHub 直连 / 镜像 / 重定向）…</div>';
  try {
    const res = await Shield.call('check_updates');
    State.updateInfo = res;
    if (!res) { if (el) el.innerHTML = '<div class="text-danger text-sm">检测无返回</div>'; return; }
    const row = (key, label) => {
      const i = res[key] || {};
      return `<tr>
        <td class="text-muted">${label}</td>
        <td class="mono text-sm">${escapeHtml(i.current_version || '—')}</td>
        <td class="mono text-sm">${escapeHtml(i.latest_version || '—')}</td>
        <td>${i.has_update
          ? '<span class="badge badge-warning">可更新</span>'
          : '<span class="badge badge-success">已最新</span>'}</td>
        <td class="text-muted text-xs">${escapeHtml(i.via || '—')}</td>
      </tr>`;
    };
    let html = `
      <table class="table">
        <thead><tr><th>组件</th><th>当前</th><th>最新</th><th>状态</th><th>通道</th></tr></thead>
        <tbody>${row('gui', 'Shield GUI')}${row('shield', 'Shield CLI')}</tbody>
      </table>
      <div class="text-muted text-xs mt-2">镜像前缀：${(res.mirrors || []).map(m => escapeHtml(m)).join(' · ') || '无'}</div>`;
    if (res.errors && res.errors.length) {
      html += `<div class="alert alert-warning mt-2"><span>⚠</span>
        <div class="text-xs">${res.errors.map(e => escapeHtml(e)).join('<br>')}</div></div>`;
    }
    if (el) el.innerHTML = html;
    // 顺带刷新标题栏更新按钮
    if (typeof TitleBar.checkForUpdates === 'function') TitleBar.checkForUpdates();
  } catch (e) {
    if (el) el.innerHTML = `<div class="alert alert-danger"><span>✕</span><div>${escapeHtml(e.message)}</div></div>`;
  }
};

Views._clearCreds = async function () {
  const ok = await confirmDialog('清除凭证缓存', '将清除本地缓存的凭证，确定？');
  if (!ok) return;
  const res = await Shield.call('clean_credentials');
  toast('缓存已清除', 'success');
};
