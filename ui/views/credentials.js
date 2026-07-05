/* 凭证与安全视图 */
Views.credentials = function () {
  return `
    <div class="view-header">
      <h1 class="view-title">凭证与安全</h1>
      <p class="view-desc">Shield 使用强加密保护本地凭证；了解连接流程与访问模式</p>
    </div>

    <div class="grid grid-2 mb-4">
      <div class="card">
        <div class="card-header"><h3 class="card-title">🧹 清除缓存凭证</h3></div>
        <p class="text-secondary text-sm mb-4">
          清除 Shield 本地缓存的凭证（密码、私钥口令等）。清除后已保存的连接预设仍保留，
          但下次连接需要重新输入凭证。
        </p>
        <button class="btn btn-danger" onclick="Views._cleanCreds()">🧹 清除缓存</button>
        <div id="clean-output" class="mt-4"></div>
      </div>

      <div class="card">
        <div class="card-header"><h3 class="card-title">🔐 加密机制</h3></div>
        <table class="table">
          <tr><td class="text-muted">算法</td><td>AES-256-GCM</td></tr>
          <tr><td class="text-muted">密钥派生</td><td>机器指纹</td></tr>
          <tr><td class="text-muted">密码存储</td><td><span class="badge badge-success">不存储</span></td></tr>
          <tr><td class="text-muted">日志脱敏</td><td><span class="badge badge-success">自动</span></td></tr>
          <tr><td class="text-muted">凭证传输</td><td>TLS 端到端</td></tr>
        </table>
      </div>
    </div>

    <div class="card mb-4">
      <div class="card-header"><h3 class="card-title">👁 访问模式</h3></div>
      <div class="grid grid-2">
        <div>
          <div class="badge badge-success mb-2">默认</div>
          <h4 style="margin:0 0 var(--sp-2)">可见模式</h4>
          <p class="text-secondary text-sm">Access URL 公开可访问，任何拿到链接的人都能使用。适合临时分享、快速演示。</p>
          <div class="cmd-preview mt-2">shield http 3000</div>
        </div>
        <div>
          <div class="badge badge-warning mb-2">高安全</div>
          <h4 style="margin:0 0 var(--sp-2)">隐身模式</h4>
          <p class="text-secondary text-sm">Access URL 需带授权码才能访问，URL 不在公开列表中显示。适合敏感服务。</p>
          <div class="cmd-preview mt-2">shield http 3000 --invisible</div>
        </div>
      </div>
    </div>

    <div class="card mb-4">
      <div class="card-header"><h3 class="card-title">🔄 连接流程</h3></div>
      <div style="font-family:var(--font-mono);font-size:var(--fs-sm);color:var(--text-secondary);background:var(--bg-base);padding:var(--sp-4);border-radius:var(--r-md);overflow-x:auto;user-select:text">
        <span class="text-muted"># 整体架构</span><br>
        内网服务 <span class="text-accent">←→</span> Shield CLI <span class="text-accent">←→</span> 公网服务器 <span class="text-accent">←→</span> 浏览器<br><br>
        <span class="text-muted"># 步骤</span><br>
        <span class="text-accent">1.</span> 用户执行 <span class="text-accent">shield &lt;proto&gt; [target]</span><br>
        <span class="text-accent">2.</span> Shield 建立到公网服务器的 WebSocket 隧道<br>
        <span class="text-accent">3.</span> 服务器分配 Access URL（如 https://xxx.yishield.com）<br>
        <span class="text-accent">4.</span> 浏览器访问 URL，流量经加密隧道转发到内网服务<br>
        <span class="text-accent">5.</span> 支持 <span class="text-accent">--invisible</span> 隐身模式与断线重连
      </div>
    </div>

    <div class="card">
      <div class="card-header"><h3 class="card-title">🛡 安全最佳实践</h3></div>
      <ul class="text-secondary text-sm" style="margin:0;padding-left:var(--sp-5)">
        <li style="margin-bottom:var(--sp-2)">敏感服务务必启用 <code class="mono">--invisible</code> 隐身模式</li>
        <li style="margin-bottom:var(--sp-2)">使用最小权限账号（避免 root/administrator 直连）</li>
        <li style="margin-bottom:var(--sp-2)">私钥优先于密码认证（SSH 场景）</li>
        <li style="margin-bottom:var(--sp-2)">定期执行 <code class="mono">shield clean</code> 清理缓存凭证</li>
        <li style="margin-bottom:var(--sp-2)">数据库访问启用 <code class="mono">--readonly</code> 只读模式</li>
        <li>用完即停，避免长时间暴露内网服务</li>
      </ul>
    </div>
  `;
};

Views._mount_credentials = function () {};

Views._cleanCreds = async function () {
  const ok = await confirmDialog('清除缓存凭证',
    '将清除本地所有缓存的凭证（密码/口令）。已保存的连接预设会保留，但下次连接需重新输入凭证。继续？');
  if (!ok) return;
  const res = await Shield.call('clean_credentials');
  const out = (res.stdout || '') + (res.stderr || '');
  const el = document.getElementById('clean-output');
  el.innerHTML = `<div class="terminal" style="user-select:text">${escapeHtml(out || '已清除')}</div>`;
  toast('缓存凭证已清除', 'success');
};
