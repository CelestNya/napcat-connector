"""
NapCat Connector — KiraAI 插件
提供 NapCatQQ 管理界面快捷入口
"""

import sys
from pathlib import Path

# 确保插件包可被发现
sys.path.insert(0, str(Path(__file__).parent))

from core.plugin import BasePlugin, PluginContext, register, PageMenu, PluginPage, logger


PLUGIN_ID = "napcat_connector"


class NapcatConnectorPlugin(BasePlugin):

    def __init__(self, ctx: PluginContext, cfg: dict):
        super().__init__(ctx, cfg)

    async def initialize(self):
        """插件初始化时打印配置信息"""
        url = self.plugin_cfg.get("webui_url", "")
        token = self.plugin_cfg.get("webui_token", "")
        token_status = "是" if token else "否 — 无 token 模式"
        logger.info("NapCat Connector 已就绪")
        logger.info(f"  WebUI 地址: {url}")
        logger.info(f"  Token 已配置: {token_status}")

    async def terminate(self):
        """清理资源"""
        pass

    @register.api("GET", "/redirect", auth=True, summary="获取 NapCat WebUI 跳转地址")
    async def get_redirect_url(self):
        """
        API 端点：返回 NapCat WebUI 的完整 URL（含 token）。
        每次请求都从 self.plugin_cfg 实时读取，配置更改后立即可用。
        """
        url = self.plugin_cfg.get("webui_url", "").rstrip("/")
        if not url:
            return {"url": "", "error": "webui_url 未配置"}
        token = self.plugin_cfg.get("webui_token", "")
        if token:
            url += f"?token={token}"
        return {"url": url}

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
        返回一个轻量 HTML 页面：
        1. 通过 API 获取当前配置的 WebUI 地址 + token
        2. 在 iframe 中加载 NapCat WebUI（或显示错误）
        """
        html = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<style>
body { margin:0; font-family: sans-serif; background:#fff; }
.loading { display:flex; align-items:center; justify-content:center;
           height:100vh; color:#666; font-size:16px; }
.error { display:flex; flex-direction:column; align-items:center;
         justify-content:center; height:100vh; color:#e74c3c; }
.error h3 { margin-bottom:8px; }
iframe { width:100%; height:100vh; border:none; }
</style>
</head>
<body>
<div id="app" class="loading">正在连接 NapCat WebUI…</div>
<script>
fetch('/api/plugin/napcat_connector/redirect')
  .then(function(r) { return r.json(); })
  .then(function(d) {
    if (d.error) {
      document.getElementById('app').className = 'error';
      document.getElementById('app').innerHTML =
        '<h3>NapCat WebUI 未配置</h3>' +
        '<p>' + d.error + '</p>' +
        '<p>请在 「设置 → 插件配置 → NapCat Connector」中填写 webui_url</p>';
    } else if (d.url) {
      document.getElementById('app').innerHTML =
        '<iframe src="' + d.url + '" allowfullscreen></iframe>';
    }
  })
  .catch(function() {
    document.getElementById('app').className = 'error';
    document.getElementById('app').innerHTML =
      '<h3>加载失败</h3><p>无法获取 WebUI 配置，请检查 KiraAI 后端</p>';
  });
</script>
</body>
</html>"""
        return PluginPage.from_html(html)
