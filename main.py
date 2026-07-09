"""
NapCat Connector — KiraAI 插件
反向代理模式：所有 NapCat WebUI 流量走 KiraAI 中转
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import re
import httpx
from fastapi import Request, Response
from core.plugin import BasePlugin, PluginContext, register, PageMenu, PluginPage, logger

PROXY_PREFIX = "/api/plugin/napcat_connector/proxy"
NAPCAT_BASE = "http://127.0.0.1:6099"

# 路径重写规则：分 content-type 应用
REWRITE_WEBUI = re.compile(r'(["\'(=\s])/webui/')
REWRITE_WEBUI_REPL = rf'\1{PROXY_PREFIX}/webui/'
REWRITE_API = re.compile(r'(["\'(=\s])/api/')
REWRITE_API_REPL = rf'\1{PROXY_PREFIX}/api/'


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
        if not path:
            path = "webui/"

        target_url = f"{NAPCAT_BASE}/{path.lstrip('/')}"

        # POST 时读取请求体，并转发 content-type
        body = None
        content_type_header = request.headers.get("content-type")
        if method == "POST":
            body = await request.body()

        # 只在首页加载时传 token
        token = self.plugin_cfg.get("webui_token", "")
        if token and "token=" not in target_url and ("webui" in path or path == ""):
            separator = "&" if "?" in target_url else "?"
            target_url += f"{separator}token={token}"

        logger.info(f"[代理] {method} {target_url}")

        # 转发请求头：透传客户端的头（Authorization/Cookie 等），排除 hop-by-hop 头
        skip_headers = {"host", "content-length", "transfer-encoding",
                        "connection", "x-frame-options", "content-security-policy"}
        forward_headers = {}
        for key, val in request.headers.items():
            if key.lower() not in skip_headers:
                forward_headers[key] = val

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.request(
                    method=method,
                    url=target_url,
                    content=body,
                    headers=forward_headers,
                    follow_redirects=False,
                )
            except httpx.RequestError as e:
                logger.error(f"代理请求失败: {e}")
                return Response(content=f"Proxy error: {e}", status_code=502)

        # 重写 Location 头
        headers = dict(resp.headers)
        if "location" in headers:
            loc = headers["location"]
            if loc.startswith("/webui"):
                loc = PROXY_PREFIX + loc
            elif loc.startswith("/api/"):
                loc = PROXY_PREFIX + loc
            headers["location"] = loc

        # 剥离不兼容的响应头
        headers.pop("x-frame-options", None)
        headers.pop("content-security-policy", None)
        headers.pop("content-encoding", None)
        headers.pop("transfer-encoding", None)
        headers.pop("content-length", None)

        body = resp.content
        content_type = resp.headers.get("content-type", "")

        # 只对文本类内容做路径重写，二进制内容（图片/字体/音视频）透传
        needs_rewrite = any(
            t in content_type
            for t in ["text/html", "text/javascript", "application/javascript",
                      "text/css", "application/json"]
        )
        if needs_rewrite:
            body_str = body.decode("utf-8", errors="replace")
            if "text/html" in content_type:
                body_str = REWRITE_WEBUI.sub(REWRITE_WEBUI_REPL, body_str)
                # 注入 localStorage namespace 脚本，避免与 KiraAI 的同源冲突
                ns_script = """<script>
(function(){var k="napcat_",P=Storage.prototype,G=P.getItem,S=P.setItem,R=P.removeItem;
P.getItem=function(n){return G.call(this,k+n)};P.setItem=function(n,v){S.call(this,k+n,v)};
P.removeItem=function(n){R.call(this,k+n)}})();
</script>"""
                body_str = body_str.replace("<head>", "<head>" + ns_script)
            elif any(t in content_type for t in ["javascript", "text/css"]):
                body_str = REWRITE_API.sub(REWRITE_API_REPL, body_str)
                body_str = REWRITE_WEBUI.sub(REWRITE_WEBUI_REPL, body_str)
            elif "application/json" in content_type:
                body_str = REWRITE_WEBUI.sub(REWRITE_WEBUI_REPL, body_str)
                body_str = REWRITE_API.sub(REWRITE_API_REPL, body_str)
            body = body_str.encode("utf-8")

        return Response(
            content=body,
            status_code=resp.status_code,
            headers=headers,
            media_type=content_type or None,
        )
