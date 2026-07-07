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
| **活动会话** | 实时日志轮询，自动提取 Access URL，一键停止/移除 |
| **Web UI 模式** | 调用 `shield start` 启动官方 Web 管理面板，浏览器打开管理 |
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
| `start_tunnel(params)` | 启动隧道子进程 |
| `stop_tunnel(sid)` / `remove_session(sid)` | 停止/移除会话 |
| `list_sessions()` / `poll_log(sid, offset)` | 会话查询与日志轮询 |
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
