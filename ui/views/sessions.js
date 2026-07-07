/* 活动会话视图 — 运行中隧道的实时管理 */
Views.sessions = function () {
  return `
    <div class="view-header">
      <h1 class="view-title">活动会话</h1>
      <p class="view-desc">查看运行中的隧道、实时日志、Access URL，可一键停止/重启</p>
    </div>

    <div class="flex justify-between items-center mb-4">
      <div class="flex gap-3 items-center">
        <span class="text-secondary text-sm">
          <span class="badge badge-success"><span class="dot dot-pulse"></span> 运行中</span>
          <span id="cnt-running">0</span> 个
        </span>
        <span class="text-secondary text-sm">
          <span class="badge badge-muted">总计</span>
          <span id="cnt-total">0</span> 个
        </span>
      </div>
      <button class="btn btn-sm" onclick="Views._refresh_sessions()">🔄 刷新</button>
    </div>

    <div id="sessions-list"></div>
  `;
};

Views._mount_sessions = function () {
  Views._refresh_sessions();
};

Views._refresh_sessions = function () {
  const list = State.sessions || [];
  const root = document.getElementById('sessions-list');
  if (!root) return;

  document.getElementById('cnt-running').textContent = list.filter(s => s.status === 'running').length;
  document.getElementById('cnt-total').textContent = list.length;

  if (list.length === 0) {
    root.innerHTML = `
      <div class="card">
        <div class="empty">
          <div class="empty-icon">🟢</div>
          <div class="empty-title">暂无活动会话</div>
          <p class="text-muted">点击下方按钮创建你的第一个隧道</p>
          <button class="btn btn-primary mt-4" onclick="navigate('tunnel-new')">⚡ 新建隧道</button>
        </div>
      </div>`;
    return;
  }

  root.innerHTML = list.map(s => Views._renderSession(s)).join('');

  // 为每个会话启动日志轮询
  list.forEach(s => Views._pollSessionLog(s.session_id));
};

Views._renderSession = function (s) {
  const isStopped = s.status === 'stopped' || s.status === 'error';
  const statusBadge = {
    running:  '<span class="badge badge-success"><span class="dot dot-pulse"></span>运行中</span>',
    starting: '<span class="badge badge-warning"><span class="dot dot-pulse"></span>启动中</span>',
    stopped:  '<span class="badge badge-muted">已停止</span>',
    error:    '<span class="badge badge-danger"><span class="dot"></span>错误</span>',
  }[s.status] || `<span class="badge badge-muted">${s.status}</span>`;

  const url = (s.access_urls && s.access_urls[0]) || '';
  const dur = fmtDuration(s.started_at, s.ended_at || (Date.now()/1000));

  return `
    <div class="session-item" id="sess-${s.session_id}">
      <div class="session-head">
        <div class="session-meta">
          <span class="session-proto">${s.protocol}</span>
          <span class="mono text-sm">${escapeHtml(s.target || '—')}</span>
          ${s.display_name ? `<span class="text-muted text-sm">· ${escapeHtml(s.display_name)}</span>` : ''}
          ${statusBadge}
          <span class="text-muted text-xs">PID ${s.pid || '—'} · ${dur}</span>
        </div>
        <div class="flex gap-2">
          ${url ? `<button class="btn btn-sm btn-info" onclick="window.open('${escapeAttr(url)}','_blank')">🌐 访问</button>` : ''}
          ${url ? `<button class="btn btn-sm" onclick="copyText('${escapeAttr(url)}')">📋 复制 URL</button>` : ''}
          <button class="btn btn-sm" onclick="Views._editSession('${s.session_id}')">✏️ 编辑</button>
          ${isStopped
            ? `<button class="btn btn-sm btn-primary" onclick="Views._restartSession('${s.session_id}')">▶ 启动</button>`
            : `<button class="btn btn-sm btn-danger" onclick="Views._stopSession('${s.session_id}')">⏹ 停止</button>`
          }
          <button class="btn btn-sm btn-ghost" onclick="Views._removeSession('${s.session_id}')">✕</button>
        </div>
      </div>
      ${url ? `
        <div class="alert alert-info mb-2" style="padding:var(--sp-2) var(--sp-3)">
          <span>🔗</span>
          <div class="mono text-sm" style="word-break:break-all;user-select:text">${escapeHtml(url)}</div>
        </div>` : ''}
      <div class="terminal" id="log-${s.session_id}" style="max-height:240px;min-height:60px">等待日志…</div>
    </div>
  `;
};

Views._editSession = async function (sid) {
  try {
    const sess = await Shield.call('get_session', sid);
    if (!sess) { toast('无法获取会话信息', 'error'); return; }
    // 预填到隧道新建表单
    State.pendingPreset = {
      protocol: sess.protocol,
      target: sess.target,
      display_name: sess.display_name,
    };
    navigate('tunnel-new');
  } catch (e) {
    toast('获取会话信息失败: ' + e.message, 'error');
  }
};

Views._restartSession = async function (sid) {
  const res = await Shield.call('restart_session', sid);
  if (res.session_id) {
    toast('会话已重新启动', 'success');
    refreshSessions();
  } else {
    toast('启动失败: ' + (res.error || ''), 'error');
  }
};

Views._pollSessionLog = function (sid) {
  // 用 offset 增量拉取
  if (!Views._logOffsets) Views._logOffsets = {};
  const offset = Views._logOffsets[sid] || 0;

  Shield.call('poll_log', sid, offset).then(res => {
    if (!res || !res.exists) return;
    const term = document.getElementById('log-' + sid);
    if (!term) return;
    if (res.text) {
      // 高亮 URL
      const html = escapeHtml(res.text).replace(
        /(https?:\/\/[^\s<]+)/g,
        '<span class="ln-url">$1</span>'
      );
      if (offset === 0) term.innerHTML = html;
      else term.innerHTML += html;
      term.scrollTop = term.scrollHeight;
    } else if (offset === 0) {
      term.textContent = '（暂无输出）';
    }
    Views._logOffsets[sid] = res.total;
  }).catch(()=>{});
};

Views._stopSession = async function (sid) {
  const ok = await Shield.call('stop_tunnel', sid);
  if (ok) {
    toast('会话已停止', 'success');
    refreshSessions();
  } else {
    toast('停止失败', 'error');
  }
};

Views._removeSession = async function (sid) {
  const ok = await confirmDialog('移除会话', '将停止该会话并从列表中移除，确定？');
  if (!ok) return;
  await Shield.call('remove_session', sid);
  if (Views._logOffsets) delete Views._logOffsets[sid];
  toast('会话已移除', 'success');
  refreshSessions();
};
