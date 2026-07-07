/* 备份恢复视图 — 预设/全局数据备份、WebDAV、定时调度 */
(() => {
  // 默认备份目录（由后端提供）
  let defaultDir = '';
  let webdavCfg = { enabled: false, url: '', username: '', password: '' };
  let scheduleMin = 0;

  /* ---- 渲染 ---- */
  Views.backup = function () {
    return `
      <div class="view-header">
        <h1 class="view-title">🔄 备份恢复</h1>
        <p class="view-desc">备份预设/全局数据，支持本地存档与 WebDAV 远程同步</p>
      </div>

      <div class="grid grid-2">
        <!-- 一键备份 -->
        <div class="card">
          <div class="card-header"><h3 class="card-title">📦 一键备份</h3></div>
          <p class="text-secondary text-sm mb-4">立即创建完整备份（预设 + 设置），格式 <code>ShieldGUI_日期时间.zip</code></p>
          <div class="flex gap-2">
            <button class="btn btn-primary" onclick="Views._backupNow()">⚡ 立即备份</button>
            <button class="btn" onclick="Views._refreshBackupList()">🔄 刷新列表</button>
          </div>
        </div>

        <!-- 备份路径 -->
        <div class="card">
          <div class="card-header"><h3 class="card-title">📁 备份路径</h3></div>
          <div class="form-row">
            <label class="form-label">本地备份目录</label>
            <input class="input mono" id="backup-dir" placeholder="默认: 文档/ShieldGUI/backups">
            <div class="form-hint">留空使用默认路径</div>
          </div>
          <button class="btn btn-primary btn-sm" onclick="Views._saveBackupDir()">💾 保存路径</button>
        </div>
      </div>

      <!-- WebDAV 远程备份 -->
      <div class="card mt-4">
        <div class="card-header"><h3 class="card-title">🌐 WebDAV 远程备份</h3></div>
        <p class="text-secondary text-sm mb-4">启用后将备份文件同步到远程 WebDAV 服务器</p>
        <div class="flex items-center gap-2 mb-4">
          <label class="checkbox" style="display:inline-flex">
            <input type="checkbox" id="webdav-enabled" onchange="Views._toggleWebDAV()">
            启用 WebDAV
          </label>
        </div>
        <div id="webdav-fields" class="hidden">
          <div class="grid grid-2" style="grid-template-columns:1fr 1fr">
            <div class="form-row">
              <label class="form-label">WebDAV URL</label>
              <input class="input mono" id="webdav-url" placeholder="https://example.com/dav/backups">
            </div>
            <div class="form-row">
              <label class="form-label">用户名（可选）</label>
              <input class="input mono" id="webdav-username" placeholder="admin">
            </div>
            <div class="form-row">
              <label class="form-label">密码（可选）</label>
              <input class="input mono" type="password" id="webdav-password" placeholder="••••••••">
            </div>
          </div>
          <button class="btn btn-primary btn-sm" onclick="Views._backupAndUpload()">⚡ 立即备份并上传</button>
          <button class="btn btn-sm ml-2" onclick="Views._saveWebDAV()">💾 保存配置</button>
          <button class="btn btn-sm ml-2" onclick="Views._listRemote()">📡 远程列表</button>
        </div>
      </div>

      <!-- 定时备份 -->
      <div class="card mt-4">
        <div class="card-header"><h3 class="card-title">⏰ 定时备份</h3></div>
        <p class="text-secondary text-sm mb-4">按间隔自动创建备份并可选同步到 WebDAV</p>
        <div class="form-row" style="max-width:320px">
          <label class="form-label">备份间隔</label>
          <select class="select" id="backup-schedule" onchange="Views._saveSchedule()">
            <option value="0">关闭</option>
            <option value="30">每 30 分钟</option>
            <option value="60">每 1 小时</option>
            <option value="180">每 3 小时</option>
            <option value="360">每 6 小时</option>
            <option value="720">每 12 小时</option>
            <option value="1440">每天</option>
            <option value="10080">每周</option>
          </select>
        </div>
      </div>

      <!-- 本地备份列表 -->
      <div class="card mt-4">
        <div class="card-header"><h3 class="card-title">📋 本地备份列表</h3></div>
        <div id="backup-list-container">
          <p class="text-secondary text-sm">加载中...</p>
        </div>
      </div>

      <!-- 远程备份列表 -->
      <div class="card mt-4 hidden" id="remote-card">
        <div class="card-header"><h3 class="card-title">📡 远程备份列表</h3></div>
        <div id="remote-list-container">
          <p class="text-secondary text-sm">暂无远程备份</p>
        </div>
      </div>
    `;
  };

  /* ---- mount ---- */
  Views._mount_backup = async function () {
    // 加载备份路径
    try {
      const s = await Shield.call('load_settings');
      const paths = await Shield.call('backup_get_paths');
      defaultDir = paths.default_dir || '';

      const dirEl = document.getElementById('backup-dir');
      dirEl.value = s.backup_dir || '';

      // WebDAV
      webdavCfg = s.webdav || { enabled: false, url: '', username: '', password: '' };
      const wdEl = document.getElementById('webdav-enabled');
      wdEl.checked = !!webdavCfg.enabled;
      if (webdavCfg.enabled) Views._toggleWebDAV();
      document.getElementById('webdav-url').value = webdavCfg.url || '';
      document.getElementById('webdav-username').value = webdavCfg.username || '';
      document.getElementById('webdav-password').value = webdavCfg.password || '';

      // 定时备份
      scheduleMin = s.backup_schedule || 0;
      document.getElementById('backup-schedule').value = String(scheduleMin);
    } catch (e) { console.warn('backup mount', e); }

    Views._refreshBackupList();
  };

  /* ---- 立即备份 ---- */
  Views._backupNow = async function () {
    const dir = document.getElementById('backup-dir').value.trim() || defaultDir;
    const btn = document.querySelector('.btn-primary');
    btn.textContent = '⏳ 备份中...';
    btn.disabled = true;
    try {
      const res = await Shield.call('backup_create', dir);
      if (res.ok && webdavCfg.enabled && webdavCfg.url) {
        await Shield.call('backup_webdav_upload', res.path, webdavCfg);
      }
      Views._refreshBackupList();
    } catch (e) {
      toast('备份失败: ' + e.message, 'error');
    }
    btn.textContent = '⚡ 立即备份';
    btn.disabled = false;
  };

  /* ---- 立即备份并上传到 WebDAV ---- */
  Views._backupAndUpload = async function () {
    const dir = document.getElementById('backup-dir').value.trim() || defaultDir;
    const btn = document.querySelector('[onclick*="backupAndUpload"]');
    btn.textContent = '⏳ 备份上传中...';
    btn.disabled = true;
    try {
      const res = await Shield.call('backup_create', dir);
      if (!res.ok) { toast('备份失败: ' + (res.error || ''), 'error'); return; }
      toast('备份完成，正在上传到 WebDAV...', 'info');
      const wdOk = await Shield.call('backup_webdav_upload', res.path, webdavCfg);
      if (wdOk.ok) toast('✅ 备份已上传到 WebDAV', 'success');
      else toast('⚠️ 备份已创建，但 WebDAV 上传失败: ' + (wdOk.error || ''), 'warning');
      Views._refreshBackupList();
    } catch (e) {
      toast('操作失败: ' + e.message, 'error');
    }
    btn.textContent = '⚡ 立即备份并上传';
    btn.disabled = false;
  };

  /* ---- 刷新本地备份列表 ---- */
  Views._refreshBackupList = async function () {
    const dir = document.getElementById('backup-dir').value.trim() || defaultDir;
    const container = document.getElementById('backup-list-container');
    try {
      const list = await Shield.call('backup_list', dir);
      if (!list || list.length === 0) {
        container.innerHTML = '<p class="text-secondary text-sm">暂无备份文件</p>';
        return;
      }
      container.innerHTML = `
        <table class="table">
          <thead><tr>
            <th>文件名</th><th>大小</th><th>修改时间</th><th>操作</th>
          </tr></thead>
          <tbody>
            ${list.map(b => `
              <tr>
                <td class="mono text-sm">${b.name}</td>
                <td>${(b.size / 1024).toFixed(1)} KB</td>
                <td class="text-xs">${b.modified.replace('T', ' ').slice(0, 19)}</td>
                <td class="flex gap-1">
                  <button class="btn btn-sm btn-primary" onclick="Views._restoreBackup('${b.path.replace(/\\/g, '\\\\')}')">♻ 恢复</button>
                  <button class="btn btn-sm btn-danger" onclick="Views._deleteBackup('${b.path.replace(/\\/g, '\\\\')}')">🗑 删除</button>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `;
    } catch (e) {
      container.innerHTML = `<p class="text-danger text-sm">加载失败: ${e.message}</p>`;
    }
  };

  /* ---- 恢复备份 ---- */
  Views._restoreBackup = async function (path) {
    const ok = await confirmDialog('恢复备份', '将覆盖当前预设和设置，确定？');
    if (!ok) return;
    const res = await Shield.call('backup_restore', path);
    toast(res.ok ? '✅ 恢复完成' : '❌ 恢复失败: ' + (res.error || ''), res.ok ? 'success' : 'error');
  };

  /* ---- 删除备份 ---- */
  Views._deleteBackup = async function (path) {
    const ok = await confirmDialog('删除备份', '确定删除此备份？');
    if (!ok) return;
    await Shield.call('backup_delete', path);
    Views._refreshBackupList();
    toast('已删除', 'info');
  };

  /* ---- 保存备份路径 ---- */
  Views._saveBackupDir = async function () {
    const val = document.getElementById('backup-dir').value.trim();
    const s = await Shield.call('load_settings');
    s.backup_dir = val;
    await Shield.call('save_settings', s);
    toast('备份路径已保存', 'success');
  };

  /* ---- WebDAV 切换 ---- */
  Views._toggleWebDAV = function () {
    const enabled = document.getElementById('webdav-enabled').checked;
    document.getElementById('webdav-fields').classList.toggle('hidden', !enabled);
  };

  Views._saveWebDAV = async function () {
    webdavCfg = {
      enabled: document.getElementById('webdav-enabled').checked,
      url: document.getElementById('webdav-url').value.trim(),
      username: document.getElementById('webdav-username').value.trim(),
      password: document.getElementById('webdav-password').value.trim(),
    };
    const s = await Shield.call('load_settings');
    s.webdav = webdavCfg;
    await Shield.call('save_settings', s);
    toast('WebDAV 配置已保存', 'success');
  };

  /* ---- 远程列表 ---- */
  Views._listRemote = async function () {
    const card = document.getElementById('remote-card');
    const container = document.getElementById('remote-list-container');
    card.classList.remove('hidden');
    container.innerHTML = '<p class="text-secondary text-sm">查询中...</p>';
    try {
      const list = await Shield.call('backup_webdav_list', webdavCfg);
      if (!list || list.length === 0) {
        container.innerHTML = '<p class="text-secondary text-sm">暂无远程备份</p>';
        return;
      }
      container.innerHTML = `
        <table class="table">
          <thead><tr><th>文件名</th><th>大小</th><th>操作</th></tr></thead>
          <tbody>
            ${list.map(f => `
              <tr>
                <td class="mono text-sm">${f.name}</td>
                <td>${(f.size / 1024).toFixed(1)} KB</td>
                <td><button class="btn btn-sm btn-primary" onclick="Views._downloadRemote('${f.name}')">⬇ 下载并恢复</button></td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `;
    } catch (e) {
      container.innerHTML = `<p class="text-danger text-sm">查询失败: ${e.message}</p>`;
    }
  };

  Views._downloadRemote = async function (filename) {
    const localDir = document.getElementById('backup-dir').value.trim() || defaultDir;
    const dl = await Shield.call('backup_webdav_download', filename, localDir, webdavCfg);
    if (!dl.ok) { toast('下载失败: ' + dl.error, 'error'); return; }
    const ok = await confirmDialog('恢复远程备份', `已下载 ${filename}，立即恢复？`);
    if (!ok) return;
    const res = await Shield.call('backup_restore', dl.path);
    toast(res.ok ? '✅ 恢复完成' : '❌ 恢复失败', res.ok ? 'success' : 'error');
    Views._refreshBackupList();
  };

  /* ---- 定时备份 ---- */
  Views._saveSchedule = async function () {
    const val = parseInt(document.getElementById('backup-schedule').value, 10);
    scheduleMin = val;
    const s = await Shield.call('load_settings');
    s.backup_schedule = val;
    await Shield.call('save_settings', s);

    if (val > 0) {
      const dir = document.getElementById('backup-dir').value.trim() || defaultDir;
      await Shield.call('backup_scheduler_start', val, dir, webdavCfg);
      toast(`定时备份已开启（间隔 ${val} 分钟）`, 'success');
    } else {
      await Shield.call('backup_scheduler_stop');
      toast('定时备份已关闭', 'info');
    }
  };
})();
