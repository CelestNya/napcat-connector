"""
NapCat Connector — KiraAI 插件
反向代理模式：所有 NapCat WebUI 流量走 KiraAI 中转
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import httpx
from fastapi import Request, Response
from core.plugin import BasePlugin, PluginContext, register, PageMenu, PluginPage, logger

PROXY_PREFIX = "/api/plugin/napcat_connector/proxy"
NAPCAT_BASE = "http://127.0.0.1:6099"

# 需要路径重写的路径前缀映射
REWRITE_RULES = [
    ("/webui/", f"{PROXY_PREFIX}/webui/"),
    ('"/api/', f'"{PROXY_PREFIX}/api/'),
]


class NapcatConnectorPlugin(BasePlugin):

    def __init__(self, ctx: PluginContext, cfg: dict):
        super().__init__(ctx, cfg)

    async def initialize(self):
        logger.info("NapCat Connector 已就绪（代理模式）")

    async def terminate(self):
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
        反向代理入口：iframe 加载此路由，由后端实时取回 NapCat 资源。
        """
        return PluginPage.from_url(f"{PROXY_PREFIX}/webui/")

    @register.api("GET", "/proxy/{path:path}", auth=False)
    async def proxy_get(self, path: str, request: Request):
        """反向代理 GET 请求"""
        return await self._proxy("GET", path, request)

    @register.api("POST", "/proxy/{path:path}", auth=False)
    async def proxy_post(self, path: str, request: Request):
        """反向代理 POST 请求"""
        return await self._proxy("POST", path, request)

    async def _proxy(self, method: str, path: str, request: Request) -> Response:
        """代理核心逻辑"""
        # 如果 path 为空，默认为 webui/
        if not path:
            path = "webui/"

        target_url = f"{NAPCAT_BASE}/{path.lstrip('/')}"

        # 获取请求体（POST 时）
        body = None
        if method == "POST":
            body = await request.body()

        # 从配置读取 token，注入到 URL
        token = self.plugin_cfg.get("webui_token", "")
        separator = "&" if "?" in target_url else "?"
        if token and "token=" not in target_url:
            target_url += f"{separator}token={token}"

        logger.info(f"[代理] {method} {target_url}")

        # 转发请求到 NapCat
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.request(
                    method=method,
                    url=target_url,
                    content=body,
                    headers={
                        "Accept": request.headers.get("accept", "*/*"),
                        "User-Agent": request.headers.get(
                            "user-agent",
                            "Mozilla/5.0 KiraAI-Plugin/1.0",
                        ),
                    },
                    follow_redirects=False,  # 自己处理跳转
                )
            except httpx.RequestError as e:
                logger.error(f"代理请求失败: {e}")
                return Response(
                    content=f"Proxy error: {e}",
                    status_code=502,
                )

        # 重写响应头中的 Location
        headers = dict(resp.headers)
        if "location" in headers:
            loc = headers["location"]
            for old, new in REWRITE_RULES:
                if loc.startswith(old.rstrip('"')):
                    loc = loc.replace(old.rstrip('"'), new.rstrip('"'))
                    break
            headers["location"] = loc

        # 剥离安全头，允许 iframe 嵌套
        headers.pop("x-frame-options", None)
        headers.pop("content-security-policy", None)

        # 重写响应体（仅 HTML/JS/CSS）
        body = resp.content
        content_type = resp.headers.get("content-type", "")
        if any(t in content_type for t in ["text/html", "text/javascript",
                                            "application/javascript",
                                            "text/css", "application/json"]):
            body_str = body.decode("utf-8", errors="replace")
            for old, new in REWRITE_RULES:
                body_str = body_str.replace(old, new)
            body = body_str.encode("utf-8")

        return Response(
            content=body,
            status_code=resp.status_code,
            headers=headers,
            media_type=resp.headers.get("content-type"),
        )
