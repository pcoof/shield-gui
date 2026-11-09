/* 活动会话视图 — 桌面隧道 + 官方 Web 面板应用统一管理
 *
 * 会话来源（source）：
 *   gui —— GUI 直接 spawn 的 shield 子进程，有实时日志
 *   web —— 官方 Web UI（http://localhost:8181/）里的应用，状态从 /api/apps 拉取
 *
 * 容量上限：同时连接 3 个（running/starting），活动会话最多 10 个（含 Web 应用）
 */
Views.sessions = function () {
  return `
    <div class="view-header">
      <h1 class="view-title">活动会话</h1>
      <p class="view-desc">桌面隧道与官方 Web 面板里的应用统一展示，可查看状态、访问地址与实时日志</p>
    </div>

    <div class="flex justify-between items-center mb-4">
      <div class="capacity" id="sessions-capacity"></div>
      <div class="flex gap-2">
        <button class="btn btn-sm" onclick="Views._openWebPanel()">🌐 打开 Web 面板</button>
        <button class="btn btn-sm" onclick="Views._refresh_sessions(true)">🔄 刷新</button>
      </div>
    </div>

    <div id="sessions-limit-tip"></div>
    <div id="sessions-list"></div>
  `;
};

Views._mount_sessions = function () {
  Views._sessionSig = '';
  Views._refresh_sessions(true);
};

/* ---------- 容量计量条 ---------- */
Views._renderCapacity = function () {
  const el = document.getElementById('sessions-capacity');
  if (!el) return;
  const list = State.sessions || [];
  const L = State.limits || {
    max_sessions: 10,
    max_running: 3,
    sessions: list.length,
    running: list.filter(s => s.status === 'running' || s.status === 'starting').length,
  };
  const runPct = Math.min(100, (L.running / Math.max(1, L.max_running)) * 100);
  const sesPct = Math.min(100, (L.sessions / Math.max(1, L.max_sessions)) * 100);
  const runFull = L.running >= L.max_running;
  const sesFull = L.sessions >= L.max_sessions;

  el.innerHTML = `
    <span class="capacity-item ${runFull ? 'full' : ''}" title="同时连接上限 ${L.max_running} 个">
      <span class="dot ${L.running ? 'dot-pulse' : ''}"></span>
      并发 <span class="capacity-num">${L.running}/${L.max_running}</span>
      <span class="capacity-bar"><i style="width:${runPct}%"></i></span>
    </span>
    <span class="capacity-item ${sesFull ? 'full' : ''}" title="活动会话上限 ${L.max_sessions} 个">
      会话 <span class="capacity-num">${L.sessions}/${L.max_sessions}</span>
      <span class="capacity-bar"><i style="width:${sesPct}%"></i></span>
    </span>
    <span class="capacity-item ${L.web_ui_online ? 'web-online' : ''}"
          title="${L.web_ui_online ? 'Web 面板已连接，其中的应用会同步到这里' : 'Web 面板未运行'}">
      🌐 Web 面板 ${L.web_ui_online ? '已同步' : '未运行'}
      ${L.web_sessions ? `· ${L.web_sessions} 个应用` : ''}
    </span>
  `;

  // 顶部提示：命中上限时明确告知原因与出路
  const tip = document.getElementById('sessions-limit-tip');
  if (!tip) return;
  if (runFull) {
    tip.innerHTML = `
      <div class="alert alert-warning mb-4">
        <span class="alert-icon">!</span>
        <div>
          <b>并发已满（${L.running}/${L.max_running}）</b><br>
          <span class="text-sm">需先停止一个正在运行的隧道，才能启动新的连接。Web 面板里的连接同样计入并发。</span>
        </div>
      </div>`;
  } else if (sesFull) {
    tip.innerHTML = `
      <div class="alert alert-warning mb-4">
        <span class="alert-icon">!</span>
        <div>
          <b>活动会话已达上限（${L.sessions}/${L.max_sessions}）</b><br>
          <span class="text-sm">请移除不用的会话（✕）后再新建隧道。</span>
        </div>
      </div>`;
  } else {
    tip.innerHTML = '';
  }
};

