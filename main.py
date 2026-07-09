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
