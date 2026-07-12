"""
NapCat Connector — KiraAI 插件
反向代理模式：所有 NapCat WebUI 流量走 KiraAI 中转
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import time
import asyncio
import websockets
from fastapi import Request, Response, WebSocket
from fastapi.responses import RedirectResponse, StreamingResponse
from core.plugin import BasePlugin, PluginContext, register, PageMenu, PluginPage, logger

from proxy_utils import (
    PROXY_PREFIX,
    PLUGIN_API_PREFIX,
    NAPCAT_DEFAULT_BASE,
    WS_PROXY_PREFIX,
    HTTP_METHODS,
    rewrite_paths,
    strip_version,
    build_entry_url,
    build_direct_entry_url,
    is_text_content,
    is_sse_response,
    should_read_body,
    build_ws_target_url,
    build_inject_html,
    HttpClientManager,
)


class NapcatConnectorPlugin(BasePlugin):

    def __init__(self, ctx: PluginContext, cfg: dict):
        super().__init__(ctx, cfg)
        self._cache_buster = str(int(time.time() * 1000))

    async def initialize(self):
        self._http_mgr = HttpClientManager()
        await self._http_mgr.initialize()
        self._cache_buster = str(int(time.time() * 1000))
        logger.info("NapCat Connector 已就绪（代理模式）")

    async def terminate(self):
        logger.info("NapCat Connector 正在关闭...")
        await self._http_mgr.terminate()
        logger.info("NapCat Connector 已关闭")

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
        """动态重定向入口：根据 connection_mode 决定跳转到代理路径或外部 NapCat URL

        - proxy 模式：跳转到内部代理路径（含 _v/ 缓存破坏段 + token）
        - direct 模式：跳转到外部 NapCat URL（直连，不带缓存破坏段）
        每次请求读取最新配置，模式/ token 热更新即时生效。
        """
        if self.plugin_cfg.get("connection_mode", "proxy") == "direct":
            napcat_base = self.plugin_cfg.get("webui_url", NAPCAT_DEFAULT_BASE)
            token = self.plugin_cfg.get("webui_token", "")
            url = build_direct_entry_url(napcat_base, token)
        else:
            token = self.plugin_cfg.get("webui_token", "")
            url = build_entry_url(PROXY_PREFIX, self._cache_buster, token)
        resp = RedirectResponse(url=url, status_code=302)
        resp.headers["cache-control"] = "no-store"
        return resp

    # 循环注册所有 HTTP 方法（利用默认参数绑定避免闭包陷阱）
    for _method in HTTP_METHODS:
        @register.api(_method, "/proxy/{path:path}", auth=False)
        async def _proxy_handler(self, path: str, request: Request, _m=_method):
            """反向代理 {_m} 请求"""
            return await self._proxy(_m, path, request)

    @register.ws("/{ws_path:path}", auth=False)
    async def ws_proxy(self, ws: WebSocket):
        """通配 WebSocket 代理：所有 WS 流量经 KiraAI 中转，NapCat 端口零暴露

        浏览器连接 /ws/plugin/napcat_connector/api/ws/terminal?id=x&token=y
        -> ws_path = "api/ws/terminal"
        -> 连接 NapCat ws://127.0.0.1:6099/api/ws/terminal?id=x&token=y
        """
        await ws.accept()
        ws_path = ws.path_params.get("ws_path", "")
        if not ws_path:
            await ws.close(code=1008, reason="Empty path")
            return

        napcat_base = self.plugin_cfg.get("webui_url", NAPCAT_DEFAULT_BASE)
        query_params = dict(ws.query_params)
        target_url = build_ws_target_url(napcat_base, ws_path, query_params)

        try:
            async with websockets.connect(target_url) as nws:
                async def browser_to_napcat():
                    try:
                        while True:
                            data = await ws.receive_text()
                            await nws.send(data)
                    except Exception:
                        pass
                    finally:
                        try:
                            await nws.close()
                        except Exception:
                            pass

                async def napcat_to_browser():
                    try:
                        while True:
                            data = await nws.recv()
                            await ws.send_text(data)
                    except Exception:
                        pass
                    finally:
                        try:
                            await ws.close()
                        except Exception:
                            pass

                await asyncio.gather(browser_to_napcat(), napcat_to_browser(),
                                     return_exceptions=True)
        except websockets.exceptions.WebSocketException as e:
            try:
                await ws.close(code=1011, reason=str(e))
            except Exception:
                pass
        except Exception as e:
            logger.error(f"WS 代理错误 ({ws_path}): {e}")
            try:
                await ws.close(code=1011, reason="Internal error")
            except Exception:
                pass

    async def _proxy(self, method: str, path: str, request: Request) -> Response:
        """代理核心逻辑"""
        if not path:
            path = "webui/"

        # 剥离缓存破坏版本段 _vxxxx/（仅用于让浏览器 URL 变化，不传给 NapCat）
        path = strip_version(path)

        # 拦截 Service Worker 脚本：代理环境下 SW 会缓存未重写的旧 JS 导致 422
        if path.rstrip("/").endswith("/sw.js"):
            return Response(content="// disabled", status_code=404,
                            media_type="application/javascript")

        # 从配置动态读取 NapCat 地址（配置热更新）
        napcat_base = self.plugin_cfg.get("webui_url", NAPCAT_DEFAULT_BASE).rstrip("/")
        target_url = f"{napcat_base}/{path.lstrip('/')}"

        # 转发 query string
        query_string = request.url.query
        if query_string:
            target_url += f"?{query_string}"

        # POST/PUT/PATCH 时读取请求体
        body = None
        if method in ("POST", "PUT", "PATCH"):
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

        client = self._http_mgr.client
        try:
            req = client.build_request(
                method=method,
                url=target_url,
                content=body,
                headers=forward_headers,
            )
            resp = await client.send(req, stream=True)
        except (httpx.RequestError, RuntimeError) as e:
            logger.error(f"代理请求失败: {e}")
            return Response(content=f"Proxy error: {e}", status_code=502)

        # 构建响应头（统一处理，流式和非流式共用）
        res_headers = dict(resp.headers)
        if "location" in res_headers:
            loc = res_headers["location"]
            if loc.startswith("/webui") or loc.startswith("/api/"):
                res_headers["location"] = f"{PROXY_PREFIX}/_v{self._cache_buster}{loc}"

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

        # ==== SSE 流式响应 ====
        if is_sse_response(content_type):
            async def _sse_stream():
                try:
                    async for chunk in resp.aiter_bytes():
                        yield chunk
                finally:
                    try:
                        await resp.aclose()
                    except Exception:
                        pass

            return StreamingResponse(
                content=_sse_stream(),
                status_code=resp.status_code,
                headers=res_headers,
                media_type=content_type or None,
            )

        # ==== 非流式响应 ====
        _status = resp.status_code
        try:
            if should_read_body(method):
                body = await resp.aread()
            else:
                body = b""
        except (httpx.RequestError, RuntimeError) as e:
            logger.error(f"代理读取响应失败 (shutdown?): {e}")
            body = b""
        finally:
            await resp.aclose()

        # 只对文本类内容做路径重写，二进制内容（图片/字体/音视频）透传
        if is_text_content(content_type):
            body_str = body.decode("utf-8", errors="replace")
            # 统一重写所有文本内容中的绝对路径
            body_str = rewrite_paths(body_str, PROXY_PREFIX, self._cache_buster)
            # 禁用 Service Worker 注册（在 JS 中，不在 HTML 中）
            # 代理环境下 SW 会缓存未重写的旧 JS 导致 422
            body_str = body_str.replace(
                '"serviceWorker"in navigator&&window.addEventListener("load",',
                'false&&window.addEventListener("load",')
            if "text/html" in content_type:
                # 注入 <base> 标签 + 启动脚本 + WebSocket 拦截器
                _inject_html = build_inject_html(
                    PROXY_PREFIX, self._cache_buster, WS_PROXY_PREFIX)
                body_str = body_str.replace("<head>", f"<head>{_inject_html}")
            body = body_str.encode("utf-8")

        return Response(
            content=body,
            status_code=_status or 200,
            headers=res_headers,
            media_type=content_type or None,
        )
