# Shield GUI

Shield CLI 的 Windows 桌面 GUI 封装。通过 pywebview 提供原生窗口体验，无需打开终端即可管理 Shield 隧道。

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | 原生 HTML/CSS/JS（无框架依赖） |
| 后端 | Python 3.13+ |
| 桌面容器 | pywebview 6.x（WinForms 原生窗口） |
| 系统托盘 | pystray 0.19+ |
| 进程管理 | subprocess（shield.exe 子进程生命周期） |
| 配置存储 | JSON 文件（兼容 Shield 官方 apps.json 格式） |

## 项目结构

```
shield-gui/
├── main.py                  # 入口：pywebview 窗口创建 + TrayManager（系统托盘）
├── core/
│   ├── api.py               # PythonApi — JS 桥接对象（全部后端方法）
│   ├── shield_runner.py     # ShieldRunner — shield.exe 子进程管理
│   ├── webui_client.py      # WebUIClient — 官方 Web 面板 API（会话同步）
│   ├── updater.py           # 更新通道 — Release 直链 / 镜像下载 / 自我替换
│   ├── process_guard.py     # 更新前枚举并结束全部 shield.exe 进程 / 停服务 / 等文件解锁
│   ├── net_diag.py          # 网络预检（DNS/TCP/TLS/HTTP）+ CLI 启动错误中文诊断 / 代理环境
│   └── config_store.py      # ConfigStore — 配置目录探测 + 预设 CRUD
├── ui/
│   ├── index.html           # 主页面：导航 / 顶栏 / 布局骨架
│   ├── app.js               # 前端核心：路由 / 状态 / TitleBar（拖拽+Resize）
│   ├── styles/
│   │   ├── base.css         # CSS 变量、排版、颜色系统
│   │   ├── layout.css       # 网格 / 导航 / 顶栏 / Resize 手柄
│   │   └── components.css   # 卡片 / 表格 / 按钮 / 表单 / 弹窗组件
│   └── views/
│       ├── dashboard.js     # 仪表盘：统计、快速开始、安装向导
│       ├── tunnel-new.js    # 新建隧道：协议选择 + 表单 + 命令预览 + 内置预设
│       ├── presets.js       # 连接预设：列表/启动/删除
│       ├── sessions.js      # 活动会话：实时日志 + 访问 URL + 停止
│       ├── protocols.js     # 协议指南：8 种协议的用法与示例
│       ├── plugins.js       # 插件管理：安装/移除/升级
│       ├── service.js       # 系统服务：Web UI 启动 / 服务安装卸载
│       ├── credentials.js   # 凭证与安全：加密机制与清理
│       └── settings.js      # 应用配置：服务器/节点/缓存
└── pyproject.toml           # 项目元数据与依赖声明
```

## 功能特性

| 功能 | 说明 |
|---|---|
| **新建隧道** | 选择 8 种协议（SSH/RDP/VNC/HTTP/HTTPS/Telnet/TCP/UDP），填写目标地址即生成 CLI 命令 |
| **连接预设** | 保存常用隧道配置，一键启动；兼容 Shield 官方 apps.json 格式；内置 21 种常用端口预设 |
| **活动会话** | 实时日志轮询，自动提取 Access URL，一键停止/移除；**最多 10 个会话、同时连接 3 个** |
| **Web UI 模式** | 调用 `shield start` 启动官方 Web 管理面板；**面板里添加的应用会同步到「活动会话」**，与桌面端共用 3 并发 / 10 会话额度 |
| **应用内更新** | 不跳转 GitHub：下载 Release 直链或镜像（ghproxy.net / v4.gh-proxy.org），并行测速取最快通道；GUI 自替换并重启，CLI 先结束全部 shield.exe 进程再替换 shield.exe（保留 .bak，失败回滚），完成后自动恢复 Web 面板与会话 |
| **系统服务** | 安装/卸载/启停 Windows 服务 ShieldCLI（需管理员权限） |
| **插件管理** | 安装/移除/升级 MySQL、PostgreSQL、SQL Server 数据库插件 |
| **协议指南** | 8 种协议的详细用法、命令示例与要点备忘 |
| **凭证安全** | AES-256-GCM 加密、隐身模式、缓存清理 |
| **系统托盘** | 关闭窗口隐藏到托盘后台常驻，托盘菜单可快速新建隧道/打开 Web UI/检查更新 |
| **Frameless 窗口** | 自定义标题栏 + 拖拽移动 + 边缘/角部 Resize 手柄 + 最大化/最小化/关闭 |

## 快速开始

### 前置条件