/* ---------- 列表刷新（签名未变时只轮询日志，避免日志被清空闪烁） ---------- */
Views._sessionSig = '';

Views._refresh_sessions = function (force) {
  const list = State.sessions || [];
  Views._renderCapacity();
  const root = document.getElementById('sessions-list');
  if (!root) return;

  const sig = list
    .map(s => `${s.session_id}:${s.status}:${(s.access_urls || [])[0] || ''}:${s.pid || ''}:${s.source || ''}`
      + `:${(s.error_info || {}).code || ''}:${s.retry_count || 0}:${s.warning || ''}`
      + `:${s.protocol || ''}:${s.target || ''}:${s.display_name || ''}`)
    .join('|');
  const canPatch = !force && sig === Views._sessionSig && root.childElementCount > 0;

  if (canPatch) {
    list.forEach(s => Views._pollSessionLog(s.session_id));
    return;
  }
  Views._sessionSig = sig;

  if (list.length === 0) {
    root.innerHTML = `
      <div class="card">
        <div class="empty">
          <div class="empty-icon">🟢</div>
          <div class="empty-title">暂无活动会话</div>
          <p class="text-muted">新建一个隧道，或在官方 Web 面板（<span class="mono">localhost:8181</span>）里添加应用</p>
          <div class="flex gap-2 mt-4" style="justify-content:center">
            <button class="btn btn-primary" onclick="navigate('tunnel-new')">⚡ 新建隧道</button>
            <button class="btn" onclick="Views._openWebPanel()">🌐 打开 Web 面板</button>
          </div>
        </div>
      </div>`;
    return;
  }

  root.innerHTML = list.map(s => Views._renderSession(s)).join('');
  // 重新渲染后日志从头拉取一次，保证历史输出完整
  if (!Views._logOffsets) Views._logOffsets = {};
  list.forEach(s => {
    if (s.source !== 'web') Views._logOffsets[s.session_id] = 0;
    Views._pollSessionLog(s.session_id);
  });
};

