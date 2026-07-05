/* 新建隧道视图 — GUI 的核心功能页 */
Views.tunnelNew = function () {
  return `
    <div class="view-header">
      <h1 class="view-title">新建隧道</h1>
      <p class="view-desc">选择协议 → 填写目标 → 启动安全隧道，shield 会返回公网可访问的 URL</p>
    </div>

    <div class="grid" style="grid-template-columns:1fr 360px;gap:var(--sp-5);align-items:start">
      <!-- 左侧表单 -->
      <div style="display:flex;flex-direction:column;gap:var(--sp-5)">

        <!-- 协议选择 -->
        <div class="card">
          <div class="card-header">
            <h3 class="card-title">① 选择协议</h3>
            <span class="text-muted text-sm" id="proto-desc">—</span>
          </div>
          <div class="protocol-grid" id="proto-grid"></div>
        </div>

        <!-- 目标地址 -->
        <div class="card">
          <div class="card-header"><h3 class="card-title">② 目标地址</h3></div>
          <div class="form-row">
            <label class="form-label">目标 IP:Port<span class="req">*</span></label>
            <div class="input-group">
              <input class="input mono" id="f-target" placeholder="例: 127.0.0.1:22 或 192.168.1.10 或 3306（仅端口）"
                     oninput="TunnelForm.updatePreview()">
              <button class="btn" onclick="TunnelForm.useLocal()">本机</button>
            </div>
            <div class="form-hint">留空则使用协议默认端口（如 SSH → 127.0.0.1:22）</div>
          </div>
          <div class="form-row">
            <label class="form-label">显示名称</label>
            <input class="input" id="f-display" placeholder="可选，便于在会话列表识别"
                   oninput="TunnelForm.updatePreview()">
          </div>
        </div>

        <!-- 认证参数（SSH/RDP/VNC） -->
        <div class="card" id="auth-card">
          <div class="card-header"><h3 class="card-title">③ 认证 <span class="text-muted text-sm" id="auth-hint"></span></h3></div>
          <div class="form-grid">
            <div class="form-row">
              <label class="form-label">用户名</label>
              <input class="input mono" id="f-username" placeholder="root / administrator"
                     oninput="TunnelForm.updatePreview()">
            </div>
            <div class="form-row">
              <label class="form-label">密码</label>
              <input class="input mono" type="password" id="f-authpass" placeholder="目标服务密码"
                     oninput="TunnelForm.updatePreview()">
            </div>
          </div>
          <div class="form-row" id="ssh-only-fields">
            <label class="form-label">SSH 私钥文件路径</label>
            <div class="input-group">
              <input class="input mono" id="f-privkey" placeholder="~/.ssh/id_rsa"
                     oninput="TunnelForm.updatePreview()">
              <button class="btn" onclick="TunnelForm.pickKey()">浏览…</button>
            </div>
          </div>
          <div class="form-grid">
            <div class="form-row" id="ssh-passphrase-field">
              <label class="form-label">私钥口令（Passphrase）</label>
              <input class="input mono" type="password" id="f-passphrase"
                     oninput="TunnelForm.updatePreview()">
            </div>
            <div class="form-row" id="sftp-field">
              <label class="form-label">SFTP</label>
              <label class="checkbox" style="margin-top:6px">
                <input type="checkbox" id="f-sftp" onchange="TunnelForm.updatePreview()">
                启用文件传输
              </label>
            </div>
          </div>
        </div>

        <!-- 数据库参数（插件协议） -->
        <div class="card hidden" id="db-card">
          <div class="card-header"><h3 class="card-title">③ 数据库参数</h3></div>
          <div class="form-grid">
            <div class="form-row">
              <label class="form-label">数据库名</label>
              <input class="input mono" id="f-dbname" oninput="TunnelForm.updatePreview()">
            </div>
            <div class="form-row">
              <label class="form-label">数据库用户</label>
              <input class="input mono" id="f-dbuser" oninput="TunnelForm.updatePreview()">
            </div>
            <div class="form-row">
              <label class="form-label">数据库密码</label>
              <input class="input mono" type="password" id="f-dbpass" oninput="TunnelForm.updatePreview()">
            </div>
            <div class="form-row">
              <label class="form-label">只读模式</label>
              <label class="checkbox" style="margin-top:6px">
                <input type="checkbox" id="f-readonly" onchange="TunnelForm.updatePreview()"> 强制只读
              </label>
            </div>
          </div>
        </div>

        <!-- 高级选项 -->
        <div class="card">
          <div class="card-header">
            <h3 class="card-title">④ 高级选项</h3>
            <button class="btn btn-sm btn-ghost" onclick="TunnelForm.toggleAdvanced()">
              <span id="adv-toggle-text">展开 ▾</span>
            </button>
          </div>
          <div id="adv-fields" class="hidden">
            <div class="form-grid">
              <div class="form-row">
                <label class="form-label">站点名称 (site-name)</label>
                <input class="input" id="f-sitename" oninput="TunnelForm.updatePreview()">
              </div>
              <div class="form-row">
                <label class="form-label">AC 节点过滤 (visable)</label>
                <input class="input mono" id="f-visable" value="visable" oninput="TunnelForm.updatePreview()">
              </div>
              <div class="form-row">
                <label class="form-label">隧道端口 (tunnel-port)</label>
                <input class="input mono" id="f-tunnelport" type="number" placeholder="默认 62888"
                       oninput="TunnelForm.updatePreview()">
              </div>
              <div class="form-row">
                <label class="form-label">自定义服务器 (server)</label>
                <input class="input mono" id="f-server" placeholder="https://console.yishield.com/raas"
                       oninput="TunnelForm.updatePreview()">
              </div>
            </div>
            <div style="display:flex;gap:var(--sp-4);margin-top:var(--sp-2)">
              <label class="checkbox"><input type="checkbox" id="f-invisible" onchange="TunnelForm.updatePreview()"> 隐身模式（需授权码访问）</label>
              <label class="checkbox"><input type="checkbox" id="f-verbose" onchange="TunnelForm.updatePreview()"> 详细日志 (-v)</label>
            </div>
          </div>
        </div>

        <!-- 操作按钮 -->
        <div class="flex gap-3">
          <button class="btn btn-primary btn-lg" onclick="TunnelForm.start()" id="btn-start">
            🚀 启动隧道
          </button>
          <button class="btn btn-lg" onclick="TunnelForm.saveAsPreset()">💾 存为预设</button>
          <button class="btn btn-lg btn-ghost" onclick="TunnelForm.reset()">重置</button>
        </div>
      </div>

      <!-- 右侧预览 -->
      <div style="position:sticky;top:0;display:flex;flex-direction:column;gap:var(--sp-4)">
        <div class="card">
          <div class="card-header"><h3 class="card-title">命令预览</h3></div>
          <div class="cmd-preview" id="cmd-preview">shield ssh</div>
          <div class="form-hint mt-2">这是将实际执行的命令（点击可复制）</div>
        </div>
        <div class="card">
          <div class="card-header"><h3 class="card-title">协议说明</h3></div>
          <div id="proto-info" class="text-sm text-secondary">选择一个协议查看详情</div>
        </div>
      </div>
    </div>
  `;
};