1. 安装 [Shield CLI](https://www.yishield.com/download)
   - 或通过包管理器：`winget install yishield.shieldcli`
2. 确认 `shield.exe` 在系统 PATH 中
3. 安装 Python 3.13+ 和 pywebview

### 启动 GUI

```bash
cd shield-gui
pip install pywebview
python main.py
```

### 使用工作流

```
未安装 SHIELD                    已安装 SHIELD
    │                                  │
    ├─ 仪表盘显示安装向导              ├─ 仪表盘：统计 + 快速开始
    │   ├─ 下载官网 / winget           │   ├─ 新建隧道（命令行模式）
    │   ├─ 手动安装说明                │   ├─ 从预设启动
    │   └─ 重新检测按钮                │   └─ Web UI / 系统服务
    │                                  │
    └─ 安装完成后重启 GUI              └─ 新建隧道 → 选择协议 → 填写目标 → 启动
                                              │
                                              └─ 保存为预设（下次一键启动）
```

## 路由表

| 路由 | 视图 | 说明 |
|---|---|---|
| `dashboard` | 仪表盘 | 服务总览、状态统计、快速开始 / 安装向导 |
| `tunnel-new` | 新建隧道 | 协议选择 + 参数表单 + 实时命令预览 |
| `presets` | 连接预设 | 已保存配置的管理 |
| `sessions` | 活动会话 | 运行中隧道的实时日志、URL、停止 |
| `protocols` | 协议指南 | 8 种协议的详细用法文档 |
| `plugins` | 插件管理 | 数据库插件的安装与管理 |
| `service` | 系统服务 | Web UI 启动、服务安装/卸载/启停 |
| `credentials` | 凭证与安全 | 加密机制说明、凭证缓存清理 |
| `settings` | 应用配置 | 自定义服务器、默认参数、缓存 |

## API 桥接（pywebview js_api）

前端通过 `window.pywebview.api.<method>()` 调用以下后端方法：

| 方法 | 用途 |
|---|---|
| `get_env()` | 环境检测（版本、路径、协议） |
| `build_argv(params)` | 表单参数 → shield argv |
| `start_tunnel(params, force=False)` | 启动隧道（合并默认设置 → 网络预检 → spawn；预检失败返回 `need_confirm`，`force=True` 跳过预检） |
| `probe_server(server, proxy)` | 分阶段测试控制台连通性，返回各阶段耗时与中文建议 |
| `retry_session(sid)` / `restart_session(sid)` | 复用原参数重试/重启，保留上次日志与重试计数 |
| `stop_tunnel(sid)` / `remove_session(sid)` | 停止/移除会话（`web:<id>` 走 Web 面板 API） |
| `list_sessions()` / `poll_log(sid, offset)` | 会话查询与日志轮询（本地 + Web 面板合并） |
| `session_limits()` | 容量占用：并发 x/3、会话 y/10、Web 面板在线状态 |
| `web_ui_info()` | Web 面板在线状态、版本、应用数、已连接数 |
| `check_updates()` | 检测 GUI/CLI 新版本，返回直链 + 镜像候选链接 |
| `install_update(target)` | 应用内下载并替换（`gui` 自替换重启 / `shield` 替换 shield.exe） |
| `get_update_config()` / `save_update_mirrors(list)` | 更新通道与镜像前缀读写 |
| `start_web_ui(port)` | 启动 Web UI 服务（shield start） |
| `open_web_ui(port)` | 浏览器打开 Web UI |
| `service_install/stop/uninstall()` | 系统服务管理 |
| `plugin_list/add/remove/upgrade()` | 插件管理 |
| `list_presets/save_preset/del_preset()` | 预设管理 |
| `clean_credentials()` | 凭证缓存清理 |
| `load_settings/save_settings()` | 用户设置读写 |
| `pick_private_key()` | 文件对话框选择私钥 |
| `window_minimize/maximize/restore` | 窗口最小化/最大化/还原 |
| `window_close` | 关闭→隐藏到系统托盘（close-to-tray） |
| `window_show/hide` | 窗口显隐控制 |
| `window_move_by(dx, dy)` | 标题栏拖拽移动 |
| `window_get_bounds` / `window_set_bounds` | 窗口位置/尺寸读写（边缘 Resize） |

## 常见问题

**Q：启动会话报错 `HTTP request failed: Post "https://console.yishield.com/raas/api/public/quick-setup": context deadline exceeded (Client.Timeout exceeded while awaiting headers)`？**
A：这不是隧道参数错，而是 **CLI 启动时要先向控制台注册（quick-setup），等待响应头超时了**。常见原因是到 `console.yishield.com` 的链路丢包、服务端繁忙，或系统代理已失效导致请求一直挂起（Go 的 `net/http` 会读 `HTTP_PROXY/HTTPS_PROXY`，代理软件没开但注册表/环境变量还留着地址时最容易中招）。GUI 现在的处理方式：

1. **启动前预检**：分阶段探测 DNS → TCP → TLS → HTTP（约 2.5 秒，成功结果缓存 5 分钟），不通时弹出中文诊断，可选择「仍要启动」，不会硬拦。
2. **失败不再假装运行中**：CLI 打印 `✗ Connection failed` 或异常退出时，会话状态立即纠正为「错误」，并附上中文原因与处理建议、推送通知；原始日志仍完整保留。
3. **重试**：可恢复错误（超时 / 5xx）默认自动重试 1 次，也能在会话卡片点「🔁 重试」；重试会复用原参数并保留上次日志。自动重试次数在「应用配置 → 网络与连接」可调（0–3）。
4. **换通道**：在同一处可填 HTTP 代理（传给 CLI 子进程），或改自定义服务器地址；点「🔌 测试连接」可看到各阶段耗时。设置页保存的 `--server` 现在会真正作用于所有新建隧道。

若只是偶发抖动，稍后重试即可；若持续超时，优先检查代理软件状态与 DNS，并在「应用配置」里做一次连接测试定位卡在哪一阶段。

**Q：更新时提示「所有下载通道均失败」？**
A：在「应用配置 → 更新通道」里确认镜像前缀可用（默认 `https://ghproxy.net/`、`https://v4.gh-proxy.org/`），可增删或换成自建镜像；应用会并行测速，优先走最快的通道，直链作为兜底。

**Q：更新 GUI 后程序自动关闭了？**
A：这是正常的自替换流程：新版本下载到临时目录后，由守护脚本在本进程退出后覆盖 exe 并重新启动。源码运行（`python main.py`）时无法替换自身，只会把新版本下载到临时目录并提示路径。

**Q：仪表盘显示「TypeError: Views.dashboard is not a function」？**
A：说明 `ui/views/dashboard.js` 没被加载成功，通常是 WebView2 缓存了空/损坏的脚本副本，或者运行的是旧版打包 exe（内嵌资源不会随源码更新）。现在的 `index.html` 给所有脚本加了版本号参数绕开缓存；`app.js` 启动时会检查全部视图函数，缺失的脚本自动带随机参数重载一次（提示「已自动恢复 N 个页面脚本」），进入页面时若仍缺失也会再自愈。若继续报错，请用源码运行 `python main.py` 验证，或重新构建 exe。

**Q：更新 Shield CLI 会不会把正在跑的隧道弄断？**
A：会短暂中断，这是必要步骤。运行中的 `shield.exe` 会锁住目标文件，因此更新时先结束**所有** shield.exe 进程（桌面隧道、Web 面板、系统托盘、命令行实例、Windows 服务），确认文件解除占用后才替换。替换完成后 GUI 会按原端口重启 Web 面板、重连面板应用并恢复之前的隧道会话（受 3 个并发上限约束，超出部分需手动启动）；新版本无法运行或版本未提升时自动用 `shield.exe.bak` 回滚，失败时同样会恢复原有会话。

**Q：Web 面板里添加的应用为什么没出现在「活动会话」？**
A：需要面板在线（`shield start` 或系统服务运行中）。GUI 每 2 秒拉取一次 `/api/apps`；离线时列表只显示桌面端会话。面板端口可在「应用配置 → 会话容量」调整。

**Q：为什么最多只能同时连 3 个、最多 10 个会话？**
A：这是内置容量约束（Web 面板应用与桌面隧道共用额度）。达到上限时启动会被拒绝，需先停止或移除不用的会话。

**Q：点击"新建隧道"后协议选择区是空的？**
A：这是 0.1.0 版本的已知问题，已在后续版本修复。刷新页面或重启 GUI 即可。

**Q：关闭窗口后程序去哪了？**
A：点击关闭按钮会将窗口隐藏到系统托盘，程序仍在后台运行。可从托盘菜单「退出」彻底关闭，或双击托盘图标恢复窗口。

**Q：Web UI 启动后无法访问？**
A：确认端口未被占用。在「系统服务」页修改端口后重新启动。也可手动运行 `shield start <port>` 排查输出日志。

**Q：shield.exe 已安装但 GUI 检测不到？**
A：确认 shield.exe 在 PATH 环境变量中。重启 Shield GUI 后会自动重新检测。如仍未识别，可在终端执行 `shield --version` 确认安装正常。

**Q：frameless 窗口如何调整大小？**
A：将鼠标移动到窗口边缘（上下左右）或四角，光标变为双向箭头后拖拽即可调整窗口大小。最大化时可点击标题栏右侧的 □ 按钮。

## 许可证

MIT License
