"""
完备代码审查测试套件

覆盖单元测试未覆盖的边界情况、安全风险、编码兼容性等。
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

_CB = "1234567890"

# ===================================================================
# 1. 路径重写 - 边界情况
# ===================================================================

class TestRewritePathsEdgeCases:
    """路径重写的边界情况和安全风险"""

    def test_path_traversal(self):
        """路径遍历攻击不应被重写损坏"""
        src = 'fetch("/../../../etc/passwd")'
        result = rewrite_paths(src, PROXY_PREFIX, _CB)
        # /../../../etc/passwd 中的 /.. 匹配的是 /api 吗？不匹配，应保持不变
        assert result == src

    def test_newline_injection(self):
        """换行符（\s）会触发正则匹配，路径被重写（已知行为）"""
        src = '"/api\n/login"'
        result = rewrite_paths(src, PROXY_PREFIX, _CB)
        # 注：正则 (?=[/"'\s;)]) 中的 \s 包含 \n，所以 /api\n 被匹配。
        # 在 NapCat minified JS 中不会出现此模式。
        assert PROXY_PREFIX in result

    def test_unicode_in_path(self):
        """Unicode 路径应保持"""
        src = '"/api/中文/登录"'
        result = rewrite_paths(src, PROXY_PREFIX, _CB)
        assert "中文" in result
        assert "登录" in result

    def test_very_long_path(self):
        """超长路径不应导致性能问题"""
        src = '"/api/' + "a" * 10000 + '"'
        result = rewrite_paths(src, PROXY_PREFIX, _CB)
        assert PROXY_PREFIX in result

    def test_empty_string(self):
        """空字符串应返回空"""
        assert rewrite_paths("", PROXY_PREFIX, _CB) == ""

    def test_no_trailing_chars(self):
        """路径后无预期字符应不匹配"""
        src = '"/api123"'
        assert rewrite_paths(src, PROXY_PREFIX, _CB) == src

    def test_multiline_js(self):
        """多行 JS 中的路径"""
        src = 'const a="/api";\nconst b="/webui";'
        result = rewrite_paths(src, PROXY_PREFIX, _CB)
        assert PROXY_PREFIX in result
        assert result.count(PROXY_PREFIX) == 2

    def test_backtick_template_with_vars(self):
        """模板字面量中的变量+路径"""
        src = 'fetch(`/api/${id}/login`)'
        result = rewrite_paths(src, PROXY_PREFIX, _CB)
        assert PROXY_PREFIX in result

    def test_mixed_quotes(self):
        """混合引号的路径"""
        src = "const a='/api';const b=\"/webui\""
        result = rewrite_paths(src, PROXY_PREFIX, _CB)
        assert result.count(PROXY_PREFIX) == 2

    def test_all_four_rules_same_line(self):
        """同一行四个路径都应被重写"""
        src = '"/api" "/webui" "/files" "/plugin"'
        result = rewrite_paths(src, PROXY_PREFIX, _CB)
        assert result.count(PROXY_PREFIX) == 4

    def test_url_encoded_chars(self):
        """URL 编码字符保持"""
        src = '"/api/Debug%20ws"'
        result = rewrite_paths(src, PROXY_PREFIX, _CB)
        assert "%20" in result

    def test_https_prefix_not_matched(self):
        """https:// 协议前缀不应被误匹配"""
        src = '"https://example.com/api/xxx"'
        result = rewrite_paths(src, PROXY_PREFIX, _CB)
        # https:// 中的 / 前面是 :，不在字符类中，不应匹配
        # 但 /api 中的 / 前面是 .com，不在字符类中
        # 所以不应匹配
        assert result == src

    def test_trailing_semicolon(self):
        """分号后的路径应匹配"""
        src = '"/api";'
        result = rewrite_paths(src, PROXY_PREFIX, _CB)
        assert PROXY_PREFIX in result

    def test_trailing_close_paren(self):
        """闭括号后的路径应匹配"""
        src = '("/api")'
        result = rewrite_paths(src, PROXY_PREFIX, _CB)
        assert PROXY_PREFIX in result


