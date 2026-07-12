# NapCat Connector

KiraAI 插件：反向代理 / 直连双模式接入 NapCat WebUI。

## 安装

此插件由 KiraAI 内置管理，无需手动操作。在 KiraAI 插件市场搜索 `napcat-connector` 即可安装。

## 配置

| 参数 | 说明 |
|------|------|
| `mode` | 连接模式：`proxy`（后端转发，端口不暴露） / `direct`（前端直连 NapCat 端口，更快但暴露端口） |
| `webui_url` | NapCat 地址，默认 `http://127.0.0.1:6099` |
| `webui_token` | 登录 Token，填写后自动登录 NapCat WebUI，留空则不自动登录 |

在 KiraAI WebUI → 插件管理 → NapCat Connector 配置面板中修改，配置热更新即时生效。

## 连接模式对比

| 方面 | 代理模式（proxy） | 直连模式（direct） |
|------|-------------------|-------------------|
| iframe 源 | KiraAI (5267) | NapCat (6099) |
| 端口暴露 | NapCat 端口不暴露 | 暴露到浏览器 |
| 流量路径 | 全部经 KiraAI 中转 | 浏览器直连 NapCat |
| 渲染速度 | 稍慢（需代理转发 + HTML 重写） | 更快（无中转开销） |
| iframe sandbox | 全程同源，无限制 | 跨源，受 sandbox 限制 |

> **提示**：直连模式需浏览器能直接访问 NapCat 端口（默认 6099）。如遇 iframe 加载异常，请切回代理模式。

## 开发

```bash
pip install -e .
pytest tests/
```

Playwright 集成测试：

```bash
npx playwright install chromium
node tests/verify_extension_fix.mjs   # 代理模式回归
node tests/verify_direct_mode.mjs     # 直连模式验证（需先配置 mode=direct）
```

## 许可

MIT
