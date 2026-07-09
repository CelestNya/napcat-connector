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

    @register.api(
        "GET",
        "/redirect",
        auth=False,
        summary="获取 NapCat WebUI 跳转地址",
    )
    async def get_redirect_url(self):
        """
        API 端点：返回 NapCat WebUI 的完整 URL（含 token）。
        NapCat 的 redirect 链：
            /?token=xxx → 301 → /webui（token 丢失）
            /webui?token=xxx → 301 → /webui/?token=xxx（token 保留）
        所以必须访问 /webui?token=xxx 而非 /?token=xxx
        才能让 token 存活到 SPA 加载后自动登录。
        """
        base = self.plugin_cfg.get("webui_url", "").rstrip("/")
        if not base:
            return {"url": "", "error": "webui_url 未配置"}
        token = self.plugin_cfg.get("webui_token", "")
        # 确保 URL 路径包含 /webui，使 token 通过 NapCat 的 redirect 链
        if not base.endswith("/webui"):
            base += "/webui"
        if token:
            base += f"?token={token}"
        return {"url": base}

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
        返回一个轻量 HTML 页面，通过 fetch 获取实时 WebUI URL，
        然后用 iframe.src 加载 NapCat WebUI。
        使用 fetch 而非 window.location 跳转，因为 iframe sandbox
        不允许 top-navigation（缺少 allow-top-navigation 属性）。
        """
        html = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<style>
* { margin:0; padding:0; box-sizing:border-box; }
html, body { width:100%; height:100%; overflow:hidden;
             font-family: sans-serif; background:#f5f5f5; }
.msg { display:flex; flex-direction:column; align-items:center;
       justify-content:center; height:100%; color:#666; }
.msg h3 { margin:0 0 8px; }
.msg.error { color:#e74c3c; }
.spinner { width:40px; height:40px; border:4px solid #ddd;
           border-top-color:#409eff; border-radius:50%;
           animation:spin 0.8s linear infinite; margin-bottom:16px; }
@keyframes spin { to { transform:rotate(360deg); } }
#frame { width:100%; height:100%; border:none; display:none; }
</style>
</head>
<body>
<div id="app" class="msg">
  <div class="spinner"></div>
  <span id="status">正在连接 NapCat WebUI…</span>
</div>
<iframe id="frame" allowfullscreen></iframe>
<script>
(function() {
  var app = document.getElementById('app');
  var statusEl = document.getElementById('status');
  var frame = document.getElementById('frame');

  fetch('/api/plugin/napcat_connector/redirect', { credentials: 'same-origin' })
    .then(function(resp) {
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      return resp.json();
    })
    .then(function(d) {
      if (d.error) {
        app.className = 'msg error';
        app.innerHTML = '<h3>NapCat WebUI 未配置</h3>' +
          '<p>' + d.error + '</p>' +
          '<p>请在「设置 → 插件配置 → NapCat Connector」中填写 webui_url</p>';
        return;
      }
      if (!d.url) {
        app.className = 'msg error';
        app.innerHTML = '<h3>配置错误</h3><p>WebUI URL 为空</p>';
        return;
      }
      // 隐藏加载提示，显示 iframe
      app.style.display = 'none';
      frame.style.display = 'block';
      frame.src = d.url;
    })
    .catch(function(err) {
      app.className = 'msg error';
      app.innerHTML = '<h3>加载失败</h3>' +
        '<p>无法获取 WebUI 配置: ' + err.message + '</p>' +
        '<p>请检查 KiraAI 后端日志</p>';
    });
})();
</script>
</body>
</html>"""
        return PluginPage.from_html(html)