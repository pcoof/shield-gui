/* 仪表盘视图 */
Views.dashboard = function () {
  const env = State.env || {};
  const cfg = env.config || {};
  const running = (State.sessions || []).filter(s => s.status === 'running').length;
  const total = (State.sessions || []).length;

  return `
    <div class="view-header">
      <h1 class="view-title">欢迎使用 Shield GUI</h1>
      <p class="view-desc">安全隧道连接器 · 把内网服务暴露到公网，浏览器即可访问</p>
    </div>

    ${env.installed ? '' : `
      <div class="alert alert-danger mb-4">
        <span class="alert-icon">✕</span>
        <div>
          <b>未检测到 Shield CLI</b><br>
          <span class="text-sm">请先安装 Shield CLI 后再使用本工具。下方提供了多种安装方式。</span>
        </div>
      </div>
    `}

    ${!env.installed ? `
    <!-- ===== CLI 未安装：安装向导 ===== -->
    <div class="grid grid-2 mb-4">
      <div class="card">
        <div class="card-header"><h3 class="card-title">⬇️ 一键安装</h3></div>
        <div style="display:flex;flex-direction:column;gap:var(--sp-3)">
          <button class="btn btn-primary btn-block" onclick="Views._installFromGitHub()">
            📦 从 GitHub Release 自动安装
          </button>
          <p class="text-xs text-secondary" style="margin:0">
            下载 <span class="mono">shield-windows-amd64.zip</span> 并解压到 <span class="mono">C:\\Program Files\\ShieldCLI\\</span>
          </p>
          <div style="padding-top:var(--sp-3);border-top:1px solid var(--border)">
            <button class="btn btn-block" onclick="Views._installFromBat()">
              ⚙️ 通过 install.bat 自动安装
            </button>
            <p class="text-xs text-secondary" style="margin:0">
              运行官方安装脚本，自动下载安装到 <span class="mono">C:\\Program Files\\ShieldCLI\\shield.exe</span>
            </p>
          </div>
          <div id="install-progress" class="mt-2"></div>
        </div>
      </div>
      <div class="card">
        <div class="card-header"><h3 class="card-title">📦 包管理器 / 手动</h3></div>
        <div style="display:flex;flex-direction:column;gap:var(--sp-2)">
          <div class="cmd-preview text-sm">winget install yishield.shieldcli</div>
          <p class="text-xs text-secondary" style="margin:0">通过 winget 包管理器安装（需要 Windows 10 1709+）</p>
          <div class="cmd-preview text-sm">scoop bucket add yishield https://github.com/yishield/scoop-bucket && scoop install shield</div>
          <p class="text-xs text-secondary" style="margin:0">通过 Scoop 包管理器安装</p>
          <div class="cmd-preview text-sm">choco install shieldcli</div>
          <p class="text-xs text-secondary" style="margin:0">通过 Chocolatey 包管理器安装</p>
          <div style="padding-top:var(--sp-3);border-top:1px solid var(--border)">
            <button class="btn btn-block" onclick="Shield.call('open_web_ui', 0); toast('已打开官方下载页', 'info')">
              🌐 从官方网站下载
            </button>
            <p class="text-xs text-secondary" style="margin:0">
              访问 <span class="mono">https://www.yishield.com/download</span> 手动下载
            </p>
          </div>
          <div style="padding-top:var(--sp-3);border-top:1px solid var(--border)">
            <button class="btn btn-block" onclick="location.reload()">
              🔄 重新检测
            </button>
            <p class="text-xs text-secondary" style="margin:0">
              安装完成后点击此处重新检测 shield.exe
            </p>
          </div>
        </div>
      </div>
    </div>
    ` : `
    <div class="grid grid-4 mb-4">
      <div class="stat">
        <div class="stat-icon" style="background:var(--accent-muted);color:var(--accent)">🛡</div>
        <div class="stat-value">${env.version ? env.version.replace(/^shield version /i, '') : '—'}</div>
        <div class="stat-label">Shield 版本</div>
      </div>
      <div class="stat">
        <div class="stat-icon" style="background:var(--success-muted);color:var(--success)">🟢</div>
        <div class="stat-value">${running}</div>
        <div class="stat-label">活动隧道</div>
      </div>
      <div class="stat">
        <div class="stat-icon" style="background:var(--info-muted);color:var(--info)">📋</div>
        <div class="stat-value" id="stat-presets">—</div>
        <div class="stat-label">已存预设</div>
      </div>
      <div class="stat">
        <div class="stat-icon" style="background:var(--warning-muted);color:var(--warning)">🧩</div>
        <div class="stat-value" id="stat-plugins">—</div>
        <div class="stat-label">已装插件</div>
      </div>
    </div>

    <div class="grid grid-2 mb-4">
      <div class="card">
        <div class="card-header"><h3 class="card-title">🚀 快速开始</h3></div>
        <div style="display:flex;flex-direction:column;gap:var(--sp-3)">
          <button class="btn btn-primary btn-block" onclick="navigate('tunnel-new')">
            ⚡ 新建隧道（命令行模式）
          </button>
          <button class="btn btn-block" onclick="navigate('presets')">
            📑 从预设启动
          </button>
          <button class="btn btn-block" onclick="navigate('service')">
            ⚙️ 启动 Web UI / 安装系统服务
          </button>
        </div>
      </div>

      <div class="card">
        <div class="card-header"><h3 class="card-title">🔍 环境信息</h3></div>
        <table class="table">
          <tr><td class="text-muted">可执行文件</td><td class="mono text-sm">${escapeHtml(env.path || '—')}</td></tr>
          <tr><td class="text-muted">配置目录</td>
              <td class="mono text-sm">${escapeHtml(cfg.effective_dir || '—')}
                ${cfg.needs_trigger ? '<span class="badge badge-warning" style="margin-left:8px">待生成</span>' : ''}
              </td></tr>
          <tr><td class="text-muted">存储模式</td>
              <td>${cfg.official_dir ? '<span class="badge badge-success">官方目录</span>' : '<span class="badge badge-warning">JSON 兜底</span>'}</td></tr>
          <tr><td class="text-muted">支持协议</td>
              <td>${Object.keys(State.protocols).map(p=>`<span class="badge badge-muted" style="margin-right:4px">${p}</span>`).join('')}</td></tr>
        </table>
      </div>
    </div>
    `}

    <div class="card">
      <div class="card-header">
        <h3 class="card-title">📖 三种使用模式</h3>
      </div>
      <div class="grid grid-3">
        <div>
          <div class="badge badge-accent mb-2">推荐</div>
          <h4 style="margin:0 0 var(--sp-2)">🌐 Web UI 模式</h4>
          <p class="text-secondary text-sm">浏览器图形化管理面板，最多管理 10 个应用，本地加密存储凭证。</p>
          <button class="btn btn-sm btn-info mt-2" onclick="Views._launchWebUI()">
            🚀 启动 Web UI
          </button>
        </div>
        <div>
          <div class="badge badge-info mb-2">灵活</div>
          <h4 style="margin:0 0 var(--sp-2)">⚡ 命令行模式</h4>
          <p class="text-secondary text-sm">直接指定协议与目标，适合脚本自动化或一次性连接。</p>
          <button class="btn btn-sm mt-2" onclick="navigate('tunnel-new')">新建隧道 →</button>
        </div>
        <div>
          <div class="badge badge-muted mb-2">常驻</div>
          <h4 style="margin:0 0 var(--sp-2)">⚙️ 系统服务</h4>
          <p class="text-secondary text-sm">随系统启动，持续运行。适合需要长期访问的场景。</p>
          <button class="btn btn-sm mt-2" onclick="navigate('service')">管理服务 →</button>
        </div>
      </div>
    </div>
  `;
};

