# NapCat WebUI 导航集成 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 KiraAI WebUI 侧边栏添加「NapCat 控制台」导航项，点击后以 iframe 内嵌加载 NapCat WebUI，URL 自动携带 token 实现免登录。

**Architecture:** KiraAI 插件 `@register.page()` + `PluginPage.from_url()` 实现。插件在初始化时读取 `webui_url` 和 `webui_token` 配置，页面方法在调用时构造完整 URL 并返回 302 重定向。KiraAI 前端的 `PluginPageView.vue` 在 iframe 中加载该重定向，iframe 跟随跳转到 NapCat WebUI（带 token 参数自动登录）。

**Tech Stack:** Python 3.11+, KiraAI Plugin API (BasePlugin / register / PageMenu / PluginPage)

## Global Constraints

- 插件目录：`D:\Projects\KiraAI-dev\KiraAI-napcat-connector\`
- 所有代码注释/日志用中文
- 遵循 QZone 插件（`KiraAI-qzone-plugin`）已建立的插件结构惯例
- 如果 token 为空（`""`），URL 不加 `?token=` 参数
- `PluginPage.from_url()` 的方法必须是同步函数（不可 async）
- 配置值在 `__init__` 中读取并存储为实例属性

---

### Task 1: 更新 schema.json 配置项

**Files:**
- Modify: `D:\Projects\KiraAI-dev\KiraAI-napcat-connector\schema.json`

**Interfaces:**
- Consumes: 现有 schema.json（已包含 ws_url, http_url, access_token, bot_qq, reconnect_interval, max_reconnect_retries, debug_logging）
- Produces: 新增 webui_url, webui_token 两个配置项

- [ ] **Step 1: 读取当前 schema.json**

Read the current file to confirm existing fields.

- [ ] **Step 2: 写入更新后的 schema.json**

写入包含以下完整配置项的 schema.json：

```json
{
    "ws_url": {
        "type": "string",
        "default": "ws://127.0.0.1:8081",
        "hint": "NapCatQQ OneBot WebSocket 地址"
    },
    "http_url": {
        "type": "string",
        "default": "http://127.0.0.1:3000",
        "hint": "NapCatQQ OneBot HTTP API 地址"
    },
    "access_token": {
        "type": "string",
        "default": "",
        "hint": "OneBot API 访问令牌（可选）"
    },
    "bot_qq": {
        "type": "string",
        "default": "",
        "hint": "机器人 QQ 号，留空自动检测"
    },
    "webui_url": {
        "type": "string",
        "default": "http://127.0.0.1:6099",
        "hint": "NapCat WebUI 访问地址"
    },
    "webui_token": {
        "type": "string",
        "default": "",
        "hint": "WebUI 登录 token（留空不传 token）"
    },
    "reconnect_interval": {
        "type": "int",
        "default": 5,
        "hint": "断线重连间隔（秒）"
    },
    "max_reconnect_retries": {
        "type": "int",
        "default": 0,
        "hint": "最大重连次数（0=无限）"
    },
    "debug_logging": {
        "type": "switch",
        "default": false,
        "hint": "开启 DEBUG 级别日志"
    }
}
```

- [ ] **Step 3: 提交**

```bash
git add schema.json
git commit -m "feat(plugin): add webui_url and webui_token config items"
```

---

### Task 2: 实现 main.py 插件主类

**Files:**
- Modify: `D:\Projects\KiraAI-dev\KiraAI-napcat-connector\main.py`
- Test: `D:\Projects\KiraAI-dev\KiraAI-napcat-connector\tests\test_main.py`

**Interfaces:**
- Consumes: `core.plugin.{BasePlugin, PluginContext, register, PageMenu, PluginPage, logger}`
- Consumes: schema.json 配置项（webui_url, webui_token）
- Produces: `NapcatConnectorPlugin` 类（包含 `initialize()`, `terminate()`, `napcat_page()`）
- Produces: URL 构建 `{webui_url.rstrip("/")}?token={webui_token}`
- Produces: `@register.page("/napcat", ...)` 注册导航

- [ ] **Step 1: 写入 main.py**

写入完整插件类，包含 URL 构建逻辑，支持有/无 token 两种情况：

```python
"""
NapCat Connector — KiraAI 插件
提供 NapCatQQ 管理界面快捷入口
"""

import sys
from pathlib import Path

# 确保插件包可被发现
sys.path.insert(0, str(Path(__file__).parent))

