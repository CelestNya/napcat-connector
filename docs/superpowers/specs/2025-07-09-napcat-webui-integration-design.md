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

### 方案选择：A — PluginPage.from_url()（最初方案，已废弃）

最初采用 `PluginPage.from_url()`，但 URL 在插件初始化时固定，用户改配置后不生效。

### 最终方案：PluginPage.from_html() + API 端点

改用 `from_html()` 返回一个内含 JavaScript 的轻量 HTML 页面，通过调用插件 API 端点实时获取当前配置的 WebUI URL（含 token），再在 iframe 中加载 NapCat WebUI。

### 详细设计

#### 1. 配置项（schema.json）

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `webui_url` | `string` | `"http://127.0.0.1:6099"` | NapCat WebUI 访问地址 |
| `webui_token` | `string` | `""` | WebUI 登录 token |

#### 2. API 端点

注册 `GET /api/plugin/napcat_connector/redirect`：

```python
@register.api("GET", "/redirect", auth=True)
def get_redirect_url(self):
    url = self.plugin_cfg.get("webui_url", "").rstrip("/")
    if not url:
        return {"url": "", "error": "webui_url 未配置"}
    token = self.plugin_cfg.get("webui_token", "")
    if token:
        url += f"?token={token}"
    return {"url": url}
```

#### 3. 页面注册（main.py）

```python
@register.page("/napcat", ...)
def napcat_page(self):
    html = "<!DOCTYPE html>..."  # JS 调用 API → iframe
    return PluginPage.from_html(html)
```

#### 4. 工作流程

```
用户点击「NapCat 控制台」
    ↓
Vue Router → PluginPageView.vue → <iframe src="/page/plugin/napcat_connector/napcat">
    ↓
KiraAI 后端返回 HTML 页面（静态）
    ↓
HTML 中的 JS fetch('/api/plugin/napcat_connector/redirect')
    ↓
API 端点从 self.plugin_cfg 实时读取 webui_url + webui_token
    ↓
返回 {"url": "http://napcat:6099/?token=xxx"}
    ↓
JS 创建 <iframe src="http://napcat:6099/?token=xxx">
    ↓
NapCat WebUI 加载 → 自动登录（token 在 URL 中）
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
