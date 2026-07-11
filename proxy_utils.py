"""
NapCat Connector — 纯函数工具模块

包含所有可独立测试的逻辑：路径重写规则、常量、JS 注入模板等。
不依赖 fastapi / websockets / core.plugin，测试环境可直接 import。
"""

import re
import time
import httpx
from urllib.parse import urlencode, urlparse

# ===== 常量 =====
PROXY_PREFIX = "/api/plugin/napcat_connector/proxy"
PLUGIN_API_PREFIX = "/api/plugin/napcat_connector"
NAPCAT_DEFAULT_BASE = "http://127.0.0.1:6099"
WS_PROXY_PREFIX = "/ws/plugin/napcat_connector"
HTTP_METHODS = ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD")

# ===== 路径重写正则规则 =====
# 在文本内容中搜索 NapCat 的绝对路径 /api /webui /files /plugin，
# 并将它们重写为 KiraAI 代理路径。
# (?!/plugin) 防二次重写：代理前缀自身包含 /api/plugin/napcat_connector，不应被再次匹配
# (?=[/"'\s;)]) 正向预查：确保匹配到完整的路径词而非子串

_REWRITE_API = re.compile(r"""(["'`(=\s])/api(?!/plugin)(?=[/"'\s;)])""")
_REWRITE_WEBUI = re.compile(r"""(["'`(=\s])/webui(?!/plugin)(?=[/"'\s;)])""")
_REWRITE_FILES = re.compile(r"""(["'`(=\s])/files(?!/plugin)(?=[/"'\s;)])""")
_REWRITE_PLUGIN = re.compile(r"""(["'`(=\s])/plugin(?=[/"'\s;$])""")

# 版本段剥离：_v{timestamp}/ 前缀（仅用于浏览器 URL 缓存破坏，不传给 NapCat）
_VERSION_RE = re.compile(r"^_v\d+/")

# 需要路径重写的 Content-Type 关键词
_TEXT_CONTENT_KEYWORDS = [
    "text/html",
    "text/javascript",
    "application/javascript",
    "text/css",
    "application/json",
]


def rewrite_paths(text: str, proxy_prefix: str, cache_buster: str) -> str:
    """对文本内容执行 4 条路径重写

    Args:
        text: JS/HTML/CSS 原文
        proxy_prefix: 如 "/api/plugin/napcat_connector/proxy"
        cache_buster: 如 "1741608123456"

    Returns:
        重写后的文本
    """
    api_repl = rf"\1{proxy_prefix}/_v{cache_buster}/api"
    webui_repl = rf"\1{proxy_prefix}/_v{cache_buster}/webui"
    files_repl = rf"\1{proxy_prefix}/_v{cache_buster}/files"
    plugin_repl = rf"\1{proxy_prefix}/_v{cache_buster}/plugin"

    text = _REWRITE_API.sub(api_repl, text)
    text = _REWRITE_WEBUI.sub(webui_repl, text)
    text = _REWRITE_FILES.sub(files_repl, text)
    text = _REWRITE_PLUGIN.sub(plugin_repl, text)
    return text


def strip_version(path: str) -> str:
    """剥离缓存破坏版本段 _vxxxx/"""
    return _VERSION_RE.sub("", path)


def build_entry_url(proxy_prefix: str, cache_buster: str, token: str) -> str:
    """构建 entry 重定向 URL

    URL 含 _v 版本段 + _t 时间戳，强制浏览器放弃旧缓存。
    """
    url = f"{proxy_prefix}/_v{cache_buster}/webui/?_t={int(time.time() * 1000)}"
    if token:
        url += f"&token={token}"
    return url


def is_text_content(content_type: str) -> bool:
    """判断 Content-Type 是否需要执行路径重写"""
    ct_lower = content_type.lower()
    return any(kw in ct_lower for kw in _TEXT_CONTENT_KEYWORDS)


def is_sse_response(content_type: str) -> bool:
    """判断是否为 SSE（Server-Sent Events）流式响应"""
    return "text/event-stream" in content_type.lower()


def should_read_body(method: str) -> bool:
    """HEA D 请求不需要读取响应体"""
    return method.upper() != "HEAD"


def build_ws_target_url(napcat_base: str, ws_path: str, query_params: dict) -> str:
    """构建 NapCat WebSocket 目标 URL

    Args:
        napcat_base: 如 "http://127.0.0.1:6099"
        ws_path: 如 "api/ws/terminal"（无前导 /）
        query_params: 如 {"id": "xxx", "token": "yyy"}

    Returns:
        如 "ws://127.0.0.1:6099/api/ws/terminal?id=xxx&token=yyy"
    """
    ws_base = napcat_base.replace("https://", "wss://").replace("http://", "ws://")
    ws_base = ws_base.rstrip("/")
    url = f"{ws_base}/{ws_path.lstrip('/')}"
    if query_params:
        url += "?" + urlencode(query_params)
    return url


