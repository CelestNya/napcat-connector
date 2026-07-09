"""
NapCat Connector — KiraAI 插件
提供 NapCatQQ 管理界面快捷入口
"""

import sys
from pathlib import Path

# 确保插件包可被发现
sys.path.insert(0, str(Path(__file__).parent))

from fastapi.responses import RedirectResponse
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

    @register.api(
        "GET",
        "/redirect",
        auth=False,
        summary="重定向到 NapCat WebUI（含 token）",
    )
    async def get_redirect_url(self):
        """
        API 端点：返回 302 重定向到 NapCat WebUI（含 token）。
        每次请求从 self.plugin_cfg 实时读取配置。
        auth=False 因为此端点被 PluginPageView 的 iframe 调用，
        iframe 内无法发送 Authorization 头，且 cookie 的 SameSite
        策略可能在 iframe 上下文中被阻止。
        """
        url = self.plugin_cfg.get("webui_url", "").rstrip("/")
        if not url:
            logger.warning("NapCat WebUI URL 未配置")
            return RedirectResponse(
                url="/page/plugin/napcat_connector/napcat?error=noconfig",
                status_code=302,
            )
        token = self.plugin_cfg.get("webui_token", "")
        if token:
            url += f"?token={token}"
        logger.info(f"重定向到 NapCat WebUI: {url}")
        return RedirectResponse(url=url, status_code=302)

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
        返回一个轻量 HTML 页面，通过 window.location.href 跳转到
        /api/plugin/napcat_connector/redirect 端点获取实时 URL 并重定向。
        避免了 iframe 内 fetch 的 cookie 认证问题。
        """
        html = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<style>
body { margin:0; font-family: sans-serif; background:#f5f5f5; }
.msg { display:flex; flex-direction:column; align-items:center;
       justify-content:center; height:100vh; color:#666; }
.msg h3 { margin:0 0 8px; }
.msg.error { color:#e74c3c; }
.spinner { width:40px; height:40px; border:4px solid #ddd;
           border-top-color:#409eff; border-radius:50%;
           animation:spin 0.8s linear infinite; margin-bottom:16px; }
@keyframes spin { to { transform:rotate(360deg); } }
</style>
</head>
<body>
<div class="msg">
  <div class="spinner"></div>
  <span>正在跳转到 NapCat WebUI…</span>
</div>
<script>
(function() {
  // 从 URL 查询参数读取错误标识
  var params = new URLSearchParams(window.location.search);
  if (params.get('error') === 'noconfig') {
    document.body.innerHTML =
      '<div class="msg error"><h3>NapCat WebUI 未配置</h3>' +
      '<p>请在「设置 → 插件配置 → NapCat Connector」中填写 webui_url</p></div>';
    return;
  }
  // 跳转到 API 端点，获取实时 URL 并重定向
  window.location.href = '/api/plugin/napcat_connector/redirect';
})();
</script>
</body>
</html>"""
        return PluginPage.from_html(html)