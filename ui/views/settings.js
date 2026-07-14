/* 应用配置视图 — 自定义服务器 / 默认参数 / 缓存 */
Views.settings = function () {
  return `
    <div class="view-header">
      <h1 class="view-title">应用配置</h1>
      <p class="view-desc">自定义 Shield 服务器、默认参数、缓存管理</p>
    </div>

    <div class="grid grid-2">
      <!-- 自定义服务器 -->
      <div class="card">
        <div class="card-header"><h3 class="card-title">🌍 自定义服务器</h3></div>
        <p class="text-secondary text-sm mb-4">
          默认连接公共服务 <code class="mono">console.yishield.com</code>。
          若部署了私有服务端，可在此指定。
        </p>
        <div class="form-row">
          <label class="form-label">API 服务器 URL ：<a href="https://console.yishield.com/enter" target="_blank" class="text-sm">控制台</a></label>
          <input class="input mono" id="set-server" placeholder="https://console.yishield.com/raas">
          <div class="form-hint">通过 <code class="mono">-H / --server</code> 参数传递</div>
        </div>
        <button class="btn btn-primary btn-sm" onclick="Views._saveSettings()">💾 保存</button>
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
    if (s.visable) document.getElementById('set-visable').value = s.visable;
    if (s.tunnel_port) document.getElementById('set-tunnelport').value = s.tunnel_port;
    document.getElementById('set-invisible').checked = !!s.invisible;
    document.getElementById('set-verbose').checked = !!s.verbose;
    document.getElementById('set-autostart-sessions').checked = !!s.autostart_sessions;
    // tray_enabled 默认 true，只有明确 false 才取消勾选
    const trayEl = document.getElementById('set-tray-enabled');
    if (s.tray_enabled === false) trayEl.checked = false;
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
    visable: document.getElementById('set-visable').value.trim(),
    tunnel_port: document.getElementById('set-tunnelport').value.trim(),
    invisible: document.getElementById('set-invisible').checked,
    verbose: document.getElementById('set-verbose').checked,
    autostart_sessions: document.getElementById('set-autostart-sessions').checked,
    tray_enabled: document.getElementById('set-tray-enabled').checked,
  };
  const ok = await Shield.call('save_settings', settings);
  toast(ok ? '设置已保存' : '保存失败', ok ? 'success' : 'error');
};

Views._clearCreds = async function () {
  const ok = await confirmDialog('清除凭证缓存', '将清除本地缓存的凭证，确定？');
  if (!ok) return;
  const res = await Shield.call('clean_credentials');
  toast('缓存已清除', 'success');
};
