/* 协议指南视图 */
Views.protocols = function () {
  const data = [
    {k:'ssh',    icon:'🔐', name:'SSH',     port:22,   auth:true,  color:'accent',
     desc:'在浏览器中打开完整的 SSH 终端（基于 xterm.js），支持密码认证、私钥认证和 SFTP 文件传输。',
     cmds:['shield ssh','shield ssh 2222','shield ssh 10.0.0.2','shield ssh 10.0.0.2:2222','shield ssh 192.168.1.10 --username root --auth-pass secretpw','shield ssh 10.0.0.2 --private-key ~/.ssh/id_rsa --enable-sftp'],
     notes:['默认目标 127.0.0.1:22','私钥支持口令保护 (--passphrase)','--enable-sftp 开启文件传输']},
    {k:'rdp',    icon:'🖥',  name:'RDP',     port:3389, auth:true,  color:'info',
     desc:'在浏览器中访问 Windows 远程桌面，完整鼠标键盘控制，无需安装 RDP 客户端。',
     cmds:['shield rdp','shield rdp 192.168.1.100','shield rdp 192.168.1.100:3390','shield rdp 10.0.0.5 --username administrator --auth-pass P@ssw0rd'],
     notes:['默认目标 127.0.0.1:3389','需要目标机已开启远程桌面','支持自定义端口']},
    {k:'vnc',    icon:'🖱',  name:'VNC',     port:5900, auth:true,  color:'purple',
     desc:'在浏览器中共享和控制远程桌面屏幕，像素级渲染，完整鼠标键盘映射。',
     cmds:['shield vnc','shield vnc 192.168.1.50','shield vnc 10.0.0.8:5901 --auth-pass vncpass'],
     notes:['默认目标 127.0.0.1:5900','支持 VNC 密码认证','适合 Linux/macOS 桌面共享']},
    {k:'http',   icon:'🌐', name:'HTTP',    port:80,   auth:false, color:'success',
     desc:'将本地或内网 HTTP Web 应用暴露到公网，完整代理请求，保留 Headers、Cookies、WebSocket。',
     cmds:['shield http 3000','shield http 10.0.0.5:8080','shield http 8080 --site-name my-blog'],
     notes:['默认目标 127.0.0.1:80','支持 WebSocket 透传','适合本地开发预览、内网管理系统']},
    {k:'https',  icon:'🔒', name:'HTTPS',   port:443,  auth:false, color:'success',
     desc:'将本地或内网 HTTPS Web 应用暴露到公网，TLS 由本地服务处理。',
     cmds:['shield https 8443','shield https 10.0.0.5','shield https 10.0.0.5 --visable=HK'],
     notes:['--visable 指定 AC 节点区域','默认目标 127.0.0.1:443','证书由本地提供']},
    {k:'telnet', icon:'📟', name:'Telnet',  port:23,   auth:true,  color:'warning',
     desc:'连接 Telnet 服务，适用于路由器、交换机等网络设备和传统系统管理。',
     cmds:['shield telnet','shield telnet 192.168.1.1','shield telnet 10.0.0.254 --username admin'],
     notes:['默认目标 127.0.0.1:23','明文协议，仅用于受信内网','网络设备运维常用']},
    {k:'tcp',    icon:'🔌', name:'TCP',     port:0,    auth:false, color:'info',
     desc:'通用 TCP 端口代理，转发 MySQL、Redis、PostgreSQL 等任意 TCP 服务，无需浏览器。',
     cmds:['shield tcp 3306','shield tcp 192.168.1.10:6379','shield tcp 5432  # PostgreSQL'],
     notes:['无默认端口，必须指定','数据库通常需插件 (mysql/postgres/sqlserver)','转发到本地随机端口']},
    {k:'udp',    icon:'📡', name:'UDP',     port:0,    auth:false, color:'info',
     desc:'通用 UDP 端口代理，适用于 DNS、SNMP 等基于 UDP 的服务。',
     cmds:['shield udp 53','shield udp 192.168.1.1:53  # DNS'],
     notes:['无默认端口，必须指定','常用于 DNS 转发','不建立浏览器会话']},
  ];

  return `
    <div class="view-header">
      <h1 class="view-title">协议指南</h1>
      <p class="view-desc">Shield CLI 支持 8 种协议，覆盖终端、桌面、Web、数据库、网络设备</p>
    </div>
    <div class="grid" style="gap:var(--sp-5)">
      ${data.map(p => `
        <div class="card">
          <div class="card-header">
            <h3 class="card-title">${p.icon} ${p.name}
              <span class="badge badge-${p.color}" style="margin-left:8px">${p.port ? ':' + p.port : '自定义'}</span>
              ${p.auth ? '<span class="badge badge-info">需认证</span>' : '<span class="badge badge-muted">无需认证</span>'}
            </h3>
            <button class="btn btn-sm" onclick="navigate('tunnel-new');setTimeout(()=>TunnelForm.select('${p.k}'),100)">
              ⚡ 用此协议新建
            </button>
          </div>
          <p class="text-secondary mb-4">${p.desc}</p>
          <div style="display:grid;grid-template-columns:1fr 280px;gap:var(--sp-4)">
            <div>
              <div class="text-muted text-xs mb-2">常用命令</div>
              ${p.cmds.map(c => `<div class="cmd-preview mb-2">${escapeHtml(c)}</div>`).join('')}
            </div>
            <div>
              <div class="text-muted text-xs mb-2">要点</div>
              <ul style="margin:0;padding-left:var(--sp-5);color:var(--text-secondary);font-size:var(--fs-sm)">
                ${p.notes.map(n => `<li style="margin-bottom:var(--sp-1)">${escapeHtml(n)}</li>`).join('')}
              </ul>
            </div>
          </div>
        </div>`).join('')}
    </div>
  `;
};
Views._mount_protocols = function () {};