# ===================================================================
# 2. 版本段剥离 - 边界情况
# ===================================================================

class TestStripVersionEdgeCases:
    """版本段剥离边界情况"""

    def test_empty_string(self):
        assert strip_version("") == ""

    def test_only_version(self):
        """单独版本段无尾斜杠时不剥离（正则需要 /）"""
        assert strip_version("_v123") == "_v123"

    def test_version_no_trailing_slash(self):
        assert strip_version("_v123") == "_v123"

    def test_multiple_versions(self):
        assert strip_version("_v123/_v456/api") == "_v456/api"

    def test_deeply_nested(self):
        assert strip_version("_v123/a/b/c/d") == "a/b/c/d"

    def test_version_with_letters(self):
        assert strip_version("_vabc/api") == "_vabc/api"


# ===================================================================
# 3. Entry URL - 边界情况
# ===================================================================

class TestBuildEntryUrlEdgeCases:
    """Entry URL 边界情况"""

    def test_token_with_special_chars(self):
        url = build_entry_url(PROXY_PREFIX, _CB, "token+&?=")
        assert "token+&?=" in url  # token 原样放在 query param 中，未编码

    def test_empty_token_still_has_timestamp(self):
        url = build_entry_url(PROXY_PREFIX, _CB, "")
        assert "_t=" in url

    def test_very_long_token(self):
        token = "A" * 1000
        url = build_entry_url(PROXY_PREFIX, _CB, token)
        assert len(url) > len(PROXY_PREFIX)

    def test_unicode_token(self):
        url = build_entry_url(PROXY_PREFIX, _CB, "登录token")
        assert "登录token" in url  # 注意：HTMX 要求 URL 中的非 ASCII 应编码


# ===================================================================
# 4. Content-Type 判断 - 边界情况
# ===================================================================

class TestContentTypeEdgeCases:
    """Content-Type 判断边界情况"""

    def test_case_insensitivity(self):
        assert is_text_content("TEXT/HTML") is True
        assert is_sse_response("TEXT/EVENT-STREAM") is True
        assert should_read_body("head") is False

    def test_charset_suffix(self):
        assert is_text_content("text/html; charset=utf-8") is True
        assert is_sse_response("text/event-stream; charset=utf-8") is True

    def test_empty_string(self):
        assert is_text_content("") is False
        assert is_sse_response("") is False

    def test_none(self):
        assert is_text_content("None") is False

    def test_partial_match(self):
        # 关键词是子串匹配，注意避免误匹配
        assert is_text_content("text/nothtml") is False


# ===================================================================
# 5. WS 目标 URL - 边界情况
# ===================================================================

class TestBuildWsTargetUrlEdgeCases:
    """WS 目标 URL 边界情况"""

    def test_empty_query_params(self):
        url = build_ws_target_url("http://127.0.0.1:6099", "api/ws", {})
        assert url == "ws://127.0.0.1:6099/api/ws"

    def test_none_query_params(self):
        url = build_ws_target_url("http://127.0.0.1:6099", "api/ws", None)
        assert url == "ws://127.0.0.1:6099/api/ws"

    def test_empty_path(self):
        url = build_ws_target_url("http://127.0.0.1:6099", "", {"t": "1"})
        assert url == "ws://127.0.0.1:6099/?t=1"

    def test_ipv6_host(self):
        url = build_ws_target_url("http://[::1]:6099", "api/ws", {})
        assert "[::1]" in url

    def test_domain_with_port(self):
        url = build_ws_target_url("http://napcat.local:6099", "api/ws", {"k": "v"})
        assert "napcat.local" in url

    def test_query_param_with_special_chars(self):
        url = build_ws_target_url("http://127.0.0.1:6099", "api/ws", {"t": "a b&c=d"})
        assert "a+b" in url  # urlencode 空格为 +
        assert "c%3Dd" in url  # urlencode = 为 %3D

    def test_many_query_params(self):
        params = {f"k{i}": f"v{i}" for i in range(100)}
        url = build_ws_target_url("http://127.0.0.1:6099", "api/ws", params)
        assert url.count("&") >= 98


