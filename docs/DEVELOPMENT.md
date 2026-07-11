# 开发指南

## 项目结构

```
napcat-connector/
├── __init__.py          # 插件入口，try/except ImportError
├── main.py              # 插件主逻辑（路由、代理、WS 转发）
├── proxy_utils.py       # 纯函数模块（常量、正则规则、JS 注入模板、连接池管理）
├── manifest.json        # 插件清单（名称、版本、描述）
├── schema.json          # 配置项 schema
├── tests/
│   ├── conftest.py      # pytest 配置（sys.path）
│   ├── test_proxy_utils.py  # 单元测试（64 用例）
│   └── diagnose_plugin.mjs  # Playwright 端到端诊断
└── docs/
    ├── README.md        # 总览
    ├── HOW_IT_WORKS.md  # 工作原理
    └── DEVELOPMENT.md   # 本文件
```

## 核心模块

### `proxy_utils.py`（纯函数，可独立测试）

| 组件 | 说明 |
|------|------|
| 常量 | `PROXY_PREFIX`, `PLUGIN_API_PREFIX`, `NAPCAT_DEFAULT_BASE`, `WS_PROXY_PREFIX`, `HTTP_METHODS` |
| 正则规则 | `_REWRITE_API`, `_REWRITE_WEBUI`, `_REWRITE_FILES`, `_REWRITE_PLUGIN` |
| `rewrite_paths()` | 4 条路径重写 |
| `strip_version()` | `_vxxxx/` 版本段剥离 |
| `build_entry_url()` | entry 重定向 URL |
| `is_text_content()` / `is_sse_response()` / `should_read_body()` | Content-Type 判断 |
| `build_ws_target_url()` | WebSocket 目标 URL 构建 |
| `build_ws_interceptor_js()` / `build_inject_html()` | HTML 注入模板 |
| `HttpClientManager` | 共享 httpx 连接池管理 |

### `main.py`（运行时逻辑）

| 组件 | 行数 | 说明 |
|------|------|------|
| 缓存破坏 | ~5 | `_CACHE_BUSTER = str(int(time.time() * 1000))` |
| `__init__` / `initialize` / `terminate` | ~10 | `HttpClientManager` 生命周期 |
| `napcat_page` | ~10 | `@register.page` 注册侧栏导航 |
| `proxy_entry` | ~8 | `@register.api("GET", "/entry")` 动态重定向 |
| `_proxy_handler` | ~5 | 循环注册 6 种 HTTP 方法 |
| `ws_proxy` | ~40 | `@register.ws("/{ws_path:path}")` 通配 WS 代理 |
| `_proxy` | ~120 | 代理核心逻辑（转发、重写、SSE 流式） |

### `_proxy` 方法内部流程

```
_proxy(method, path, request)
  │
  ├─ 1. 剥离版本段 _v{ts}/
  ├─ 2. 拦截 sw.js（返回 404）
  ├─ 3. 构造 target_url（配置热更新）
  ├─ 4. 追加 query string
  ├─ 5. 读取 POST/PUT/PATCH body
  ├─ 6. 转发请求头（剥离条件缓存/不兼容头）
  │
  ├─ 7. 共享 httpx client.send(stream=True)
  │
  ├─ 8. 判断 SSE (text/event-stream)
  │     └─ 流式返回（aiter_bytes → StreamingResponse）
  │
  ├─ 9. 非流式处理：
  │     ├─ HEAD 短路（不读 body）
  │     ├─ 重写 Location 头
  │     ├─ 剥离不兼容/缓存头
  │     ├─ 设置 Cache-Control: no-store
  │     ├─ 路径重写（rewrite_paths）
  │     ├─ 禁用 SW 注册
  │     └─ HTML 注入（<base>, SW 清理, WS 拦截器）
  │
  └─ 10. 返回 Response
```

## 测试

### 单元测试（不依赖 KiraAI 运行时）

```bash
cd /d/Projects/KiraAI-dev/KiraAI-napcat-connector
.venv/Scripts/python.exe -m pytest tests/ -v
```

覆盖：
- 全部 4 条路径重写规则的匹配/不匹配（16 用例）
- 版本段剥离（3 用例）
- entry 重定向 URL 构建（3 用例）
- Content-Type 判断函数（11 用例）
- WebSocket 目标 URL 构建（7 用例）
- WS 拦截器 JS 生成（5 用例）
- HTML 注入完整性（5 用例）
- HTTP_METHODS 常量（7 用例）
- HttpClientManager 连接池生命周期（5 用例）

总计 **64 个测试**。

### Playwright 端到端测试

```bash
# 完整诊断（需 KiraAI + NapCat 运行）
cd /d/tmp && node diagnose_final.mjs

# 或从项目目录复制到 playwright 环境：
cp tests/diagnose_plugin.mjs /d/tmp/
cd /d/tmp && node diagnose_plugin.mjs
```

## 添加新功能

### 新增重写规则

1. 在 `proxy_utils.py` 添加正则：`_REWRITE_xxx = re.compile(...)`
2. 在 `rewrite_paths()` 中添加 sub 调用
3. 在 `tests/test_proxy_utils.py` 中 `TestRewritePaths` 添加对应测试

### 新增 HTTP 代理方法

1. 在 `proxy_utils.py` 的 `HTTP_METHODS` 元组中添加方法名
2. 方法自动注册（循环），无需修改其他代码

### 新增 WebSocket 代理

通配 WS 端点 `@register.ws("/{ws_path:path}")` 已覆盖所有 WS 路径。
- 终端 WS：自动捕获 `api/ws/terminal`
- 插件 WS：自动捕获 `api/Debug/ws`、`api/xxx/ws` 等
- query params 全量透传

无需新增端点，只需确认 WS 构造器拦截器已正确注入。

### 修改 HTML 注入内容

编辑 `proxy_utils.py` 中的 `build_inject_html()` 或 `build_ws_interceptor_js()`。

## 调试技巧

### 检查代理返回的 JS

```python
import urllib.request
PROXY = "http://127.0.0.1:5267/api/plugin/napcat_connector/proxy/_v{ver}"
req = urllib.request.Request(f"{PROXY}/webui/assets/index-BfMm4PRv.js")
js = urllib.request.urlopen(req).read().decode("utf-8")
```

### 检查 HTML 注入

```python
req = urllib.request.Request(f"{PROXY}/webui/")
html = urllib.request.urlopen(req).read().decode("utf-8")
print('<base href=' in html)           # base 标签
print('getRegistrations' in html)      # SW 清理
print('getRegistrations' in html)      # SW 清理
print('window.WebSocket' in html)      # WS 拦截器
```

### 查看注册路由

```python
import http.client, json
c = http.client.HTTPConnection("127.0.0.1", 5267)
c.request("GET", "/api/plugins")
print(c.getresponse().read().decode())
```
