# NapCat Connector

> KiraAI 插件 — 通过反向代理集成 NapCat WebUI，无需暴露 NapCat 端口

## Features

| 功能 | 状态 |
|------|------|
| 反向代理 NapCat WebUI（全部流量经 KiraAI） | ✅ |
| WebUI Token 自动登录 | ✅ |
| 系统终端（WebSocket 代理） | ✅ |
| SSE 实时状态/日志 | ✅ |
| 插件扩展页面（如 Stapxs QQ Lite） | ✅ |
| 颜色模式切换（HEAD 检测） | ✅ |
| 配置热更新 | ✅ |
| localStorage 隔离（主题不串） | ✅ |
| 缓存破坏机制（URL 版本段） | ✅ |
| Service Worker 清理 | ✅ |

## Quick Start

### 1. 安装

将插件目录链接到 KiraAI 的插件加载目录（使用 Windows junction，不要用 `ln -s`）：

```cmd
mklink /J D:\Projects\KiraAI-dev\KiraAI-src\data\plugins\napcat_connector D:\Projects\KiraAI-dev\KiraAI-napcat-connector
```

### 2. 配置

在 KiraAI 插件配置页面设置：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `webui_url` | NapCat WebUI 访问地址 | `http://127.0.0.1:6099` |
| `webui_token` | WebUI 登录 token | `（空）` |

### 3. 使用

KiraAI 侧栏出现 **NapCat 控制台** 导航项，点击即加载 NapCat WebUI。

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  浏览器                          │
│   KiraAI 主页面 (http://127.0.0.1:5267)          │
│     └── iframe (sandbox=allow-same-origin)       │
│           │                                      │
│           │ /api/plugin/napcat_connector/entry    │
│           ▼                                      │
│      302 Redirect → /proxy/_v{ts}/webui/?token=xxx│
│           │                                      │
│           ▼                                      │
│  ┌── KiraAI Reverse Proxy ──────────────────┐    │
│  │  GET/POST/HEAD /proxy/_v{ts}/{path}      │    │
│  │     → httpx → http://127.0.0.1:6099/{path}│   │
│  │  WebSocket /ws/plugin/.../terminal       │    │
│  │     → websockets → ws://127.0.0.1:6099/...│   │
│  │  SSE Streaming: 同 GET 代理，流式传输     │    │
│  └───────────────────────────────────────────────┘│
│           │                                      │
│           ▼                                      │
│    NapCat WebUI (端口 6099, 对外不暴露)           │
└─────────────────────────────────────────────────┘
```

## Documentation Index

- [HOW_IT_WORKS.md](HOW_IT_WORKS.md) — 反向代理工作原理与核心技术
- [CONFIGURATION.md](CONFIGURATION.md) — 配置项说明
- [DEVELOPMENT.md](DEVELOPMENT.md) — 开发指南与测试
