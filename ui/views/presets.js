/* ---------- 内置常用端口预设（按协议分类，来自常见端口协议.md） ---------- */
const COMMON_PRESETS = [
  {
    category: 'HTTP / 网页服务',
    items: [
      { name: 'HTTP 网页',        protocol: 'http',  target: '80'   },
      { name: 'HTTPS 加密网页',   protocol: 'https', target: '443'  },
      { name: 'HTTP 备用端口',    protocol: 'http',  target: '8080' },
      { name: 'HTTPS 备用端口',   protocol: 'https', target: '8443' },
    ],
  },
  {
    category: '远程管理',
    items: [
      { name: 'SSH 远程登录',      protocol: 'ssh',   target: '22'   },
      { name: 'RDP 远程桌面',      protocol: 'rdp',   target: '3389' },
      { name: 'VNC 图形桌面',      protocol: 'vnc',   target: '5900' },
      { name: 'Telnet 终端',       protocol: 'telnet',target: '23'   },
    ],
  },
  {
    category: '数据库',
    items: [
      { name: 'MySQL',             protocol: 'mysql',      target: '3306' },
      { name: 'PostgreSQL',        protocol: 'postgres',   target: '5432' },
      { name: 'SQL Server',        protocol: 'sqlserver',  target: '1433' },
      { name: 'Redis',             protocol: 'tcp',        target: '6379' },
      { name: 'MongoDB',           protocol: 'tcp',        target: '27017'},
    ],
  },
  {
    category: '文件传输',
    items: [
      { name: 'FTP 控制',         protocol: 'tcp',   target: '21'   },
      { name: 'SFTP 加密传输',    protocol: 'ssh',   target: '22'   },
    ],
  },
  {
    category: '邮件服务',
    items: [
      { name: 'SMTP 发信',        protocol: 'tcp',   target: '25'   },
      { name: 'SMTPS 加密发信',   protocol: 'tcp',   target: '465'  },
      { name: 'POP3 收信',        protocol: 'tcp',   target: '110'  },
      { name: 'IMAP 同步',        protocol: 'tcp',   target: '143'  },
    ],
  },
  {
    category: '网络基础服务',
    items: [
      { name: 'DNS 解析',         protocol: 'udp',   target: '53'   },
      { name: 'NTP 时间同步',     protocol: 'udp',   target: '123'  },
    ],
  },
];

/* ---------- 连接预设视图 ---------- */
Views.presets = function () {
  return `
    <div class="view-header">
      <h1 class="view-title">连接预设</h1>
      <p class="view-desc">保存常用隧道配置，一键启动；内置常用端口快捷填充</p>
    </div>

    <!-- 内置常用端口预设 -->
    <div class="card mb-4">
      <div class="card-header">
        <h3 class="card-title">📋 内置常用端口</h3>
        <span class="text-muted text-sm">点击即自动填充协议与目标端口</span>
      </div>
      ${COMMON_PRESETS.map(cat => `
        <div style="margin-bottom:var(--sp-4)">
          <div class="text-sm font-semibold text-secondary" style="margin:0 0 var(--sp-2);letter-spacing:.4px">
            ${cat.category}
          </div>
          <div style="display:flex;flex-wrap:wrap;gap:var(--sp-2)" class="common-preset-row">
            ${cat.items.map(item => `
              <button class="btn btn-sm preset-chip"
                      onclick="fillPreset('${item.protocol}','${item.target}','${item.name}')"
                      title="填充：${item.protocol} → :${item.target}">
                ${item.name}
                <span class="text-xs text-muted" style="font-family:var(--font-mono)">:${item.target}</span>
              </button>
            `).join('')}
          </div>
        </div>
      `).join('')}
    </div>

    <!-- 用户保存的预设 -->
    <div class="flex justify-between items-center mb-4">
      <span class="text-secondary text-sm" id="presets-count">—</span>
      <button class="btn btn-primary btn-sm" onclick="navigate('tunnel-new')">➕ 新建预设</button>
    </div>
    <div id="presets-list"></div>
  `;
};

Views._mount_presets = async function () {
  const list = await Shield.call('list_presets');
  const arr = Array.isArray(list) ? list : [];
  document.getElementById('presets-count').textContent = `共 ${arr.length} 个预设`;
  const root = document.getElementById('presets-list');

  if (arr.length === 0) {
    root.innerHTML = `
      <div class="card"><div class="empty">
        <div class="empty-icon">📑</div>
        <div class="empty-title">暂无已保存的预设</div>
        <p class="text-muted">在「新建隧道」页填写参数后点「存为预设」即可保存</p>
        <button class="btn btn-primary mt-4" onclick="navigate('tunnel-new')">⚡ 新建隧道</button>
      </div></div>`;
    return;
  }

  root.innerHTML = `
    <div class="card" style="padding:0;overflow:hidden">
      <table class="table">
        <thead><tr>
          <th>名称</th><th>协议</th><th>目标</th><th>认证</th><th style="width:180px">操作</th>
        </tr></thead>
        <tbody>
          ${arr.map(p => `
            <tr>
              <td><b>${escapeHtml(p.name || p.display_name || '未命名')}</b></td>
              <td><span class="badge badge-accent">${escapeHtml(p.protocol)}</span></td>
              <td class="mono text-sm">${escapeHtml(p.target || '默认')}</td>
              <td>${p.username ? '<span class="badge badge-info">有</span>' : '<span class="badge badge-muted">无</span>'}</td>
              <td>
                <button class="btn btn-sm btn-primary" onclick="Views._launchPreset('${escapeAttr(p.id)}')">🚀 启动</button>
                <button class="btn btn-sm btn-danger" onclick="Views._delPreset('${escapeAttr(p.id)}','${escapeAttr(p.name||'')}')">删除</button>
              </td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`;
  // 缓存列表供启动用
  Views._presetCache = arr;
};

Views._launchPreset = async function (pid) {
  const p = (Views._presetCache || []).find(x => x.id === pid);
  if (!p) { toast('预设不存在', 'error'); return; }
  toast('正在启动预设: ' + (p.name || ''), 'info');
  try {
    const res = await Shield.call('start_tunnel', p);
    if (res.error) { toast('启动失败: ' + res.error, 'error'); return; }
    toast('已启动', 'success');
    setTimeout(() => navigate('sessions'), 400);
  } catch (e) {
    toast('启动出错: ' + e.message, 'error');
  }
};

Views._delPreset = async function (pid, name) {
  const ok = await confirmDialog('删除预设', `确定删除预设「${name}」？此操作不可撤销。`);
  if (!ok) return;
  const r = await Shield.call('del_preset', pid);
  if (r) { toast('已删除', 'success'); Views._mount_presets(); }
  else toast('删除失败', 'error');
};
