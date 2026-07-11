# 反向代理工作原理

## 核心流程

```
浏览器请求 → KiraAI 路由 → 插件 API 端点 → 代理 NapCat → 返回重写后内容
```

### 1. 入口导航

```
用户点击导航 → Vue Router → /plugin-page/napcat_connector/napcat
  → PluginPageView iframe → src=/page/plugin/napcat_connector/napcat
  → 307 redirect → /api/plugin/napcat_connector/entry
  → 302 redirect → /api/plugin/napcat_connector/proxy/_v{ts}/webui/?_t=xxx&token=xxx
```

`/entry` 端点每次动态读取配置，拼 token 后 302 跳转。`_v{ts}` 是时间戳版本段，用于**缓存破坏**。

### 2. 反向代理 (`_proxy` 方法)

全部 GET/POST/HEAD 请求统一经过 `_proxy`：

```
/proxy/{path:path} → 剥离 _v{ts}/ → http://127.0.0.1:6099/{path}
```

**转发逻辑**：
1. 剥离版本段 `_v{timestamp}/`
2. 动态读取 `webui_url` 配置作为 NapCat 地址
3. 转发 query string
4. 透传请求头（Authorization, Cookie, Content-Type 等）
5. 剥离条件缓存头（If-None-Match, If-Modified-Since）

**响应处理**：
1. 剥离不兼容头（X-Frame-Options, CSP, Content-Encoding, ETag, Last-Modified）
2. 设置 `Cache-Control: no-store`
3. 对文本内容（HTML/JS/CSS/JSON）做路径重写
4. 二进制内容（图片、字体、音频）直接透传

### 3. 路径重写

使用正则替换，将 NapCat 返回内容中的绝对路径改写为代理路径：

| 规则 | 匹配 | 替换为 |
|------|------|--------|
| `REWRITE_API` | `"/api/xxx"` | `"{PROXY}/_v{ts}/api/xxx"` |
| `REWRITE_WEBUI` | `"/webui/xxx"` | `"{PROXY}/_v{ts}/webui/xxx"` |
| `REWRITE_FILES` | `"/files/xxx"` | `"{PROXY}/_v{ts}/files/xxx"` |
| `REWRITE_PLUGIN` | `"/plugin/xxx"` | `"{PROXY}/_v{ts}/plugin/xxx"` |

**防二次重写**：`(?!/plugin)` 负向预查防止代理前缀（含 `/api/plugin`）被再次匹配。

**模板字面量支持**：字符类包含反引号 `` ` `` 和 `$`，匹配 ES6 模板字符串中的路径。

### 4. `<base>` 标签（一了百了）

在 HTML 中注入 `<base href="{PROXY}/_v{ts}/">`，浏览器自动将所有相对 URL（`fetch`、`XHR`、`EventSource`、`<script src>`、`<link href>`、`<iframe src>`）解析为代理路径:

```
fetch("/api/auth/login")
  → 浏览器解析为 {PROXY}/_v{ts}/api/auth/login
  → 自动走代理 → NapCat
```

任何未在正则规则中覆盖的路径都能被捕获，实现"一了百了"。

### 5. WebSocket 代理

系统终端使用 WebSocket 连接，不走 HTTP 代理。解决方案：

```
WS 连接 → KiraAI → @register.ws("/terminal") → ws://127.0.0.1:6099/api/ws/terminal
```

1. JS 中 WebSocket pathname 被改写为 `/ws/plugin/napcat_connector/terminal`
2. KiraAI 接收 WS 升级请求，路由到插件处理器
3. 处理器解析 `?id=xxx&token=xxx`，连接 NapCat WebSocket
4. `asyncio.gather` 双向并发转发

### 6. SSE 流式代理

NapCat 的实时状态/日志使用 EventSource。代理识别 `text/event-stream` 响应后，使用 `httpx` 流式读取 + `StreamingResponse` 流式返回：

```
请求 → GET /proxy/api/base/GetSysStatusRealTime
  → httpx 流式转发 GET http://127.0.0.1:6099/api/base/GetSysStatusRealTime
  → 逐 chunk 转发给浏览器
```

### 7. 缓存破坏

NapCat 的 JS 文件名带 hash，版本不变则 hash 不变，浏览器会用缓存旧版本。

**三层防护**：
1. **版本段** `_v{timestamp}`：每次插件加载生成新值，URL 不同，缓存无效
2. **`Cache-Control: no-store`**：禁止浏览器存储
3. **剥离 ETag/Last-Modified**：避免 304 条件请求

## 关键技术决策

### localStorage 隔离

同源 iframe 与主窗口共享 `Storage.prototype`，但 `localStorage` 实例不同。使用 `this === window.localStorage` 区分调用者：

- iframe 内调用 → 加 `napcat_` 前缀
- 主窗口调用 → 不加前缀

### Service Worker 处理

NapCat 注册 SW 缓存资源。代理环境下 SW 可能缓存未重写的旧 JS 导致 422。

**三层处理**：
1. 拦截 `sw.js` 请求（返回 404）
2. 禁用 SW 注册代码（替换为 `false&&`)
3. 清理已注册的旧 SW（页面加载时自动 unregister）

### HEAD 方法

Stapxs 插件切换颜色时使用同步 `XMLHttpRequest HEAD` 检查 dark/light CSS 文件是否存在。必须注册 HEAD 端点，否则返回 405 → 报错"无法切换颜色模式"。

### Token 注入

通过 entry 端点的 302 跳转将 token 放入 URL query string，浏览器 SPA 组件 `web_login` 用 `new URLSearchParams(window.location.search).get("token")` 提取，触发自动登录。
