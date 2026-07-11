"""proxy_utils 纯函数单元测试

不依赖 KiraAI 运行时，直接 import proxy_utils 模块。
"""
import pytest
from proxy_utils import (
    PROXY_PREFIX,
    PLUGIN_API_PREFIX,
    WS_PROXY_PREFIX,
    HTTP_METHODS,
    rewrite_paths,
    strip_version,
    build_entry_url,
    is_text_content,
    is_sse_response,
    should_read_body,
    build_ws_target_url,
    build_ws_interceptor_js,
    build_inject_html,
    HttpClientManager,
)

_CB = "1234567890"  # 固定 cache_buster 用于测试


# ==============================================================
# 路径重写
# ==============================================================

class TestRewritePaths:
    """验证 /api、/webui、/files、/plugin 路径重写规则"""

    def test_api_with_trailing_slash(self):
        """带尾斜杠的 /api/ 路径应被重写"""
        src = 'fetch("/api/auth/login")'
        result = rewrite_paths(src, PROXY_PREFIX, _CB)
        assert result == f'fetch("{PROXY_PREFIX}/_v{_CB}/api/auth/login")'

    def test_api_without_trailing_slash(self):
        """无尾斜杠的 /api（axios baseURL）应被重写——422 bug 的根因"""
        src = 'const r="/api";e.baseURL=r;'
        result = rewrite_paths(src, PROXY_PREFIX, _CB)
        assert result == f'const r="{PROXY_PREFIX}/_v{_CB}/api";e.baseURL=r;'

    def test_webui_with_trailing_slash(self):
        """带尾斜杠的 /webui/ 路径应被重写"""
        src = '"/webui/assets/index.js"'
        result = rewrite_paths(src, PROXY_PREFIX, _CB)
        assert result == f'"{PROXY_PREFIX}/_v{_CB}/webui/assets/index.js"'

    def test_webui_without_trailing_slash(self):
        """无尾斜杠的 /webui 应被重写"""
        src = '"/webui"'
        result = rewrite_paths(src, PROXY_PREFIX, _CB)
        assert result == f'"{PROXY_PREFIX}/_v{_CB}/webui"'

    def test_sse_paths_rewritten(self):
        """SSE 端点路径应被重写"""
        for path in ["/api/base/GetSysStatusRealTime", "/api/Log/GetLogRealTime"]:
            src = f'"{path}"'
            result = rewrite_paths(src, PROXY_PREFIX, _CB)
            assert result == f'"{PROXY_PREFIX}/_v{_CB}{path}"'

    def test_no_double_rewrite(self):
        """已重写的代理前缀不应被二次重写"""
        already = f'"{PROXY_PREFIX}/_v{_CB}/api/auth/login"'
        assert rewrite_paths(already, PROXY_PREFIX, _CB) == already

    def test_no_double_rewrite_webui(self):
        """已重写的 /webui 代理前缀不应被二次重写"""
        already = f'"{PROXY_PREFIX}/_v{_CB}/webui/"'
        assert rewrite_paths(already, PROXY_PREFIX, _CB) == already

    def test_unrelated_code_untouched(self):
        """不含路径的代码不应被修改"""
        src = "e.baseURL=r;const t=localStorage.getItem(x)"
        assert rewrite_paths(src, PROXY_PREFIX, _CB) == src

    def test_webui_substring_not_matched(self):
        """/webui_plugin 等子串不应被误匹配"""
        src = '"/webui_plugin"'
        assert rewrite_paths(src, PROXY_PREFIX, _CB) == src

    def test_files_path_rewritten(self):
        """/files/theme.css 等静态资源路径应被重写"""
        src = 'Fd("/files/theme.css?_t=123")'
        result = rewrite_paths(src, PROXY_PREFIX, _CB)
        assert result == f'Fd("{PROXY_PREFIX}/_v{_CB}/files/theme.css?_t=123")'

    def test_files_no_double_rewrite(self):
        """已重写的 /files 代理前缀不应被二次重写"""
        already = f'"{PROXY_PREFIX}/_v{_CB}/files/theme.css"'
        assert rewrite_paths(already, PROXY_PREFIX, _CB) == already

    def test_plugin_template_literal(self):
        """插件扩展页面 iframe src（模板字面量）应被重写"""
        src = "return`/plugin/${e}/page/${l}`"
        result = rewrite_paths(src, PROXY_PREFIX, _CB)
        assert f"{PROXY_PREFIX}/_v{_CB}/plugin" in result

    def test_plugin_string(self):
        """插件路径（字符串字面量）应被重写"""
        src = '"/plugin/some/page"'
        assert rewrite_paths(src, PROXY_PREFIX, _CB) == (
            f'"{PROXY_PREFIX}/_v{_CB}/plugin/some/page"'
        )

    def test_proxy_prefix_plugin_not_matched(self):
        """代理前缀中的 /plugin（/api/plugin/...）不应被误匹配"""
        src = f'const x="{PROXY_PREFIX}/_v{_CB}/plugin/page"'
        assert rewrite_paths(src, PROXY_PREFIX, _CB) == src

    def test_both_rules_apply(self):
        """同一段文本中 /api 和 /webui 都应被重写"""
        src = 'const a="/api";const b="/webui/"'
        result = rewrite_paths(src, PROXY_PREFIX, _CB)
        assert f"{PROXY_PREFIX}/_v{_CB}/api" in result
        assert f"{PROXY_PREFIX}/_v{_CB}/webui/" in result

    def test_real_napcat_interceptor(self):
        """模拟 NapCat 真实的 axios 拦截器代码"""
        src = (
            'interceptors.request.use(e=>{const r="/api";e.baseURL=r;'
            'const t=localStorage.getItem("token");'
            'return t&&(e.headers.Authorization=`Bearer ${t}`),e})'
        )
        result = rewrite_paths(src, PROXY_PREFIX, _CB)
        assert 'r="/api"' not in result
        assert f'r="{PROXY_PREFIX}/_v{_CB}/api"' in result


