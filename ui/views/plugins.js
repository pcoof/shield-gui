/* 插件管理视图 */
Views.plugins = function () {
  return `
    <div class="view-header">
      <h1 class="view-title">插件管理</h1>
      <p class="view-desc">通过独立插件扩展协议支持，主程序零膨胀，按需安装</p>
    </div>

    <div class="card mb-4">
      <div class="card-header">
        <h3 class="card-title">📦 已安装插件</h3>
        <button class="btn btn-sm" onclick="Views._reloadPlugins()">🔄 刷新</button>
      </div>
      <div id="installed-plugins"><div class="text-muted text-sm">加载中…</div></div>
    </div>

    <div class="card">
      <div class="card-header"><h3 class="card-title">🛒 可用插件</h3></div>
      <div class="grid grid-3">
        <div>
          <h4>🗄 MySQL</h4>
          <p class="text-secondary text-sm mb-2">MySQL 5.7 / 8.x 数据库代理，浏览器内 SQL 操作。</p>
          <div class="flex gap-2">
            <button class="btn btn-sm btn-primary" onclick="Views._installPlugin('mysql')">安装</button>
            <button class="btn btn-sm btn-danger" onclick="Views._removePlugin('mysql')">移除</button>
          </div>
        </div>
        <div>
          <h4>🗄 PostgreSQL</h4>
          <p class="text-secondary text-sm mb-2">PostgreSQL 10+ 数据库代理，支持只读模式。</p>
          <div class="flex gap-2">
            <button class="btn btn-sm btn-primary" onclick="Views._installPlugin('postgres')">安装</button>
            <button class="btn btn-sm btn-danger" onclick="Views._removePlugin('postgres')">移除</button>
          </div>
        </div>
        <div>
          <h4>🗄 SQL Server</h4>
          <p class="text-secondary text-sm mb-2">Microsoft SQL Server 数据库代理。</p>
          <div class="flex gap-2">
            <button class="btn btn-sm btn-primary" onclick="Views._installPlugin('sqlserver')">安装</button>
            <button class="btn btn-sm btn-danger" onclick="Views._removePlugin('sqlserver')">移除</button>
          </div>
        </div>
      </div>
      <div class="alert alert-info mt-4">
        <span>ℹ</span>
        <div>
          <b>从本地安装</b><br>
          <span class="text-sm">若有本地插件二进制，可在下方手动安装：</span>
          <div class="input-group mt-2" style="max-width:480px">
            <input class="input mono text-sm" id="local-plugin-name" placeholder="插件名 mysql">
            <input class="input mono text-sm" id="local-plugin-path" placeholder="本地路径（可选）">
            <button class="btn btn-sm" onclick="Views._installLocal()">安装</button>
          </div>
        </div>
      </div>
    </div>

    <div class="card mt-4">
      <div class="card-header"><h3 class="card-title">📖 插件开发指南</h3></div>
      <div class="text-secondary text-sm">
        <p style="margin:0 0 var(--sp-2)"><b>设计理念：</b>主程序与协议解耦，每个插件是独立二进制，按需下载。</p>
        <p style="margin:0 0 var(--sp-2)"><b>插件契约：</b></p>
        <ul style="margin:0 0 var(--sp-2);padding-left:var(--sp-5)">
          <li>插件命名：<code class="mono">shield-plugin-&lt;name&gt;</code>（如 shield-plugin-mysql）</li>
          <li>插件需实现统一的 JSON-RPC 或 stdio 协议接口</li>
          <li>通过 <code class="mono">shield plugin add &lt;name&gt; --from &lt;path&gt;</code> 从本地安装</li>
          <li>插件版本独立管理，<code class="mono">shield plugin upgrade [name]</code> 升级</li>
        </ul>
        <p style="margin:0"><b>使用插件：</b>安装后，<code class="mono">shield &lt;plugin-name&gt;</code> 即可作为协议使用，例如 <code class="mono">shield mysql 3306 --db-name mydb --db-user root --db-pass xxx</code></p>
      </div>
    </div>

    <div class="card mt-4">
      <div class="card-header"><h3 class="card-title">🔧 命令行操作</h3></div>
      <div class="cmd-preview mb-2">shield plugin list                              # 列出已装与可用</div>
      <div class="cmd-preview mb-2">shield plugin add mysql                         # 从官方仓库安装</div>
      <div class="cmd-preview mb-2">shield plugin add mysql --from ./shield-plugin-mysql  # 从本地安装</div>
      <div class="cmd-preview mb-2">shield plugin remove mysql                      # 移除插件</div>
      <div class="cmd-preview mb-2">shield plugin upgrade mysql                     # 升级单个插件</div>
      <div class="cmd-preview">shield plugin upgrade                           # 升级全部插件</div>
    </div>
  `;
};

Views._mount_plugins = function () { Views._reloadPlugins(); };

Views._reloadPlugins = async function () {
  const el = document.getElementById('installed-plugins');
  if (!el) return;
  el.innerHTML = '<div class="text-muted text-sm">加载中…</div>';
  try {
    const res = await Shield.call('plugin_list');
    const out = (res.stdout || '') + (res.stderr || '');
    if (/no plugins installed/i.test(out) || !out.trim()) {
      el.innerHTML = '<div class="empty"><div class="empty-icon">🧩</div><div class="empty-title">尚未安装任何插件</div><p class="text-muted">从下方可用插件中选择安装</p></div>';
      return;
    }
    // 解析输出（shield plugin list 输出格式较自由，简单渲染）
    el.innerHTML = `
      <div class="terminal" style="max-height:200px;user-select:text">${escapeHtml(out.trim())}</div>`;
  } catch (e) {
    el.innerHTML = `<div class="alert alert-danger">加载失败: ${escapeHtml(e.message)}</div>`;
  }
};

Views._installPlugin = async function (name) {
  toast(`正在安装插件 ${name}（可能需要下载）…`, 'info');
  const res = await Shield.call('plugin_add', name);
  const out = ((res.stdout || '') + (res.stderr || '')).trim();
  if (res.success) {
    toast(`插件 ${name} 安装成功`, 'success');
    Views._reloadPlugins();
    return;
  }
  // 安装失败 — 显示详细错误
  const errMsg = res.error || out || `退出码 ${res.code}`;
  toast(`插件 ${name} 安装失败`, 'error');
  // 在插件列表上方显示错误详情
  const root = document.getElementById('installed-plugins');
  if (root) {
    root.innerHTML = `
      <div class="alert alert-danger">
        <span>✕</span>
        <div>
          <b>插件 ${name} 安装失败</b><br>
          <span class="text-sm">${escapeHtml(errMsg.slice(0, 500))}</span>
          <div class="mt-2">
            <button class="btn btn-sm" onclick="Views._reloadPlugins()">🔄 返回</button>
          </div>
        </div>
      </div>`;
  }
};

Views._removePlugin = async function (name) {
  const ok = await confirmDialog('移除插件', `确定移除插件 ${name}？`);
  if (!ok) return;
  const res = await Shield.call('plugin_remove', name);
  toast(`插件 ${name} 已移除`, 'success');
  Views._reloadPlugins();
};

Views._installLocal = async function () {
  const name = document.getElementById('local-plugin-name').value.trim();
  const path = document.getElementById('local-plugin-path').value.trim();
  if (!name) { toast('请输入插件名', 'warning'); return; }
  toast(`从本地安装 ${name}…`, 'info');
  const res = await Shield.call('plugin_add', name, path);
  toast(`本地插件 ${name} 安装完成`, res.code === 0 ? 'success' : 'warning');
  Views._reloadPlugins();
};