Views._renderSession = function (s) {
  const isWeb = s.source === 'web';
  const isStopped = s.status === 'stopped' || s.status === 'error';
  const statusBadge = {
    running:  '<span class="badge badge-success"><span class="dot dot-pulse"></span>运行中</span>',
    starting: '<span class="badge badge-warning"><span class="dot dot-pulse"></span>启动中</span>',
    stopped:  '<span class="badge badge-muted">已停止</span>',
    error:    '<span class="badge badge-danger"><span class="dot"></span>错误</span>',
  }[s.status] || `<span class="badge badge-muted">${escapeHtml(s.status || '')}</span>`;

  const url = (s.access_urls && s.access_urls[0]) || '';
  const dur = fmtDuration(s.started_at, s.ended_at || (Date.now() / 1000));
  const pidText = isWeb ? (s.raw_status || 'web') : (s.pid || '—');
  const limit = State.limits || {};
  const canStart = limit.can_start !== false;

  // 启动失败：展示后端给出的中文诊断与处理建议
  const d = s.error_info || null;
  const diagHtml = d ? `
    <div class="diag-card">
      <div class="diag-head">
        <span class="diag-icon">✕</span>
        <div class="diag-text">
          <div class="diag-title">${escapeHtml(d.title || '启动失败')}</div>
          <div class="diag-reason">${escapeHtml(d.reason || '')}</div>
        </div>
        ${d.retryable ? '<span class="badge badge-warning">可重试</span>' : ''}
      </div>
      ${(d.advice || []).length
        ? `<ol class="diag-advice">${d.advice.map(a => `<li>${escapeHtml(a)}</li>`).join('')}</ol>` : ''}
      ${d.raw ? `<div class="diag-raw mono">${escapeHtml(d.raw)}</div>` : ''}
      ${s.retry_count ? `<div class="diag-raw text-muted">已重试 ${s.retry_count} 次</div>` : ''}
    </div>` : '';
  const warnHtml = s.warning
    ? `<div class="diag-note">⏳ ${escapeHtml(s.warning)}</div>` : '';
  const startLabel = s.status === 'error' ? '🔁 重试' : '▶ 启动';
  const startFn = s.status === 'error' ? 'Views._retrySession' : 'Views._restartSession';

  return `
    <div class="session-item" id="sess-${s.session_id}">
      <div class="session-head">
        <div class="session-meta">
          <span class="session-source ${isWeb ? 'web' : ''}" title="${isWeb ? '由官方 Web 面板管理' : '由桌面端启动的子进程'}">
            ${isWeb ? '🌐 Web 面板' : '🖥 桌面'}
          </span>
          <span class="session-proto">${escapeHtml(s.protocol || '')}</span>
          <span class="mono text-sm">${escapeHtml(s.target || '—')}</span>
          ${s.display_name ? `<span class="text-muted text-sm">· ${escapeHtml(s.display_name)}</span>` : ''}
          ${statusBadge}
          <span class="text-muted text-xs">PID ${escapeHtml(String(pidText))} · ${dur}</span>
        </div>
        <div class="flex gap-2">
          ${url ? `<button class="btn btn-sm btn-info" onclick="window.open('${escapeAttr(url)}','_blank')">🌐 访问</button>` : ''}
          ${url ? `<button class="btn btn-sm" onclick="copyText('${escapeAttr(url)}')">📋 复制 URL</button>` : ''}
          <button class="btn btn-sm" onclick="Views._editSession('${s.session_id}')">✏️ 编辑</button>
          ${isWeb ? `<button class="btn btn-sm" onclick="Views._openWebPanel()">⚙ 面板</button>` : ''}
          ${isStopped
            ? `<button class="btn btn-sm btn-primary" ${canStart ? '' : 'disabled title="并发已满，请先停止其他连接"'}
                 onclick="${startFn}('${s.session_id}')">${startLabel}</button>`
            : `<button class="btn btn-sm btn-danger" onclick="Views._stopSession('${s.session_id}')">⏹ 停止</button>`
          }
          <button class="btn btn-sm btn-ghost" onclick="Views._removeSession('${s.session_id}', ${isWeb})">✕</button>
        </div>
      </div>
      ${warnHtml}
      ${diagHtml}
      ${isWeb && s.error && !d ? `
        <div class="alert alert-danger mb-2" style="padding:var(--sp-2) var(--sp-3)">
          <span>✕</span>
          <div class="text-sm" style="word-break:break-all">${escapeHtml(s.error)}</div>
        </div>` : ''}
      ${url ? `
        <div class="alert alert-info mb-2" style="padding:var(--sp-2) var(--sp-3)">
          <span>🔗</span>
          <div class="mono text-sm" style="word-break:break-all;user-select:text">${escapeHtml(url)}</div>
        </div>` : ''}
      ${isWeb
        ? `<div class="text-muted text-xs">
             该会话由官方 Web 面板管理，不提供进程日志流；重连/断开请在面板或上方按钮操作。
           </div>`
        : `<div class="terminal" id="log-${s.session_id}" style="max-height:240px;min-height:60px">等待日志…</div>`}
    </div>
  `;
};

Views._openWebPanel = async function () {
  const port = (State.limits && State.limits.web_ui_port) || 8181;
  const online = !!(State.limits && State.limits.web_ui_online);
  if (!online) {
    const started = await Shield.call('start_web_ui', port);
    if (started && started.error) {
      toast('启动 Web UI 失败: ' + started.error, 'error');
      return;
    }
  }
  const ok = await Shield.call('open_web_ui', port);
  toast(
    ok ? `已打开 http://localhost:${port}` : `请手动访问 http://localhost:${port}`,
    ok ? 'success' : 'warning'
  );
  // 面板启动后稍等再刷新，让面板里的应用同步进列表
  if (!online) setTimeout(refreshSessions, 1500);
};

