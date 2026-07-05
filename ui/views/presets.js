/* 连接预设视图 */
Views.presets = function () {
  return `
    <div class="view-header">
      <h1 class="view-title">连接预设</h1>
      <p class="view-desc">保存常用隧道配置，一键启动；数据存于 Shield 官方配置目录</p>
    </div>
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
        <div class="empty-title">暂无预设</div>
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