// 挂载钩子：路由系统调用 Views._mount_tunnel_new，委托给 TunnelForm
Views._mount_tunnel_new = function () {
  TunnelForm._mount_tunnel_new();
};

// ---------- 新建隧道表单逻辑 ----------
const TunnelForm = {
  protocol: 'ssh',
  protocols: {
    ssh:    {label:'SSH',    icon:'🔐', desc:'浏览器中打开完整 SSH 终端，支持密码/私钥/SFTP', auth:true,  defPort:22},
    rdp:    {label:'RDP',    icon:'🖥',  desc:'访问 Windows 远程桌面，鼠标键盘完整控制',     auth:true,  defPort:3389},
    vnc:    {label:'VNC',    icon:'🖱',  desc:'共享和控制远程桌面屏幕，像素级渲染',           auth:true,  defPort:5900},
    http:   {label:'HTTP',   icon:'🌐', desc:'将本地/内网 HTTP Web 应用暴露到公网',           auth:false, defPort:80},
    https:  {label:'HTTPS',  icon:'🔒', desc:'将本地/内网 HTTPS Web 应用暴露到公网',          auth:false, defPort:443},
    telnet: {label:'Telnet', icon:'📟', desc:'连接网络设备/路由器/交换机等传统 Telnet 服务',  auth:true,  defPort:23},
    tcp:    {label:'TCP',    icon:'🔌', desc:'TCP 端口代理（MySQL/Redis/PostgreSQL 等）',     auth:false, defPort:0},
    udp:    {label:'UDP',    icon:'📡', desc:'UDP 端口代理（DNS 等）',                         auth:false, defPort:0},
    mysql:      {label:'MySQL',     icon:'🗄', desc:'MySQL 数据库（需插件）', auth:false, defPort:3306, db:true},
    postgres:   {label:'PostgreSQL',icon:'🗄', desc:'PostgreSQL 数据库（需插件）', auth:false, defPort:5432, db:true},
    sqlserver:  {label:'SQLServer', icon:'🗄', desc:'SQL Server 数据库（需插件）', auth:false, defPort:1433, db:true},
  },

  _mount_tunnel_new() {
    this.renderProtocolGrid();
    this.select('ssh');
  },

  renderProtocolGrid() {
    const grid = document.getElementById('proto-grid');
    if (!grid) return;
    grid.innerHTML = Object.entries(this.protocols).map(([k, p]) => `
      <button class="protocol-card" data-proto="${k}" onclick="TunnelForm.select('${k}')">
        <div class="protocol-card-name">${p.icon} ${p.label}</div>
        <div class="protocol-card-port">: ${p.defPort || '自定义'}</div>
        <div class="protocol-card-desc">${p.desc}</div>
      </button>
    `).join('');
  },

  select(proto) {
    this.protocol = proto;
    const p = this.protocols[proto] || {};
    document.querySelectorAll('.protocol-card').forEach(el => {
      el.classList.toggle('selected', el.dataset.proto === proto);
    });
    document.getElementById('proto-desc').textContent = p.label + ' · ' + (p.defPort || '自定义端口');
    document.getElementById('proto-info').innerHTML = `
      <p style="margin:0 0 var(--sp-2)"><b>${p.icon} ${p.label}</b></p>
      <p style="margin:0">${p.desc}</p>
      ${p.defPort ? `<p class="text-muted text-xs mt-2">默认端口：${p.defPort}</p>` : ''}
    `;
    // 显隐认证卡 / 数据库卡
    const authCard = document.getElementById('auth-card');
    const dbCard = document.getElementById('db-card');
    authCard.classList.toggle('hidden', !p.auth);
    dbCard.classList.toggle('hidden', !p.db);
    // SSH 专属字段
    const sshOnly = proto === 'ssh';
    document.getElementById('ssh-only-fields').style.display = sshOnly ? '' : 'none';
    document.getElementById('ssh-passphrase-field').style.display = sshOnly ? '' : 'none';
    document.getElementById('sftp-field').style.display = sshOnly ? '' : 'none';
    document.getElementById('auth-hint').textContent = p.auth ? '(SSH/RDP/VNC)' : '';
    this.updatePreview();
  },

  useLocal() {
    document.getElementById('f-target').value = '127.0.0.1';
    this.updatePreview();
  },

  async pickKey() {
    const path = await Shield.call('pick_private_key');
    if (path) {
      document.getElementById('f-privkey').value = path;
      this.updatePreview();
      toast('已选择私钥文件', 'success');
    }
  },

  toggleAdvanced() {
    const f = document.getElementById('adv-fields');
    const t = document.getElementById('adv-toggle-text');
    const hidden = f.classList.toggle('hidden');
    t.textContent = hidden ? '展开 ▾' : '收起 ▴';
  },

  collect() {
    const v = id => (document.getElementById(id)?.value || '').trim();
    const cb = id => document.getElementById(id)?.checked || false;
    return {
      protocol: this.protocol,
      target: v('f-target'),
      display_name: v('f-display'),
      username: v('f-username'),
      auth_pass: v('f-authpass'),
      private_key: v('f-privkey'),
      passphrase: v('f-passphrase'),
      enable_sftp: cb('f-sftp'),
      db_name: v('f-dbname'),
      db_user: v('f-dbuser'),
      db_pass: v('f-dbpass'),
      readonly: cb('f-readonly'),
      site_name: v('f-sitename'),
      visable: v('f-visable'),
      tunnel_port: v('f-tunnelport'),
      server: v('f-server'),
      invisible: cb('f-invisible'),
      verbose: cb('f-verbose'),
    };
  },

  async updatePreview() {
    try {
      const params = this.collect();
      const res = await Shield.call('build_argv', params);
      const argv = res.argv || [];
      document.getElementById('cmd-preview').textContent = 'shield ' + argv.join(' ');
    } catch (e) {
      document.getElementById('cmd-preview').textContent = 'shield ' + this.protocol;
    }
  },

  reset() {
    ['f-target','f-display','f-username','f-authpass','f-privkey','f-passphrase',
     'f-dbname','f-dbuser','f-dbpass','f-sitename','f-tunnelport','f-server'
    ].forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
    ['f-sftp','f-readonly','f-invisible','f-verbose'].forEach(id => {
      const el = document.getElementById(id); if (el) el.checked = false;
    });
    this.select('ssh');
    toast('表单已重置', 'info');
  },

  async start() {
    const params = this.collect();
    if (!params.target && this.protocols[params.protocol]?.defPort) {
      // 允许留空（用默认端口）
    }
    const btn = document.getElementById('btn-start');
    btn.disabled = true;
    btn.textContent = '⏳ 启动中…';
    try {
      const res = await Shield.call('start_tunnel', params);
      if (res.error) {
        toast('启动失败: ' + res.error, 'error');
        return;
      }
      toast('隧道已启动，会话 ID: ' + res.session_id, 'success');
      // 跳转会话页
      setTimeout(() => navigate('sessions'), 500);
    } catch (e) {
      toast('启动出错: ' + e.message, 'error');
    } finally {
      btn.disabled = false;
      btn.textContent = '🚀 启动隧道';
    }
  },

  async saveAsPreset() {
    const params = this.collect();
    if (!params.protocol) { toast('请先选择协议', 'warning'); return; }
    const name = await this._promptName();
    if (!name) return;
    params.name = name;
    const saved = await Shield.call('save_preset', params);
    toast('预设已保存: ' + name, 'success');
  },

  _promptName() {
    return new Promise(resolve => {
      const mask = document.createElement('div');
      mask.className = 'modal-mask';
      mask.innerHTML = `
        <div class="modal">
          <h3 class="modal-title">保存为预设</h3>
          <div class="modal-body">
            <label class="form-label">预设名称</label>
            <input class="input" id="preset-name-input" placeholder="例：生产 MySQL" autofocus>
          </div>
          <div class="modal-actions">
            <button class="btn" data-act="cancel">取消</button>
            <button class="btn btn-primary" data-act="ok">保存</button>
          </div>
        </div>`;
      document.body.appendChild(mask);
      const input = mask.querySelector('#preset-name-input');
      mask.addEventListener('click', async e => {
        if (e.target.dataset.act === 'ok') {
          const v = input.value.trim();
          mask.remove();
          resolve(v || null);
        } else if (e.target.dataset.act === 'cancel' || e.target === mask) {
          mask.remove(); resolve(null);
        }
      });
      input.addEventListener('keydown', e => {
        if (e.key === 'Enter') mask.querySelector('[data-act=ok]').click();
      });
    });
  },
};