Views._editSession = async function (sid) {
  try {
    const sess = await Shield.call('get_session', sid);
    if (!sess) { toast('无法获取会话信息（会话可能已被移除）', 'error'); return; }
    if (sess.editable === false) {
      const go = await confirmDialog(
        '在 Web 面板中编辑',
        `该会话由官方 Web 面板管理，桌面端不能直接修改它的参数。\n\n` +
        `应用：${sess.display_name || '—'}\n` +
        `协议：${sess.protocol || '—'}\n` +
        `目标：${sess.target || '—'}\n\n` +
        `是否打开 Web 面板进行编辑？`
      );
      if (go) Views._openWebPanel();
      return;
    }
    Views._openSessionEditor(sess);
  } catch (e) {
    toast('获取会话信息失败: ' + e.message, 'error');
  }
};

/* ---------- 会话编辑弹窗（原地改参数，不必跳去新建页重新建一个会话） ---------- */
Views._openSessionEditor = function (sess) {
  const p = sess.params || {};
  const fallback = {
    ssh: ['🔐 SSH'], rdp: ['🖥 RDP'], vnc: ['🖱 VNC'], http: ['🌐 HTTP'],
    https: ['🔒 HTTPS'], telnet: ['📟 Telnet'], tcp: ['🔌 TCP'], udp: ['📡 UDP'],
    mysql: ['🗄 MySQL'], postgres: ['🗄 PostgreSQL'], sqlserver: ['🗄 SQLServer'],
  };
  const protocols = (typeof TunnelForm !== 'undefined' && TunnelForm.protocols)
    ? TunnelForm.protocols : fallback;
  const protoOptions = Object.keys(protocols).map(k => {
    const label = Array.isArray(protocols[k]) ? protocols[k][0] : (protocols[k].label || k);
    const icon = typeof protocols[k] === 'object' && !Array.isArray(protocols[k])
      ? (protocols[k].icon || '') : '';
    return `<option value="${escapeAttr(k)}" ${k === p.protocol ? 'selected' : ''}>${escapeHtml(icon + ' ' + label)}</option>`;
  }).join('');
  const running = sess.status === 'running' || sess.status === 'starting';
  const val = k => escapeAttr(p[k] == null ? '' : String(p[k]));
  const chk = k => (p[k] ? 'checked' : '');
  const extra = p.extra_argv || [];

  const mask = document.createElement('div');
  mask.className = 'modal-mask session-editor';
  mask.innerHTML = `
    <div class="modal editor-modal">
      <h3 class="modal-title">✏️ 编辑会话参数</h3>
      <div class="editor-head">
        <span class="mono text-sm">${escapeHtml(sess.session_id)}</span>
        <span class="badge ${running ? 'badge-success' : 'badge-muted'}">${running ? '运行中' : '未运行'}</span>
        <span class="text-muted text-sm">来源：桌面端</span>
      </div>
      <div class="editor-body">
        <div class="alert ${running ? 'alert-warning' : 'alert-info'} mb-3">
          <span>${running ? '!' : 'ℹ'}</span>
          <div class="text-sm">${running
            ? '会话正在运行，仅保存不会立即生效。点「保存并重启」可立刻应用新参数（连接会短暂中断）。'
            : '会话当前未运行，保存后点「▶ 启动」即使用新参数；也可直接「保存并启动」。'}</div>
        </div>

        <div class="editor-section-title">基本参数</div>
        <div class="editor-grid">
          <div class="form-row">
            <label class="form-label">协议</label>
            <select class="select" data-field="protocol">${protoOptions}</select>
          </div>
          <div class="form-row">
            <label class="form-label">目标 IP:Port</label>
            <input class="input mono" data-field="target" value="${val('target')}" placeholder="127.0.0.1:22 / 3000">
          </div>
          <div class="form-row">
            <label class="form-label">显示名称</label>
            <input class="input" data-field="display_name" value="${val('display_name')}" placeholder="便于在会话列表识别">
          </div>
          <div class="form-row">
            <label class="form-label">站点名称 (site-name)</label>
            <input class="input" data-field="site_name" value="${val('site_name')}">
          </div>
        </div>

        <div class="editor-section">
          <div class="editor-section-title">认证参数 <span class="text-muted text-xs">SSH / RDP / VNC</span></div>
          <div class="editor-grid">
            <div class="form-row"><label class="form-label">用户名</label>
              <input class="input mono" data-field="username" value="${val('username')}"></div>
            <div class="form-row"><label class="form-label">密码</label>
              <input class="input mono" type="password" data-field="auth_pass" value="${val('auth_pass')}"></div>
            <div class="form-row"><label class="form-label">私钥路径</label>
              <input class="input mono" data-field="private_key" value="${val('private_key')}"></div>
            <div class="form-row"><label class="form-label">私钥口令</label>
              <input class="input mono" type="password" data-field="passphrase" value="${val('passphrase')}"></div>
          </div>
          <label class="checkbox"><input type="checkbox" data-field="enable_sftp" ${chk('enable_sftp')}> 启用 SFTP 文件传输</label>
        </div>

        <div class="editor-section">
          <div class="editor-section-title">数据库参数 <span class="text-muted text-xs">插件协议</span></div>
          <div class="editor-grid">
            <div class="form-row"><label class="form-label">数据库名</label>
              <input class="input mono" data-field="db_name" value="${val('db_name')}"></div>
            <div class="form-row"><label class="form-label">数据库用户</label>
              <input class="input mono" data-field="db_user" value="${val('db_user')}"></div>
            <div class="form-row"><label class="form-label">数据库密码</label>
              <input class="input mono" type="password" data-field="db_pass" value="${val('db_pass')}"></div>
            <div class="form-row"><label class="form-label">只读模式</label>
              <label class="checkbox" style="margin-top:6px"><input type="checkbox" data-field="readonly" ${chk('readonly')}> 强制只读</label></div>
          </div>
        </div>

        <div class="editor-section">
          <div class="editor-section-title">高级选项</div>
          <div class="editor-grid">
            <div class="form-row"><label class="form-label">AC 节点 (visable)</label>
              <input class="input mono" data-field="visable" value="${val('visable')}"></div>
            <div class="form-row"><label class="form-label">隧道端口 (tunnel-port)</label>
              <input class="input mono" data-field="tunnel_port" value="${val('tunnel_port')}"></div>
            <div class="form-row" style="grid-column:1 / -1"><label class="form-label">自定义服务器 (server)</label>
              <input class="input mono" data-field="server" value="${val('server')}" placeholder="https://console.yishield.com/raas"></div>
          </div>
          <div class="editor-switches">
            <label class="checkbox"><input type="checkbox" data-field="invisible" ${chk('invisible')}> 隐身模式</label>
            <label class="checkbox"><input type="checkbox" data-field="verbose" ${chk('verbose')}> 详细日志 (-v)</label>
          </div>
        </div>

        ${extra.length ? `<div class="editor-note">原样保留的自定义参数：<span class="mono">${escapeHtml(extra.join(' '))}</span></div>` : ''}

        <div class="editor-section-title">命令预览</div>
        <div class="cmd-preview" id="editor-cmd">shield …</div>
        <div class="editor-note">仅修改本会话，不会改动已保存的连接预设。</div>
      </div>
      <div class="modal-actions editor-actions">
        <button class="btn" data-act="cancel">取消</button>
        <button class="btn" data-act="save">💾 仅保存</button>
        <button class="btn btn-primary" data-act="restart">${running ? '🔄 保存并重启' : '▶ 保存并启动'}</button>
      </div>
    </div>`;
  document.body.appendChild(mask);

  const preview = () => Views._updateEditorPreview(mask, extra);
  mask.addEventListener('input', preview);
  mask.addEventListener('change', preview);
  preview();

  mask.addEventListener('click', async e => {
    const act = e.target.dataset.act;
    if (e.target === mask || act === 'cancel') { mask.remove(); return; }
    if (act !== 'save' && act !== 'restart') return;
    const btn = e.target;
    btn.disabled = true;
    const params = Views._collectEditorParams(mask);
    if (extra.length) params.extra_argv = extra.slice();
    try {
      const res = await Shield.call('update_session', sess.session_id, params, act === 'restart');
      if (!res || res.error) {
        toast('保存失败: ' + ((res && res.error) || '未知错误'), 'error');
        btn.disabled = false;
        return;
      }
      mask.remove();
      if (res.restarted) toast('参数已保存，会话已用新配置重启', 'success');
      else if (res.need_restart) toast('参数已保存，重启会话后生效', 'success');
      else toast('参数已保存，下次启动时生效', 'success');
      if (Views._logOffsets) delete Views._logOffsets[sess.session_id];
      await refreshSessions();
    } catch (err) {
      toast('保存出错: ' + err.message, 'error');
      btn.disabled = false;
    }
  });
};