def build_ws_interceptor_js(ws_proxy_prefix: str, proxy_prefix: str) -> str:
    """生成 WebSocket 构造器拦截脚本

    注入到 HTML <head> 中，在 NapCat 所有 JS 执行前运行。
    拦截所有 WebSocket 连接，将 URL 重写为 KiraAI 的 WS 代理路径，
    从而消除浏览器直连 NapCat 端口。

    注意：rewrite_paths 可能已将 JS 源码中的 "/api/Debug/ws" 重写为
    "{proxy_prefix}/_v{ts}/api/Debug/ws"，导致浏览器构建的 WS URL pathname
    包含代理前缀。拦截器需检测并剥离这种嵌套的代理路径段，再添加 WS 代理前缀。

    Args:
        ws_proxy_prefix: 如 "/ws/plugin/napcat_connector"
        proxy_prefix: 如 "/api/plugin/napcat_connector/proxy"（用于检测嵌套路径）
    """
    # 用 new RegExp() 构造，避免正则字面量 / 分隔符与 proxy_prefix 中的 / 冲突
    # proxy_prefix 中的 / 需转义为 \/，\d 需保持为 \\d
    escaped_prefix = proxy_prefix.replace("/", "\\/")
    return f"""<script>
(function(){{
  var OW=window.WebSocket;if(!OW)return;
  var PP=new RegExp('^{escaped_prefix}\\/_v\\\\d+\\/');
  window.WebSocket=function(url,protos){{
    try{{var u=new URL(url);
    u.protocol=location.protocol==='https:'?'wss:':'ws:';
    u.host=location.host;
    if(PP.test(u.pathname))u.pathname=u.pathname.replace(PP,'');
    u.pathname='{ws_proxy_prefix}'+u.pathname;
    url=u.toString();}}catch(e){{}}
    return protos?new OW(url,protos):new OW(url);
  }};
  window.WebSocket.prototype=OW.prototype;
  window.WebSocket.CONNECTING=OW.CONNECTING;
  window.WebSocket.OPEN=OW.OPEN;
  window.WebSocket.CLOSING=OW.CLOSING;
  window.WebSocket.CLOSED=OW.CLOSED;
}})();
</script>"""


def build_inject_html(proxy_prefix: str, cache_buster: str, ws_proxy_prefix: str) -> str:
    """生成注入到 HTML <head> 的完整内容

    包含：
    1. <base> 标签 — 将所有相对 URL 解析为代理路径
    2. localStorage 隔离 — 防止 iframe 与主窗口的 Storage 冲突
    3. Service Worker 清理 — 移除旧 SW 缓存
    4. WebSocket 拦截器 — 确保所有 WS 经 KiraAI 代理
    """
    base_href = f"{proxy_prefix}/_v{cache_buster}/"

    # localStorage 隔离 + SW 清理
    bootstrap_js = (
        '<script>'
        '(function(k){var ls=window.localStorage,P=Storage.prototype,'
        'G=P.getItem,S=P.setItem,R=P.removeItem;'
        'P.getItem=function(n){return this===ls?G.call(this,k+n):G.call(this,n)};'
        'P.setItem=function(n,v){this===ls?S.call(this,k+n,v):S.call(this,n,v)};'
        'P.removeItem=function(n){this===ls?R.call(this,k+n):R.call(this,n)};'
        '}})("napcat_");'
        '(function(){if(navigator&&navigator.serviceWorker)'
        'navigator.serviceWorker.getRegistrations().then(function(rs){'
        'rs.forEach(function(r){r.unregister()})}).catch(function(){})})();'
        '</script>'
    )

    ws_js = build_ws_interceptor_js(ws_proxy_prefix, proxy_prefix)
    return f'<base href="{base_href}">\n{bootstrap_js}\n{ws_js}'


class HttpClientManager:
    """管理共享 httpx.AsyncClient 连接池

    在插件 initialize() 时创建，terminate() 时关闭。
    所有 HTTP 代理请求复用同一连接池，避免 DNS 解析 + TCP 握手的重复开销。
    """

    def __init__(self):
        self._client: httpx.AsyncClient | None = None

    async def initialize(self, timeout: float = 30.0) -> None:
        """创建共享 http client 并配置连接池"""
        self._client = httpx.AsyncClient(
            limits=httpx.Limits(
                max_keepalive_connections=20,
                max_connections=100,
            ),
            timeout=httpx.Timeout(timeout, connect=5.0),
        )

    async def terminate(self) -> None:
        """关闭连接池"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("HttpClientManager not initialized")
        return self._client