# ==============================================================
# 版本段剥离
# ==============================================================

class TestStripVersion:
    """验证 _v 版本段剥离逻辑"""

    def test_strip_version_from_webui(self):
        """_v 版本段应被正确剥离"""
        assert strip_version("_v123456/webui/") == "webui/"
        assert strip_version("_v123456/webui/assets/index.js") == "webui/assets/index.js"

    def test_strip_version_from_api(self):
        """_v 版本段从 api 路径剥离"""
        assert strip_version("_v123456/api/auth/login") == "api/auth/login"

    def test_no_version_prefix(self):
        """无版本段时路径不变"""
        assert strip_version("webui/") == "webui/"
        assert strip_version("api/auth/login") == "api/auth/login"


# ==============================================================
# Entry 重定向 URL
# ==============================================================

class TestBuildEntryUrl:
    """验证 entry 重定向 URL 构建"""

    def test_entry_with_token(self):
        """有 token 时 URL 应带版本段 + token"""
        url = build_entry_url(PROXY_PREFIX, _CB, "f700fb2517c4")
        assert f"_v{_CB}" in url
        assert "token=f700fb2517c4" in url

    def test_entry_without_token(self):
        """无 token 时 URL 不带 token"""
        url = build_entry_url(PROXY_PREFIX, _CB, "")
        assert f"_v{_CB}" in url
        assert "token=" not in url

    def test_entry_has_timestamp(self):
        """URL 应含时间戳 _t"""
        url = build_entry_url(PROXY_PREFIX, _CB, "x")
        assert "_t=" in url


# ==============================================================
# Content-Type 工具函数
# ==============================================================

