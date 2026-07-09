"""
NapCat Connector — KiraAI 插件
提供 NapCatQQ 管理界面快捷入口
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fastapi.responses import RedirectResponse
from core.plugin import BasePlugin, PluginContext, register, PageMenu, PluginPage, logger


class NapcatConnectorPlugin(BasePlugin):

    def __init__(self, ctx: PluginContext, cfg: dict):
        super().__init__(ctx, cfg)

    async def initialize(self):
        url = self.plugin_cfg.get("webui_url", "")
        token = self.plugin_cfg.get("webui_token", "")
        token_status = "是" if token else "否 — 无 token 模式"
        logger.info("NapCat Connector 已就绪")
        logger.info(f"  WebUI 地址: {url}")
        logger.info(f"  Token 已配置: {token_status}")

    async def terminate(self):
        pass

    @register.api(
        "GET",
        "/redirect",
        auth=False,
        summary="重定向到 NapCat WebUI（实时读取配置）",
    )
    async def get_redirect_url(self):
        """
        读取当前配置，302 重定向到 NapCat WebUI（含 token）。
        auth=False：此端点只返回重定向，不暴露敏感数据。
        """
        base = self.plugin_cfg.get("webui_url", "").rstrip("/")
        if not base:
            return RedirectResponse(
                url="/page/plugin/napcat_connector/napcat?error=noconfig",
                status_code=302,
            )
        token = self.plugin_cfg.get("webui_token", "")
        if not base.endswith("/webui"):
            base += "/webui"
        if token:
            base += f"?token={token}"
        return RedirectResponse(url=base, status_code=302)

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
        跳转链：from_url → 自带 API 端点 → 302 → NapCat WebUI

        from_url 的 URL 指向自身 API 端点（路径固定），
        API 端点每次读取实时配置后重定向到 NapCat。
        NapCat 的 301/302 由浏览器在 iframe 加载过程中自动跟随，
        无需 JavaScript，不受 sandbox 限制。
        """
        return PluginPage.from_url("/api/plugin/napcat_connector/redirect")
