"""
NapCat Connector — KiraAI 插件
反向代理模式：所有 NapCat WebUI 流量走 KiraAI 中转
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import re
import time
import asyncio
import websockets
import httpx
from fastapi import Request, Response, WebSocket
from fastapi.responses import RedirectResponse, StreamingResponse
from core.plugin import BasePlugin, PluginContext, register, PageMenu, PluginPage, logger

PROXY_PREFIX = "/api/plugin/napcat_connector/proxy"
PLUGIN_API_PREFIX = "/api/plugin/napcat_connector"
NAPCAT_DEFAULT_BASE = "http://127.0.0.1:6099"

# 缓存破坏版本号：每次插件加载时生成新值，注入到代理 URL 中，
# 使浏览器无法复用之前缓存的旧 JS（no-store 只阻止未来缓存，不清除已有缓存）
_CACHE_BUSTER = str(int(time.time() * 1000))

# 路径重写规则：将 NapCat 的绝对路径重写为代理路径
# 关键：必须同时匹配 "/api"（无尾斜杠，如 axios baseURL）和 "/api/..."（带斜杠）
# 加反引号 ` 以匹配前端模板字面量（NapCat 扩展页面 iframe src 用模板字面量）
# (?!/plugin) 负向预查：防止二次重写代理前缀 PROXY_PREFIX 自身包含的 /api
# (?=[/"'\s;)]) 正向预查：确保匹配到完整的路径词而非子串
# 重写后的路径含 _v 版本段，强制浏览器每次插件加载后重新请求
REWRITE_WEBUI = re.compile(r"""(["'`(=\s])/webui(?!/plugin)(?=[/"'\s;)])""")
REWRITE_WEBUI_REPL = rf'\1{PROXY_PREFIX}/_v{_CACHE_BUSTER}/webui'
REWRITE_API = re.compile(r"""(["'`(=\s])/api(?!/plugin)(?=[/"'\s;)])""")
REWRITE_API_REPL = rf'\1{PROXY_PREFIX}/_v{_CACHE_BUSTER}/api'
# /files/theme.css 等静态资源（由无 baseURL 的 axios 实例 Fd 直接请求）
REWRITE_FILES = re.compile(r"""(["'`(=\s])/files(?!/plugin)(?=[/"'\s;)])""")
REWRITE_FILES_REPL = rf'\1{PROXY_PREFIX}/_v{_CACHE_BUSTER}/files'
# /plugin/xxx 等 NapCat 插件扩展页面 iframe src（模板字面量 \`/plugin/${id}/page/${path}\`）
# 正向预查包含 $ 以匹配模板字面量中的 ${expression}
# 无需 (?!/xxx) 防二次重写：代理前缀中 /api/plugin/napcat_connector 的 /plugin 前是字母 i，
# 不在字符类 ["'`(=\s] 中，不会误匹配
REWRITE_PLUGIN = re.compile(r"""(["'`(=\s])/plugin(?=[/"'\s;$])""")
REWRITE_PLUGIN_REPL = rf'\1{PROXY_PREFIX}/_v{_CACHE_BUSTER}/plugin'


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
        反向代理入口：iframe 加载重定向端点，由后端实时读取配置中的 token，
        302 跳转到带 token 的代理路径。这样前端 JS 能从 window.location.search
        提取 token 完成自动登录，且配置热更新立即生效。
        """
        return PluginPage.from_url(f"{PLUGIN_API_PREFIX}/entry")

    @register.api("GET", "/entry", auth=False)
    async def proxy_entry(self):
        """动态重定向入口：每次请求读取最新配置，拼 token 后 302 跳转到代理首页

        注册路径 /entry -> 完整 URL /api/plugin/napcat_connector/entry
        from_url 指向此路径（非 /proxy/ 下），避免被 /proxy/{path:path} 捕获。
        URL 含 _v 版本段 + _t 时间戳，强制浏览器放弃旧缓存。
        """
        token = self.plugin_cfg.get("webui_token", "")
        url = f"{PROXY_PREFIX}/_v{_CACHE_BUSTER}/webui/?_t={int(time.time() * 1000)}"
        if token:
            url += f"&token={token}"
        return RedirectResponse(url=url, status_code=302)

    @register.api("GET", "/proxy/{path:path}", auth=False)
    async def proxy_get(self, path: str, request: Request):
        """反向代理 GET 请求"""
        return await self._proxy("GET", path, request)

    @register.api("POST", "/proxy/{path:path}", auth=False)
    async def proxy_post(self, path: str, request: Request):
        """反向代理 POST 请求"""
        return await self._proxy("POST", path, request)

    @register.api("HEAD", "/proxy/{path:path}", auth=False)
    async def proxy_head(self, path: str, request: Request):
        """反向代理 HEAD 请求"""
        return await self._proxy("HEAD", path, request)

    @register.ws("/terminal", auth=False)
    async def ws_terminal_proxy(self, ws: WebSocket):
        """代理 NapCat 系统终端 WebSocket

        浏览器连接 KiraAI 的 /ws/plugin/napcat_connector/terminal，
        本处理器再直连 NapCat 的 /api/ws/terminal，双向转发。
        """
        await ws.accept()
        qp = dict(ws.query_params)
        tid = qp.get("id", "")
        token = qp.get("token", "")
        if not tid or not token:
            await ws.close(code=1008, reason="Missing id or token")
            return

        napcat_ws_url = f"ws://127.0.0.1:6099/api/ws/terminal?id={tid}&token={token}"

        try:
            async with websockets.connect(napcat_ws_url) as nws:
                async def browser_to_napcat():
                    try:
                        while True:
                            data = await ws.receive_text()
                            await nws.send(data)
                    except Exception:
                        pass

                async def napcat_to_browser():
                    try:
                        while True:
                            data = await nws.recv()
                            await ws.send_text(data)
                    except Exception:
                        pass

                await asyncio.gather(browser_to_napcat(), napcat_to_browser())
        except websockets.exceptions.WebSocketException as e:
            await ws.close(code=1011, reason=str(e))
        except Exception as e:
            logger.error(f"Terminal WS 代理错误: {e}")
            try:
                await ws.close(code=1011, reason="Internal error")
            except Exception:
                pass

    async def _proxy(self, method: str, path: str, request: Request) -> Response:
        """代理核心逻辑"""
        if not path:
            path = "webui/"

        # 剥离缓存破坏版本段 _vxxxx/（仅用于让浏览器 URL 变化，不传给 NapCat）
        path = re.sub(r'^_v\d+/', '', path)

        # 拦截 Service Worker 脚本：代理环境下 SW 会缓存未重写的旧 JS 导致 422
        if path.rstrip("/").endswith("/sw.js"):
            return Response(content="// disabled", status_code=404,
                            media_type="application/javascript")

        # 从配置动态读取 NapCat 地址（配置热更新）
        napcat_base = self.plugin_cfg.get("webui_url", NAPCAT_DEFAULT_BASE).rstrip("/")
        target_url = f"{napcat_base}/{path.lstrip('/')}"

        # 转发 query string（如 /Log/GetLog?id=xxx）
        query_string = request.url.query
        if query_string:
            target_url += f"?{query_string}"

        # POST 时读取请求体
        body = None
        if method == "POST":
            body = await request.body()

        # 转发请求头：透传客户端的头（Authorization/Cookie 等），排除 hop-by-hop 头
        # 同时剥离条件请求头：代理重写了响应体，304 缓存会导致浏览器用未重写的旧内容
        skip_headers = {"host", "content-length", "transfer-encoding",
                        "connection", "x-frame-options", "content-security-policy",
                        "if-none-match", "if-modified-since", "if-unmodified-since"}
        forward_headers = {}
        for key, val in request.headers.items():
            if key.lower() not in skip_headers:
                forward_headers[key] = val

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                # 使用流式请求以支持 SSE（EventSource 长连接）
                async with client.stream(
                    method=method,
                    url=target_url,
                    content=body,
                    headers=forward_headers,
                    follow_redirects=False,
                ) as resp:
                    # 构建响应头（统一处理，流式和非流式共用）
                    res_headers = dict(resp.headers)
                    if "location" in res_headers:
                        loc = res_headers["location"]
                        if loc.startswith("/webui") or loc.startswith("/api/"):
                            res_headers["location"] = f"{PROXY_PREFIX}/_v{_CACHE_BUSTER}{loc}"

                    # 剥离不兼容的响应头
                    res_headers.pop("x-frame-options", None)
                    res_headers.pop("content-security-policy", None)
                    res_headers.pop("content-encoding", None)
                    res_headers.pop("transfer-encoding", None)
                    res_headers.pop("content-length", None)
                    res_headers.pop("etag", None)
                    res_headers.pop("last-modified", None)
                    res_headers["cache-control"] = "no-store"

                    content_type = resp.headers.get("content-type", "")

                    # SSE 流式响应：httpx 不支持 SSE 长连接（aiter_bytes 不 yield），
                    # 改用同步 http.client 在后台线程读取，通过 Queue 桥接到
                    # StreamingResponse
                    if "text/event-stream" in content_type:
                        from urllib.parse import urlparse as _up
                        _parsed = _up(napcat_base)
                        _sse_path = f"/{path.lstrip('/')}"
                        if query_string:
                            _sse_path += f"?{query_string}"

                        async def _sse_stream():
                            import http.client as _hc
                            q = asyncio.Queue()
                            _done = object()

                            def _fetch():
                                try:
                                    c = _hc.HTTPConnection(
                                        _parsed.hostname, _parsed.port or 6099,
                                        timeout=None)
                                    c.request(method, _sse_path,
                                              body=body,
                                              headers=forward_headers)
                                    r = c.getresponse()
                                    while True:
                                        chunk = r.read1(65536)
                                        if not chunk:
                                            break
                                        loop.call_soon_threadsafe(
                                            q.put_nowait, chunk)
                                except Exception:
                                    pass
                                finally:
                                    loop.call_soon_threadsafe(
                                        q.put_nowait, _done)

                            loop = asyncio.get_running_loop()
                            fut = loop.run_in_executor(None, _fetch)
                            while True:
                                item = await q.get()
                                if item is _done:
                                    break
                                yield item
                            await fut
                        return StreamingResponse(
                            content=_sse_stream(),
                            status_code=resp.status_code,
                            headers=res_headers,
                            media_type=content_type or None,
                        )

                    # 非流式响应：收集完整 body 后做路径重写
                    body = b""
                    async for chunk in resp.aiter_bytes():
                        body += chunk
                    # 保存供外层使用（resp 在 async with 块结束后不可用）
                    _status = resp.status_code
            except httpx.RequestError as e:
                logger.error(f"代理请求失败: {e}")
                return Response(content=f"Proxy error: {e}", status_code=502)

        # ====== 以下仅适用于非流式响应（body 已完整收集）======

        # 只对文本类内容做路径重写，二进制内容（图片/字体/音视频）透传
        needs_rewrite = any(
            t in content_type
            for t in ["text/html", "text/javascript", "application/javascript",
                      "text/css", "application/json"]
        )
        if needs_rewrite:
            body_str = body.decode("utf-8", errors="replace")
            # 统一重写所有文本内容中的绝对路径
            # (?!/plugin) 确保不二次重写代理前缀中已有的 /api
            body_str = REWRITE_API.sub(REWRITE_API_REPL, body_str)
            body_str = REWRITE_WEBUI.sub(REWRITE_WEBUI_REPL, body_str)
            body_str = REWRITE_FILES.sub(REWRITE_FILES_REPL, body_str)
            body_str = REWRITE_PLUGIN.sub(REWRITE_PLUGIN_REPL, body_str)
            # 修复插件 WebSocket URL：window.location.origin 指向代理页面的 KiraAI 地址，
            # 但 WebSocket 必须直连 NapCat（端口 6099），不能走代理（代理不支持 WS 升级）
            body_str = body_str.replace(
                "window.location.origin",
                '"http://127.0.0.1:6099"')
            body_str = body_str.replace(
                f"{PROXY_PREFIX}/_v{_CACHE_BUSTER}/api/Debug/ws",
                "/api/Debug/ws")
            # 修复终端 WebSocket 路径：将代理 HTTP 路径改为 KiraAI 的 WebSocket 端点
            body_str = body_str.replace(
                f"{PROXY_PREFIX}/_v{_CACHE_BUSTER}/api/ws/terminal",
                "/ws/plugin/napcat_connector/terminal")
            # 禁用 Service Worker 注册（在 JS 中，不在 HTML 中）
            # 代理环境下 SW 会缓存未重写的旧 JS 导致 422
            body_str = body_str.replace(
                '"serviceWorker"in navigator&&window.addEventListener("load",',
                'false&&window.addEventListener("load",')
            if "text/html" in content_type:
                # 注入 <base> 标签 + 启动脚本
                # 1. <base>: 将 NapCat 页面中所有以 / 开头的相对 URL 解析为代理路径，
                #    包括 fetch/XHR/EventSource 请求、<script src>、<link href> 等。
                #    无论路径以 /api/ /webui/ /files/ /plugin/ /assets/ 还是其他开头，
                #    浏览器都自动解析为 {PROXY}/_v{version}/原路径，实现"一了百了"。
                # 2. localStorage 隔离：同源 iframe 与主窗口共享 Storage.prototype
                #    但实例不同，用 this === window.localStorage 区分
                # 3. Service Worker 清理：旧 SW 可能缓存未重写内容
                _base_href = f"{PROXY_PREFIX}/_v{_CACHE_BUSTER}/"
                _inject_html = f"""<base href="{_base_href}">
<script>
(function(k){{var ls=window.localStorage,P=Storage.prototype,G=P.getItem,S=P.setItem,R=P.removeItem;
P.getItem=function(n){{return this===ls?G.call(this,k+n):G.call(this,n)}};
P.setItem=function(n,v){{this===ls?S.call(this,k+n,v):S.call(this,n,v)}};
P.removeItem=function(n){{this===ls?R.call(this,k+n):R.call(this,n)}};
}})("napcat_");
(function(){{if(navigator&&navigator.serviceWorker)
navigator.serviceWorker.getRegistrations().then(function(rs){{rs.forEach(function(r){{r.unregister()}})}}).catch(function(){{}})
}})();
</script>"""
                body_str = body_str.replace("<head>", f"<head>{_inject_html}")
            body = body_str.encode("utf-8")

        return Response(
            content=body,
            status_code=_status or 200,
            headers=res_headers,
            media_type=content_type or None,
        )