Views._mount_dashboard = async function () {
  // 异步填充统计数字
  try {
    const presets = await Shield.call('list_presets');
    const el = document.getElementById('stat-presets');
    if (el) el.textContent = (presets || []).length;
  } catch {}
  try {
    // 使用新的结构化 plugin_list 接口
    const res = await Shield.call('plugin_list');
    const el = document.getElementById('stat-plugins');
    if (el) {
      if (res && typeof res.count === 'number') {
        el.textContent = res.count;
      } else {
        el.textContent = '0';
      }
    }
  } catch {}
};

// ---------- 快速启动 ----------

Views._launchWebUI = async function () {
  const port = 8181;
  try {
    const res = await Shield.call('start_web_ui', port);
    if (res.code === 0 && !res.error) {
      Shield.call('open_web_ui', port);
      toast('Web UI 已启动并打开', 'success');
    } else if (res.already_running) {
      Shield.call('open_web_ui', port);
      toast('Web UI 已在运行', 'info');
    } else {
      toast('启动失败: ' + (res.error || '未知错误'), 'error');
    }
  } catch (e) {
    toast('启动出错: ' + e.message, 'error');
  }
};

// ---------- 安装方法 ----------

Views._installFromGitHub = async function () {
  const el = document.getElementById('install-progress');
  if (el) el.innerHTML = '<div class="terminal" style="max-height:80px"><span class="text-warning">⏳ 正在下载并安装 shield CLI（~10MB）…</span></div>';
  try {
    const res = await Shield.call('download_shield_release');
    if (el) {
      const cls = res.ok ? 'success' : 'danger';
      const msg = res.ok
        ? `✅ 安装成功！路径：${escapeHtml(res.path)}`
        : `❌ 安装失败：${escapeHtml(res.error)}`;
      el.innerHTML = `<div class="terminal" style="max-height:80px">${msg}</div>`;
    }
    if (res.ok) {
      toast('Shield CLI 安装成功！即将重新检测…', 'success');
      setTimeout(() => location.reload(), 1500);
    } else {
      toast('安装失败：' + (res.error || '未知错误'), 'error');
    }
  } catch (e) {
    if (el) el.innerHTML = `<div class="terminal" style="max-height:80px"><span class="text-danger">错误：${escapeHtml(e.message)}</span></div>`;
    toast('安装出错：' + e.message, 'error');
  }
};

Views._installFromBat = async function () {
  const el = document.getElementById('install-progress');
  if (el) el.innerHTML = '<div class="terminal" style="max-height:80px"><span class="text-warning">⏳ 正在下载并执行 install.bat…</span></div>';
  try {
    const res = await Shield.call('install_shield_bat');
    if (el) {
      const cls = res.ok ? 'success' : 'warning';
      const out = (res.stdout || '') + (res.stderr || '');
      el.innerHTML = `<div class="terminal" style="max-height:120px">${escapeHtml(out || res.message || (res.ok ? '安装完成' : '安装结束'))}</div>`;
    }
    if (res.ok) {
      toast('Shield CLI 安装成功！即将重新检测…', 'success');
      setTimeout(() => location.reload(), 1500);
    } else if (res.exe_found) {
      toast('shield.exe 已存在，安装完成', 'success');
      setTimeout(() => location.reload(), 1500);
    } else {
      toast('安装脚本执行完毕，可尝试其他方式', 'warning');
    }
  } catch (e) {
    if (el) el.innerHTML = `<div class="terminal" style="max-height:80px"><span class="text-danger">错误：${escapeHtml(e.message)}</span></div>`;
    toast('安装出错：' + e.message, 'error');
  }
};