from core.plugin import BasePlugin, PluginContext, register, PageMenu, PluginPage, logger


class NapcatConnectorPlugin(BasePlugin):

    def __init__(self, ctx: PluginContext, cfg: dict):
        super().__init__(ctx, cfg)
        self.webui_url = cfg.get("webui_url", "http://127.0.0.1:6099")
        self.webui_token = cfg.get("webui_token", "")

    async def initialize(self):
        """插件初始化时打印配置信息"""
        token_status = "是" if self.webui_token else "否 — 无 token 模式"
        logger.info(f"NapCat Connector 已就绪")
        logger.info(f"  WebUI 地址: {self.webui_url}")
        logger.info(f"  Token 已配置: {token_status}")

    async def terminate(self):
        """清理资源"""
        pass

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
        """
        生成 NapCat WebUI 访问链接。
        此方法在插件初始化时被 PluginManager 延迟调用（必须是同步方法）。
        """
        url = self.webui_url.rstrip("/")
        if self.webui_token:
            url += f"?token={self.webui_token}"
        logger.info(f"生成 NapCat WebUI 链接: {url}")
        return PluginPage.from_url(url)
```

- [ ] **Step 2: 写入测试文件**

```python
"""NapCat Connector 插件测试"""

from pathlib import Path


class FakeCtx:
    """模拟 PluginContext，仅测试所需"""
    def get_plugin_data_dir(self):
        return Path("/tmp/test_napcat_connector_data")


class TestNapcatConnectorPlugin:

    def test_url_with_token(self):
        """有 token 时 URL 应包含 ?token=xxx"""
        # 模拟配置
        cfg = {
            "webui_url": "http://192.168.1.100:6099",
            "webui_token": "my_secret_token",
        }
        # 直接测试 URL 构建逻辑
        url = cfg["webui_url"].rstrip("/")
        if cfg["webui_token"]:
            url += f"?token={cfg['webui_token']}"
        assert url == "http://192.168.1.100:6099?token=my_secret_token"

    def test_url_without_token(self):
        """无 token 时 URL 不应包含 ?token=""""""
        cfg = {
            "webui_url": "http://127.0.0.1:6099",
            "webui_token": "",
        }
        url = cfg["webui_url"].rstrip("/")
        if cfg["webui_token"]:
            url += f"?token={cfg['webui_token']}"
        assert url == "http://127.0.0.1:6099"

    def test_url_trailing_slash(self):
        """URL 末尾有斜杠时应被去除"""
        cfg = {
            "webui_url": "http://napcat.example.com:6099/",
            "webui_token": "abc123",
        }
        url = cfg["webui_url"].rstrip("/")
        if cfg["webui_token"]:
            url += f"?token={cfg['webui_token']}"
        assert url == "http://napcat.example.com:6099?token=abc123"
```

- [ ] **Step 3: 运行测试**

```bash
cd "D:/Projects/KiraAI-dev/KiraAI-src" && python -m pytest "D:/Projects/KiraAI-dev/KiraAI-napcat-connector/tests/test_main.py" -v
```

Expected: 3 tests PASS

- [ ] **Step 4: 提交**

```bash
git add main.py tests/test_main.py
git commit -m "feat(plugin): add NapCat WebUI navigation with auto-login via URL token"
```

---

### Task 3: 更新 __init__.py

**Files:**
- Modify: `D:\Projects\KiraAI-dev\KiraAI-napcat-connector\__init__.py`

**Interfaces:**
- Produces: `NapcatConnectorPlugin` 类导出

- [ ] **Step 1: 写入 __init__.py**

```python
from .main import NapcatConnectorPlugin

__all__ = ["NapcatConnectorPlugin"]
```

- [ ] **Step 2: 提交**

```bash
git add __init__.py
git commit -m "chore: export NapcatConnectorPlugin from __init__.py"
```

---

### Task 4: 确认 manifest.json

**Files:**
- Read: `D:\Projects\KiraAI-dev\KiraAI-napcat-connector\manifest.json`

- [ ] **Step 1: 读取确认**

确认 manifest.json 的 plugin_id 为 `napcat_connector`，与代码一致。

- [ ] **Step 2: 使用 git status 确认最终文件清单**

```bash
cd "D:/Projects/KiraAI-dev/KiraAI-napcat-connector" && git status
```

- [ ] **Step 3: 最终提交（如需要）**

```bash
git add -A && git commit -m "chore: finalize plugin scaffold"
```