class TestContentTypeHelpers:
    """验证 Content-Type 判断函数"""

    def test_is_text_content_html(self):
        assert is_text_content("text/html") is True

    def test_is_text_content_js(self):
        assert is_text_content("application/javascript") is True
        assert is_text_content("text/javascript") is True

    def test_is_text_content_css(self):
        assert is_text_content("text/css") is True

    def test_is_text_content_json(self):
        assert is_text_content("application/json") is True

    def test_is_text_content_image(self):
        assert is_text_content("image/png") is False

    def test_is_text_content_font(self):
        assert is_text_content("font/woff2") is False

    def test_is_sse_response_true(self):
        assert is_sse_response("text/event-stream") is True

    def test_is_sse_response_false(self):
        assert is_sse_response("application/json") is False

    def test_should_read_body_get(self):
        assert should_read_body("GET") is True

    def test_should_read_body_post(self):
        assert should_read_body("POST") is True

    def test_should_read_body_head(self):
        assert should_read_body("HEAD") is False

    def test_should_read_body_case_insensitive(self):
        assert should_read_body("head") is False
        assert should_read_body("Head") is False


# ==============================================================
# WebSocket 目标 URL 构建
# ==============================================================

class TestBuildWsTargetUrl:
    """验证 NapCat WebSocket 目标 URL 构建"""

    def test_http_to_ws(self):
        """http:// 应转为 ws://"""
        result = build_ws_target_url("http://127.0.0.1:6099", "api/ws/terminal", {})
        assert result == "ws://127.0.0.1:6099/api/ws/terminal"

    def test_https_to_wss(self):
        """https:// 应转为 wss://"""
        result = build_ws_target_url("https://napcat.local:6099", "api/ws/terminal", {})
        assert result == "wss://napcat.local:6099/api/ws/terminal"

    def test_with_query_params(self):
        """query_params 应附加到 URL"""
        result = build_ws_target_url(
            "http://127.0.0.1:6099", "api/ws/terminal",
            {"id": "abc", "token": "xyz"},
        )
        assert "?id=abc&token=xyz" in result

    def test_without_query_params(self):
        """无 query_params 时不带 ? 号"""
        result = build_ws_target_url("http://127.0.0.1:6099", "api/ws/terminal", {})
        assert "?" not in result

    def test_strips_trailing_slash_from_base(self):
        """napcat_base 的尾斜杠应被剥离"""
        result = build_ws_target_url("http://127.0.0.1:6099/", "api/ws/terminal", {})
        assert result == "ws://127.0.0.1:6099/api/ws/terminal"

    def test_handles_leading_slash_in_ws_path(self):
        """ws_path 的前导斜杠应被剥离"""
        result = build_ws_target_url("http://127.0.0.1:6099", "/api/ws/terminal", {})
        assert result == "ws://127.0.0.1:6099/api/ws/terminal"

    def test_multiple_query_params(self):
        result = build_ws_target_url(
            "http://127.0.0.1:6099", "api/Debug/ws",
            {"token": "x", "id": "y", "extra": "z"},
        )
        assert "token=x" in result
        assert "id=y" in result
        assert "extra=z" in result


# ==============================================================
# WebSocket 拦截器 JS 生成
# ==============================================================

class TestBuildWsInterceptorJs:
    """验证 WebSocket 拦截器脚本内容"""

    def test_contains_override(self):
        js = build_ws_interceptor_js(WS_PROXY_PREFIX, PROXY_PREFIX)
        assert "window.WebSocket=function" in js

    def test_contains_prototype_preservation(self):
        js = build_ws_interceptor_js(WS_PROXY_PREFIX, PROXY_PREFIX)
        assert "window.WebSocket.prototype=OW.prototype" in js

    def test_contains_constants(self):
        js = build_ws_interceptor_js(WS_PROXY_PREFIX, PROXY_PREFIX)
        assert "CONNECTING=OW.CONNECTING" in js
        assert "OPEN=OW.OPEN" in js
        assert "CLOSING=OW.CLOSING" in js
        assert "CLOSED=OW.CLOSED" in js

    def test_contains_ws_proxy_prefix(self):
        js = build_ws_interceptor_js(WS_PROXY_PREFIX, PROXY_PREFIX)
        assert WS_PROXY_PREFIX in js

    def test_contains_url_rewrite(self):
        js = build_ws_interceptor_js(WS_PROXY_PREFIX, PROXY_PREFIX)
        assert "u.pathname='" in js
        assert "u.protocol=" in js
        assert "u.host=" in js

    def test_contains_proxy_prefix_strip_logic(self):
        """拦截器应包含代理前缀剥离逻辑（防止 rewrite_paths 导致路径嵌套）"""
        js = build_ws_interceptor_js(WS_PROXY_PREFIX, PROXY_PREFIX)
        assert "PP" in js  # 正则变量
        assert ".replace(PP" in js  # 剥离调用
        # 正则中应包含转义的 proxy_prefix
        assert PROXY_PREFIX.replace("/", "\\/") in js or PROXY_PREFIX in js


