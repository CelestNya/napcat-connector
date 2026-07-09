# NapCat WebUI 集成设计文档

## 概述

在 KiraAI 的 NapCat Connector 插件中添加侧边栏导航项，点击后通过 iframe 内嵌加载 NapCat WebUI，并自动携带已配置的 token 实现免登录。

## 背景

用户通过 KiraAI 管理远端的 NapCatQQ 实例，需要快捷访问 NapCat 的 Web 管理界面。当前 NapCat WebUI 接受 URL 查询参数传递 token 实现自动登录。

## 用户场景

1. 用户打开 KiraAI WebUI
2. 侧边栏出现「NapCat 控制台」导航项
3. 点击后在页面主体区域的 iframe 中加载 NapCat WebUI
4. 自动携带 token 参数，无需手动输入登录凭据

## 设计方案

### 方案选择：A — PluginPage.from_url()

最简方案，利用 KiraAI 内置的 `PluginPage.from_url()` 机制。

### 详细设计

#### 1. 配置项（schema.json）

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `ws_url` | `string` | `"ws://127.0.0.1:8081"` | NapCat OneBot WebSocket 地址 |
| `http_url` | `string` | `"http://127.0.0.1:3000"` | NapCat OneBot HTTP API 地址 |
| `access_token` | `string` | `""` | OneBot API 访问令牌 |
| `bot_qq` | `string` | `""` | 机器人 QQ 号 |
| `webui_url` | `string` | `"http://127.0.0.1:6099"` | NapCat WebUI 访问地址 |
| `webui_token` | `string` | `""` | WebUI 登录 token |
| `reconnect_interval` | `int` | `5` | 断线重连间隔（秒） |
| `max_reconnect_retries` | `int` | `0` | 最大重连次数（0=无限） |
| `debug_logging` | `switch` | `false` | DEBUG 日志 |

#### 2. 页面注册（main.py）

```python
@register.page(
    "/napcat",
    menu=PageMenu(
        label={"zh": "NapCat 控制台", "en": "NapCat Console"},
        icon="Monitor",
        order=10,
    ),
    auth=True,
)
def napcat_page(self):
    url = self.webui_url.rstrip("/")
    if self.webui_token:
        url += f"?token={self.webui_token}"
    return PluginPage.from_url(url)
```

#### 3. 工作流程

```
用户点击「NapCat 控制台」
    ↓
Vue Router 导航到 /plugin-page/napcat_connector/napcat
    ↓
PluginPageView.vue 创建 <iframe src="/page/plugin/napcat_connector/napcat">
    ↓
KiraAI 后端处理 GET /page/plugin/napcat_connector/napcat
    ↓
调用 napcat_page() → 生成 URL: http://napcat-host:6099/?token=xxx
    ↓
返回 302 Redirect → Location: http://napcat-host:6099/?token=xxx
    ↓
iframe 跟随重定向 → 加载 NapCat WebUI → 自动登录
```

#### 4. 安全考量

- 页面受 JWT 认证保护（`auth=True`），只有登录 KiraAI 的用户才能访问
- Token 仅在 iframe src URL 中短暂存在，不会被存入浏览器历史
- 如果 token 泄露（HTTPS 降级等风险），可通过 NapCat 端更换 token

#### 5. 已知限制

- 若 NapCat WebUI 设置了 `X-Frame-Options: DENY` 或 `sameorigin`，iframe 将被浏览器拦截
- 拦截时显示空白的 fallback：用户可在新标签页手动打开 WebUI（后续可加降级提示）


## 文件结构

```
KiraAI-napcat-connector/
├── __init__.py              # 导出插件类
├── manifest.json            # 插件元数据
├── schema.json              # 配置项
├── main.py                  # 插件主类（~60 行）
├── napcat_connector/
│   └── __init__.py          # 子模块（预留）
└── tests/
    └── test_main.py         # 基本加载测试
```

## 测试策略

1. **单元测试**：验证 URL 构建逻辑（有/无 token、URL 尾部斜杠处理）
2. **集成测试**：确认插件可被 PluginManager 正常加载
3. **手动测试**：在真实 KiraAI 环境中查看导航是否出现、iframe 是否正常加载
