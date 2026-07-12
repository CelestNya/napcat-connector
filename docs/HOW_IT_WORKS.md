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

在 HTML 中注入 `<base href="{PROXY}/_v{ts}/">` 和启动脚本（SW 清理 + WS 拦截器）：

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
1. **版本段** `_v{timestamp}`：每次插件初始化和 entry 请求时生成新值，URL 不同，缓存无效
2. **`Cache-Control: no-store`**：禁止浏览器存储（302 重定向也需要，防止浏览器缓存旧的 entry 响应）
3. **剥离 ETag/Last-Modified**：避免 304 条件请求

### localStorage 隔离（defineProperty）

NapCat 和 KiraAI 同源（`127.0.0.1:5267`），共享同一个 `localStorage` 对象。两者如果使用相同的 key（如 `theme`、`token`、`options`），会直接互相污染。

**方案**：在 iframe HTML 的 `<head>` 中注入 `Object.defineProperty` 脚本，用代理对象替换 iframe 的 `window.localStorage`：

```javascript
var proxy = {
    getItem: function(n) { return _ls.getItem(p + n); },         // p = "napcat_"
    setItem: function(n, v) { _ls.setItem(p + n, v); },
    removeItem: function(n) { _ls.removeItem(p + n); },
    ...
};
Object.defineProperty(window, "localStorage", {
    value: proxy, writable: false, configurable: false
});
```

- 所有 iframe 内的 `localStorage.getItem("theme")` → 实际读写 `napcat_theme`
- 主窗口 KiraAI 的 `localStorage.getItem("theme")` → 不变（因为主窗口的 `localStorage` 没被替换）

**关键经验**：
- ❌ 不要修改 `Storage.prototype` -- 所有同源窗口共享原型，会污染主窗口
- ❌ 不要对存储值做格式转换（JSON.stringify）-- token 是 base64，加引号后 NapCat auth 解码失败 -> 401 循环
- ❌ 不要迁移 token/jwt_token -- 旧隔离脚本遗留的过期凭证会导致 401 无限重试
- ❌ **不要主动 `removeItem("napcat_token")`** -- 所有经代理的 iframe（含 NapCat 拓展插件嵌套 iframe）同源共享同一真实 localStorage，嵌套 iframe 加载时的 bootstrap 会删掉主 iframe 的有效 token -> NapCat 检测 token 丢失 -> 跳 web_login -> 拓展页面 401
- ✅ 使用 `Object.defineProperty(window, "localStorage", ...)` 只影响当前 iframe
- ✅ token 的生命周期完全交给 NapCat 自身管理（URL token 登录 -> 写 localStorage），代理只负责隔离前缀

**历史回溯**：

| 阶段 | 方案 | 问题 |
|------|------|------|
| 第一阶段 | 修改 `Storage.prototype` | 污染主窗口，KiraAI localStorage 也被前缀化 |
| 第二阶段 | 直接删除隔离 | theme/token key 直接冲突 |
| 第三阶段 | `defineProperty` + `fmt()` 格式化 | fmt 给 token 加 JSON 引号 -> 401 循环 |
| 第四阶段 | `defineProperty` + 主动清除 token | 主页面稳定，但拓展页面 401（见下） |
| 第五阶段 ✅ | `defineProperty` + 不动 token | 完全稳定，token 生命周期交还 NapCat |

**第五阶段修复（拓展页面 401）**：

第四阶段的 bootstrap_js 含 `_ls.removeItem(p+"token")`，本意是清除旧隔离脚本遗留的过期凭证。但所有经代理的 iframe 同源共享 localStorage，点击 NapCat "扩展" 时加载的拓展插件 iframe（如 Stapxs QQ Lite dashboard）也会执行 bootstrap，**删除了主 iframe 刚写入的有效 `napcat_token`**。因果链：

```
点击扩展 -> 拓展 iframe 加载 -> bootstrap removeItem("napcat_token")
-> 主 iframe 的 NapCat JS 检测 token 丢失 -> setItem("token","") -> 跳 web_login
-> 拓展页面 401
```

修复：移除 bootstrap 中所有 `removeItem(p+"token")` / `removeItem(p+"jwt_token")`，token 生命周期完全交给 NapCat 自身管理。迁移时仍跳过 token/jwt_token（不把无前缀旧值覆盖到 napcat_ 前缀）。

## 直连模式

从 v0.2.0 起支持**双模式**（`mode` 配置）：

| 模式 | 配置值 | iframe 源 | 端口暴露 | 需注入 |
|------|--------|-----------|----------|--------|
| 代理模式（默认） | `proxy` | KiraAI (5267) | 不暴露 | `<base>` + LS 隔离 + WS 拦截 |
| 直连模式 | `direct` | NapCat (6099) | 暴露到浏览器 | 无需（跨源天然隔离） |

### 架构差异

**代理模式**（原架构）：
```
浏览器 iframe → /page/plugin/... → 302 → /entry → 302 → /proxy/_v{ts}/webui/...
                                                          ↓
                                                    _proxy → httpx → 127.0.0.1:6099
```
- iframe 全程同源 5267
- KiraAI 中转所有 HTTP/WS/SSE 流量
- 注入 `<base>` / localStorage 隔离 / WS 拦截器

**直连模式**：
```
浏览器 iframe → /page/plugin/... → 302 → /entry → 302 → http://127.0.0.1:6099/webui/
                                                          ↓
                                                    浏览器直连 6099
```
- iframe 跨源（5267 → 6099），sandbox 仍生效
- NapCat 自行处理所有流量（SSE、WS、API）
- 无需 KiraAI 代理、无需 HTML 注入
- localStorage/ServiceWorker 在 6099 域下独立管理

### 配置切换

在 KiraAI WebUI 插件配置页将 `mode` 改为 `direct`，配置热更新立即生效。
entry 端点每次请求读取配置决定跳转目标，token 和模式的变更即时生效。

### 已知限制

1. **端口暴露**：浏览器需要能直接访问 NapCat 端口（默认 6099），放弃"端口不暴露"约束
2. **iframe sandbox**：KiraAI 的 iframe sandbox 属性 (`allow-scripts allow-same-origin allow-forms allow-popups`) 在直连模式仍生效，NapCat 的 `alert/confirm`（缺 `allow-modals`）和文件下载（缺 `allow-downloads`）可能被阻断。经实测，NapCat WebUI 核心功能（控制台、日志、设置、拓展插件）不受影响
3. **跨源通信**：父窗口（KiraAI）无法通过 JS 访问 iframe 内容 DOM，但 `postMessage` 仍可用

### 性能对比

直连模式省去了代理转发、路径重写、HTML 注入的全部开销，NapCat 资产直接由浏览器加载。
实测首次渲染速度明显快于代理模式（需 3 次 302 + 服务端拉取 + HTML 重写）。

## 关键技术决策

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
- HTML 注入模板（`<base>`、SW 清理、WS 拦截器）
- `HttpClientManager` 连接池管理

单元测试直接 import `proxy_utils`，不依赖 KiraAI 运行时。