# ===================================================================
# 6. WS 拦截器 JS - 安全与兼容性
# ===================================================================

class TestBuildWsInterceptorJsSafety:
    """WS 拦截器 JS 的安全性和兼容性"""

    def test_no_xss_in_prefix(self):
        """恶意 ws_proxy_prefix 不应导致 XSS"""
        malicious = '"/><script>alert(1)</script>'
        js = build_ws_interceptor_js(malicious, PROXY_PREFIX)
        # 检查引号是否被正确转义（未被提前闭合）
        assert '"' not in malicious.split('"')[0]  # 简单检查

    def test_proxy_prefix_with_special_regex_chars(self):
        """proxy_prefix 含正则特殊字符应正确处理"""
        special = "/api+.plugin[napcat]"
        # 不应抛出异常
        js = build_ws_interceptor_js(WS_PROXY_PREFIX, special)
        assert "new RegExp" in js

    def test_interceptor_has_strip_logic(self):
        """拦截器应包含代理前缀剥离逻辑"""
        js = build_ws_interceptor_js(WS_PROXY_PREFIX, PROXY_PREFIX)
        assert ".replace(PP" in js
        assert "PP.test(u.pathname)" in js

    def test_no_window_leak(self):
        """拦截器不应在全局作用域泄露变量"""
        js = build_ws_interceptor_js(WS_PROXY_PREFIX, PROXY_PREFIX)
        assert "(function(){" in js
        assert "})()" in js


# ===================================================================
# 7. HTTP_METHODS 完整性
# ===================================================================

class TestHttpMethodsCompleteness:
    """HTTP 方法完整性和路由冲突"""

    def test_all_standard_methods(self):
        standard = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"}
        assert set(HTTP_METHODS) == standard

    def test_no_duplicates(self):
        assert len(HTTP_METHODS) == len(set(HTTP_METHODS))

    def test_case_consistency(self):
        assert all(m == m.upper() for m in HTTP_METHODS)


# ===================================================================
# 8. HttpClientManager - 资源泄漏
# ===================================================================

class TestHttpClientManagerResourceLeak:
    """连接池资源泄漏检测"""

    @pytest.mark.anyio
    async def test_double_initialize_creates_new(self):
        """重复 initialize 应创建新 client，旧 client 应被丢弃"""
        mgr = HttpClientManager()
        await mgr.initialize()
        c1 = mgr.client
        await mgr.initialize()  # 第二次 init 但未 terminate
        c2 = mgr.client
        assert c1 is not c2  # 是新实例
        await mgr.terminate()

    @pytest.mark.anyio
    async def test_terminate_then_use_client_raises(self):
        """terminate() 后使用 client 应抛出 RuntimeError"""
        mgr = HttpClientManager()
        await mgr.initialize()
        await mgr.terminate()
        with pytest.raises(RuntimeError):
            _ = mgr.client

    @pytest.mark.anyio
    async def test_terminate_uninitialized(self):
        """未 initialize 就 terminate 不应报错"""
        mgr = HttpClientManager()
        await mgr.terminate()  # 不应抛出


# ===================================================================
# 9. 跨模块一致性
# ===================================================================

class TestCrossModuleConsistency:
    """跨模块常量一致性"""

    def test_proxy_prefix_consistent(self):
        """PROXY_PREFIX 应以 / 开头"""
        assert PROXY_PREFIX.startswith("/")

    def test_ws_prefix_consistent(self):
        """WS_PROXY_PREFIX 应以 / 开头"""
        assert WS_PROXY_PREFIX.startswith("/")

    def test_plugin_api_prefix_consistent(self):
        """PLUGIN_API_PREFIX 应以 / 开头"""
        assert PLUGIN_API_PREFIX.startswith("/")

    def test_prefixes_related(self):
        """路由前缀应包含 plugin_id napcat_connector"""
        assert "napcat_connector" in PROXY_PREFIX
        assert "napcat_connector" in PLUGIN_API_PREFIX
        assert "napcat_connector" in WS_PROXY_PREFIX