Views._collectEditorParams = function (mask) {
  const out = {};
  mask.querySelectorAll('[data-field]').forEach(el => {
    out[el.dataset.field] = el.type === 'checkbox' ? el.checked : (el.value || '').trim();
  });
  return out;
};

Views._updateEditorPreview = async function (mask, extra) {
  const params = Views._collectEditorParams(mask);
  if (extra && extra.length) params.extra_argv = extra;
  try {
    const res = await Shield.call('build_argv', params);
    const el = mask.querySelector('#editor-cmd');
    if (el) el.textContent = 'shield ' + (res.argv || []).join(' ');
  } catch { /* 预览失败不影响保存 */ }
};

Views._restartSession = async function (sid) {
  const res = await Shield.call('restart_session', sid);
  if (res && res.session_id) {
    toast('会话已重新启动', 'success');
    if (Views._logOffsets) delete Views._logOffsets[sid];
    refreshSessions();
  } else {
    toast('启动失败: ' + ((res && res.error) || '未知错误'), 'error');
  }
};

/* 用原参数重新发起连接（保留上一次的日志便于对照） */
Views._retrySession = async function (sid) {
  const res = await Shield.call('retry_session', sid);
  if (res && res.session_id) {
    toast('已重新发起连接，请稍候查看结果', 'success');
    if (Views._logOffsets) delete Views._logOffsets[sid];
    refreshSessions();
  } else {
    toast('重试失败: ' + ((res && res.error) || '未知错误'), 'error');
  }
};

