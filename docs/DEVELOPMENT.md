# 开发指南

## 项目结构

```
napcat-connector/
├── __init__.py          # 插件入口，try/except ImportError
├── main.py              # 插件主逻辑（路由、代理、重写）
├── manifest.json        # 插件清单（名称、版本、描述）
├── schema.json          # 配置项 schema
├── tests/
│   ├── test_main.py     # 单元测试（路径重写、版本段、entry 构建）
│   └── diagnose_plugin.mjs  # Playwright 端到端诊断
└── docs/
    ├── README.md        # 总览
    ├── HOW_IT_WORKS.md  # 工作原理
    └── DEVELOPMENT.md   # 本文件
```

## 核心模块 (`main.py`)

| 组件 | 行数 | 说明 |
|------|------|------|
| 常量配置 | ~30 | `PROXY_PREFIX`, `PLUGIN_API_PREFIX`, `NAPCAT_DEFAULT_BASE` |
| 缓存破坏 | ~5 | `_CACHE_BUSTER = str(int(time.time() * 1000))` |
| 正则重写 | ~15 | `REWRITE_API`, `REWRITE_WEBUI`, `REWRITE_FILES`, `REWRITE_PLUGIN` |
| `napcat_page` | ~10 | `@register.page` 注册侧栏导航 |
| `proxy_entry` | ~15 | `@register.api("GET", "/entry")` 动态重定向 |
| `proxy_*` | ~20 | `GET`/`POST`/`HEAD` 代理入口 |
| `ws_terminal_proxy` | ~35 | `@register.ws("/terminal")` WebSocket 代理 |
| `_proxy` | ~120 | 代理核心逻辑（转发、重写、流式 SSE） |

### `_proxy` 方法内部流程

```
_proxy(method, path, request)
  │
  ├─ 1. 剥离版本段 _v{ts}/
  ├─ 2. 拦截 sw.js（返回 404）
  ├─ 3. 构造 target_url（配置热更新）
  ├─ 4. 追加 query string
  ├─ 5. 读取 POST body
  ├─ 6. 转发请求头（剥离条件缓存/不兼容头）
  │
  ├─ 7. httpx 请求 NapCat
  │
  ├─ 8. 判断 SSE (text/event-stream)
  │     └─ 流式返回（StreamingResponse）
  │
  ├─ 9. 非流式处理：
  │     ├─ 重写 Location 头
  │     ├─ 剥离不兼容/缓存头
  │     ├─ 设置 Cache-Control: no-store
  │     ├─ 路径重写（正则 4 规则）
  │     ├─ 修复 WebSocket 路径
  │     ├─ 禁用 SW 注册
  │     └─ HTML 注入（<base>, localStorage 隔离, SW 清理）
  │
  └─ 10. 返回 Response
```

## 测试

### 单元测试

```bash
cd /d/Projects/KiraAI-dev/KiraAI-napcat-connector
python3 -m pytest tests/test_main.py -v
```

覆盖：
- 所有重写规则的匹配/不匹配
- 版本段剥离
- entry 重定向 URL 构建
- 防二次重写
- 模板字面量匹配

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

1. 在常量区添加正则：`REWRITE_xxx = re.compile(...)`
2. 在 `_proxy` 方法中的重写块添加：`body_str = REWRITE_xxx.sub(REWRITE_xxx_REPL, body_str)`
3. 在测试文件中添加对应测试

### 新增 HTTP 代理方法

1. 添加 `@register.api("METHOD", "/proxy/{path:path}", auth=False)`
2. 方法体调用 `return await self._proxy("METHOD", path, request)`

### 新增 WebSocket 代理

1. 确认路径与 JS 改写匹配
2. 添加 `@register.ws("/xxx", auth=False)`
3. 在处理器中连接 NapCat 对应端点，双向转发
4. 在 JS 重写中添加 pathname 替换

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
print('napcat_' in html)               # localStorage 隔离
print('getRegistrations' in html)      # SW 清理
```

### 查看注册路由

```python
import http.client, json
c = http.client.HTTPConnection("127.0.0.1", 5267)
c.request("GET", "/api/plugins")
print(c.getresponse().read().decode())
```
