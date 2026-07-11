# 反向代理工作原理

## 核心流程

```
浏览器请求 → KiraAI 路由 → 插件 API 端点 → 代理 NapCat → 返回重写后内容
```

### 1. 入口导航

```
用户点击导航 → Vue Router → /plugin-page/napcat_connector/napcat
  → PluginPageView iframe → src=/page/plugin/napcat_connector/napcat
  → 302 redirect → /api/plugin/napcat_connector/proxy/_v{ts}/webui/?_t=xxx&token=xxx
```

`/entry` 端点每次动态读取配置，拼 token 后 302 跳转。`_v{ts}` 是时间戳版本段，用于**缓存破坏**。

### 2. 反向代理 (`_proxy` 方法)

全部 6 种 HTTP 方法（GET/POST/PUT/DELETE/PATCH/HEAD）统一经过 `_proxy`：

```
/{path:path} → 剥离 _v{ts}/ → http://127.0.0.1:6099/{path}
```

**转发逻辑**：
1. 剥离版本段 `_v{timestamp}/`
2. 动态读取 `webui_url` 配置作为 NapCat 地址
3. 转发 query string
4. 透传请求头（Authorization, Cookie, Content-Type 等）
5. 剥离条件缓存头（If-None-Match, If-Modified-Since）

**共享连接池**：所有代理请求复用同一个 `httpx.AsyncClient` 实例（`HttpClientManager`），避免每次请求 TCP 重新握手。连接池限制：最大 100 连接，20 个 keep-alive。

**响应处理**：
1. HEAD 请求不读 body（短路优化）
2. 剥离不兼容头（X-Frame-Options, CSP, Content-Encoding, ETag, Last-Modified）
3. 设置 `Cache-Control: no-store`
4. SSE 流式响应：`resp.aiter_bytes()` → `StreamingResponse`
5. 非流式文本（HTML/JS/CSS/JSON）做路径重写
6. 二进制内容（图片、字体、音频）直接透传

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

所有 WebSocket 连接经通配 WS 端点 `@register.ws("/{ws_path:path}")` 代理。

```
WS 连接 → KiraAI → @register.ws("/{ws_path:path}") → ws://127.0.0.1:6099/{ws_path}
```

关键机制：
1. **WebSocket 构造器拦截**：在 HTML `<head>` 中注入脚本，在运行时拦截所有 `new WebSocket(url)` 调用，自动将 URL 重写为 KiraAI 的 WS 代理路径
2. **通配端点**：单个 `@register.ws("/{ws_path:path}")` 处理所有 WS 连接（终端、插件 Debug 等），`ws_path` 从 URL 路径捕获后完整转发
3. **query params 透传**：`?id=xxx&token=yyy` 等参数自动透传给 NapCat
4. **配置热更新**：NapCat 地址从 `self.plugin_cfg.get("webui_url")` 读取，`http://` → `ws://` 自适应转换

**安全约束**：NapCat 端口（6099）不暴露给浏览器，所有 WS 流量经 KiraAI 中转。浏览器 DevTools 中看不到任何 `ws://127.0.0.1:6099` 直连。

### 6. SSE 流式代理

NapCat 的实时状态/日志使用 EventSource。代理识别 `text/event-stream` 响应后，使用 httpx 原生流式读取 + `StreamingResponse` 流式返回：

```
请求 → GET /proxy/api/base/GetSysStatusRealTime
  → 共享 httpx client.stream=True → GET http://127.0.0.1:6099/api/base/GetSysStatusRealTime
  → resp.aiter_bytes() 逐 chunk → StreamingResponse
```

无需线程池，完全异步。

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

### WebSocket 构造器拦截

在 `build_inject_html` 中注入，在 NapCat 所有 JS 执行前运行：

```javascript
window.WebSocket = function(url, protos) {
  try {
    var u = new URL(url);
    u.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    u.host = location.host;
    u.pathname = '/ws/plugin/napcat_connector' + u.pathname;
    url = u.toString();
  } catch(e) {}
  return protos ? new OW(url, protos) : new OW(url);
};
```

- 保留 prototype 和静态常量（`CONNECTING`、`OPEN`、`CLOSING`、`CLOSED`）
- 不依赖编译期字符串匹配，一了百了

### HTTP 方法覆盖

注册 6 种方法：GET/POST/PUT/DELETE/PATCH/HEAD。覆盖 NapCat 所有 HTTP 操作：
- HEAD：Stapxs 插件切换颜色时用同步 `XMLHttpRequest HEAD` 检查 CSS
- PUT/DELETE/PATCH：配置修改、删除等操作

### Token 注入

通过 entry 端点的 302 跳转将 token 放入 URL query string，浏览器 SPA 组件 `web_login` 用 `new URLSearchParams(window.location.search).get("token")` 提取，触发自动登录。

### 纯函数模块（`proxy_utils.py`）

所有可测试的逻辑提取到 `proxy_utils.py`：
- 常量、正则规则
- 路径重写、版本剥离、entry URL 构建
- Content-Type 判断、WS URL 构建
- HTML 注入模板（`<base>`、localStorage 隔离、SW 清理、WS 拦截器）
- `HttpClientManager` 连接池管理

单元测试直接 import `proxy_utils`，不依赖 KiraAI 运行时。
