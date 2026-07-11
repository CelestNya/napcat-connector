"""NapCat Connector 插件测试

覆盖反向代理核心逻辑：路径重写规则（/api、/webui）、entry 重定向 URL 构建。
"""

import re

# 从 main.py 复制重写规则定义（独立测试，不依赖 KiraAI 运行时）
PROXY_PREFIX = "/api/plugin/napcat_connector/proxy"
_CACHE_BUSTER = "1234567890"  # 测试用固定值
REWRITE_WEBUI = re.compile(r"""(["'`(=\s])/webui(?!/plugin)(?=[/"'\s;)])""")
REWRITE_WEBUI_REPL = rf"\1{PROXY_PREFIX}/_v{_CACHE_BUSTER}/webui"
REWRITE_API = re.compile(r"""(["'`(=\s])/api(?!/plugin)(?=[/"'\s;)])""")
REWRITE_API_REPL = rf"\1{PROXY_PREFIX}/_v{_CACHE_BUSTER}/api"
REWRITE_FILES = re.compile(r"""(["'`(=\s])/files(?!/plugin)(?=[/"'\s;)])""")
REWRITE_FILES_REPL = rf"\1{PROXY_PREFIX}/_v{_CACHE_BUSTER}/files"
REWRITE_PLUGIN = re.compile(r"""(["'`(=\s])/plugin(?=[/"'\s;$])""")
REWRITE_PLUGIN_REPL = rf"\1{PROXY_PREFIX}/_v{_CACHE_BUSTER}/plugin"


def _rewrite(text: str) -> str:
    """模拟代理对文本内容的路径重写"""
    text = REWRITE_API.sub(REWRITE_API_REPL, text)
    text = REWRITE_WEBUI.sub(REWRITE_WEBUI_REPL, text)
    text = REWRITE_FILES.sub(REWRITE_FILES_REPL, text)
    text = REWRITE_PLUGIN.sub(REWRITE_PLUGIN_REPL, text)
    return text


def _strip_version(path: str) -> str:
    """模拟代理剥离 _v 版本段"""
    return re.sub(r'^_v\d+/', '', path)