Views._pollSessionLog = function (sid) {
  // Web 会话没有日志流，跳过轮询
  if (String(sid).startsWith('web:')) return;
  // 用 offset 增量拉取
  if (!Views._logOffsets) Views._logOffsets = {};
  const offset = Views._logOffsets[sid] || 0;

  Shield.call('poll_log', sid, offset).then(res => {
    if (!res || !res.exists) return;
    const term = document.getElementById('log-' + sid);
    if (!term) return;
    if (res.text) {
      // 高亮 URL 与失败行
      const html = escapeHtml(res.text)
        .replace(/(https?:\/\/[^\s<]+)/g, '<span class="ln-url">$1</span>')
        .replace(/^([ \t]*[✗×].*)$/gm, '<span class="ln-error">$1</span>');
      if (offset === 0) term.innerHTML = html;
      else term.innerHTML += html;
      term.scrollTop = term.scrollHeight;
    } else if (offset === 0) {
      term.textContent = '（暂无输出）';
    }
    Views._logOffsets[sid] = res.total;
  }).catch(() => {});
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

Views._removeSession = async function (sid, isWeb) {
  const ok = await confirmDialog(
    isWeb ? '删除 Web 面板应用' : '移除会话',
    isWeb
      ? '该会话来自官方 Web 面板，移除会同时删除面板中的应用配置，确定？'
      : '将停止该会话并从列表中移除，确定？'
  );
  if (!ok) return;
  await Shield.call('remove_session', sid);
  if (Views._logOffsets) delete Views._logOffsets[sid];
  toast('会话已移除', 'success');
  refreshSessions();
};