# ==============================================================
# HTML 注入内容
# ==============================================================

class TestBuildInjectHtml:
    """验证 HTML 注入内容完整性"""

    def test_contains_base_tag(self):
        html = build_inject_html(PROXY_PREFIX, _CB, WS_PROXY_PREFIX)
        assert f'<base href="{PROXY_PREFIX}/_v{_CB}/">' in html

    def test_contains_localstorage_isolation(self):
        """应包含 localStorage 隔离（defineProperty 代理，不修改 prototype）"""
        html = build_inject_html(PROXY_PREFIX, _CB, WS_PROXY_PREFIX)
        # 用 defineProperty 替换 window.localStorage
        assert 'Object.defineProperty(window,"localStorage"' in html
        assert 'napcat_' in html  # 前缀
        # 不应修改 Storage.prototype（会污染主窗口）
        assert 'Storage.prototype' not in html

    def test_contains_sw_cleanup(self):
        html = build_inject_html(PROXY_PREFIX, _CB, WS_PROXY_PREFIX)
        assert "getRegistrations" in html
        assert "unregister" in html

    def test_contains_ws_interceptor(self):
        html = build_inject_html(PROXY_PREFIX, _CB, WS_PROXY_PREFIX)
        assert WS_PROXY_PREFIX in html
        assert "window.WebSocket.prototype=OW.prototype" in html

    def test_inject_order_base_first(self):
        """<base> 标签应在脚本之前"""
        html = build_inject_html(PROXY_PREFIX, _CB, WS_PROXY_PREFIX)
        base_idx = html.index('<base href=')
        script_idx = html.index('<script>')
        assert base_idx < script_idx, "<base> 应在 <script> 之前"


# ==============================================================
# HTTP_METHODS 常量
# ==============================================================

class TestHttpMethods:
    """验证 HTTP_METHODS 常量"""

    def test_contains_get(self):
        assert "GET" in HTTP_METHODS

    def test_contains_post(self):
        assert "POST" in HTTP_METHODS

    def test_contains_put(self):
        assert "PUT" in HTTP_METHODS

    def test_contains_delete(self):
        assert "DELETE" in HTTP_METHODS

    def test_contains_patch(self):
        assert "PATCH" in HTTP_METHODS

    def test_contains_head(self):
        assert "HEAD" in HTTP_METHODS

    def test_count(self):
        assert len(HTTP_METHODS) == 6

    def test_no_options(self):
        assert "OPTIONS" not in HTTP_METHODS


# ==============================================================
# HttpClientManager
# ==============================================================

class TestHttpClientManager:
    """验证连接池生命周期管理"""

    @pytest.mark.anyio
    async def test_initialize_creates_client(self):
        mgr = HttpClientManager()
        await mgr.initialize()
        assert mgr.client is not None
        await mgr.terminate()

    @pytest.mark.anyio
    async def test_terminate_closes_client(self):
        mgr = HttpClientManager()
        await mgr.initialize()
        await mgr.terminate()
        assert mgr._client is None

    @pytest.mark.anyio
    async def test_client_before_init_raises(self):
        mgr = HttpClientManager()
        try:
            _ = mgr.client
            assert False, "应抛出 RuntimeError"
        except RuntimeError:
            pass

    @pytest.mark.anyio
    async def test_terminate_idempotent(self):
        mgr = HttpClientManager()
        await mgr.initialize()
        await mgr.terminate()
        await mgr.terminate()  # 第二次不应报错

    @pytest.mark.anyio
    async def test_reinitialize(self):
        mgr = HttpClientManager()
        await mgr.initialize()
        await mgr.terminate()
        await mgr.initialize()
        assert mgr.client is not None
        await mgr.terminate()