class TestPathRewrite:
    """验证 /api 和 /webui 路径重写规则"""

    def test_api_with_trailing_slash(self):
        """带尾斜杠的 /api/ 路径应被重写"""
        src = 'fetch("/api/auth/login")'
        assert _rewrite(src) == f'fetch("{PROXY_PREFIX}/_v{_CACHE_BUSTER}/api/auth/login")'

    def test_api_without_trailing_slash(self):
        """无尾斜杠的 /api（axios baseURL）应被重写--422 bug 的根因"""
        src = 'const r="/api";e.baseURL=r;'
        assert _rewrite(src) == f'const r="{PROXY_PREFIX}/_v{_CACHE_BUSTER}/api";e.baseURL=r;'

    def test_webui_with_trailing_slash(self):
        """带尾斜杠的 /webui/ 路径应被重写"""
        src = '"/webui/assets/index.js"'
        assert _rewrite(src) == f'"{PROXY_PREFIX}/_v{_CACHE_BUSTER}/webui/assets/index.js"'

    def test_webui_without_trailing_slash(self):
        """无尾斜杠的 /webui 应被重写"""
        src = '"/webui"'
        assert _rewrite(src) == f'"{PROXY_PREFIX}/_v{_CACHE_BUSTER}/webui"'

    def test_sse_paths_rewritten(self):
        """SSE 端点路径应被重写"""
        for path in ["/api/base/GetSysStatusRealTime", "/api/Log/GetLogRealTime"]:
            src = f'"{path}"'
            assert _rewrite(src) == f'"{PROXY_PREFIX}/_v{_CACHE_BUSTER}{path}"'

    def test_no_double_rewrite(self):
        """已重写的代理前缀不应被二次重写"""
        already = f'"{PROXY_PREFIX}/_v{_CACHE_BUSTER}/api/auth/login"'
        assert _rewrite(already) == already

    def test_no_double_rewrite_webui(self):
        """已重写的 /webui 代理前缀不应被二次重写"""
        already = f'"{PROXY_PREFIX}/_v{_CACHE_BUSTER}/webui/"'
        assert _rewrite(already) == already

    def test_unrelated_code_untouched(self):
        """不含路径的代码不应被修改"""
        src = "e.baseURL=r;const t=localStorage.getItem(x)"
        assert _rewrite(src) == src

    def test_webui_substring_not_matched(self):
        """/webui_plugin 等子串不应被误匹配"""
        src = '"/webui_plugin"'
        assert _rewrite(src) == src

    def test_files_path_rewritten(self):
        """/files/theme.css 等静态资源路径应被重写"""
        src = 'Fd("/files/theme.css?_t=123")'
        assert _rewrite(src) == f'Fd("{PROXY_PREFIX}/_v{_CACHE_BUSTER}/files/theme.css?_t=123")'

    def test_files_no_double_rewrite(self):
        """已重写的 /files 代理前缀不应被二次重写"""
        already = f'"{PROXY_PREFIX}/_v{_CACHE_BUSTER}/files/theme.css"'
        assert _rewrite(already) == already

    def test_plugin_template_literal(self):
        """插件扩展页面 iframe src（模板字面量）应被重写"""
        src = 'return`/plugin/${e}/page/${l}`'
        result = _rewrite(src)
        assert f"{PROXY_PREFIX}/_v{_CACHE_BUSTER}/plugin" in result

    def test_plugin_string(self):
        """插件路径（字符串字面量）应被重写"""
        src = '"/plugin/some/page"'
        assert _rewrite(src) == f'"{PROXY_PREFIX}/_v{_CACHE_BUSTER}/plugin/some/page"'

    def test_proxy_prefix_plugin_not_matched(self):
        """代理前缀中的 /plugin（/api/plugin/...）不应被误匹配"""
        # /api/plugin 中 /plugin 前是字母 i，不在字符类 ["'`(=\s] 中
        src = f'const x="{PROXY_PREFIX}/_v{_CACHE_BUSTER}/plugin/page"'
        assert _rewrite(src) == src

    def test_both_rules_apply(self):
        """同一段文本中 /api 和 /webui 都应被重写"""
        src = 'const a="/api";const b="/webui/"'
        result = _rewrite(src)
        assert f"{PROXY_PREFIX}/_v{_CACHE_BUSTER}/api" in result
        assert f"{PROXY_PREFIX}/_v{_CACHE_BUSTER}/webui/" in result

    def test_real_napcat_interceptor(self):
        """模拟 NapCat 真实的 axios 拦截器代码"""
        src = (
            'interceptors.request.use(e=>{const r="/api";e.baseURL=r;'
            'const t=localStorage.getItem("token");'
            'return t&&(e.headers.Authorization=`Bearer ${t}`),e})'
        )
        result = _rewrite(src)
        assert 'r="/api"' not in result
        assert f'r="{PROXY_PREFIX}/_v{_CACHE_BUSTER}/api"' in result


class TestVersionStrip:
    """验证 _v 版本段剥离逻辑"""

    def test_strip_version_from_webui(self):
        """_v 版本段应被正确剥离"""
        assert _strip_version("_v123456/webui/") == "webui/"
        assert _strip_version("_v123456/webui/assets/index.js") == "webui/assets/index.js"

    def test_strip_version_from_api(self):
        """_v 版本段从 api 路径剥离"""
        assert _strip_version("_v123456/api/auth/login") == "api/auth/login"

    def test_no_version_prefix(self):
        """无版本段时路径不变"""
        assert _strip_version("webui/") == "webui/"
        assert _strip_version("api/auth/login") == "api/auth/login"


class TestEntryRedirect:
    """验证 entry 重定向 URL 构建"""

    def _entry_url(self, token: str) -> str:
        """模拟 proxy_entry 端点的 URL 构建逻辑"""
        url = f"{PROXY_PREFIX}/_v{_CACHE_BUSTER}/webui/?_t=999"
        if token:
            url += f"&token={token}"
        return url

    def test_entry_with_token(self):
        """有 token 时 entry 跳转 URL 应带版本段+时间戳+token"""
        url = self._entry_url("f700fb2517c4")
        assert f"_v{_CACHE_BUSTER}" in url
        assert "token=f700fb2517c4" in url

    def test_entry_without_token(self):
        """无 token 时 entry 跳转 URL 不带 token"""
        url = self._entry_url("")
        assert f"_v{_CACHE_BUSTER}" in url
        assert "token=" not in url
