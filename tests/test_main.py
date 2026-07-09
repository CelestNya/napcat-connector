"""NapCat Connector 插件测试"""


def _build_url(base: str, token: str) -> str:
    """模拟实际 build_url 逻辑"""
    url = base.rstrip("/")
    if not url:
        return url
    if not url.endswith("/webui"):
        url += "/webui"
    if token:
        url += f"?token={token}"
    return url


class TestUrlBuilding:
    """验证 WebUI URL 构建逻辑"""

    def test_url_with_token(self):
        """有 token 时 URL 应为 /webui?token=xxx"""
        url = _build_url("http://192.168.1.100:6099", "my_secret_token")
        assert url == "http://192.168.1.100:6099/webui?token=my_secret_token"

    def test_url_without_token(self):
        """无 token 时 URL 应为 /webui 不带参数"""
        url = _build_url("http://127.0.0.1:6099", "")
        assert url == "http://127.0.0.1:6099/webui"

    def test_url_already_has_webui(self):
        """URL 已经包含 /webui 时不重复追加"""
        url = _build_url("http://napcat.example.com:6099/webui", "abc123")
        assert url == "http://napcat.example.com:6099/webui?token=abc123"

    def test_url_trailing_slash(self):
        """URL 末尾有斜杠时应被去除"""
        url = _build_url("http://napcat.example.com:6099/", "abc123")
        assert url == "http://napcat.example.com:6099/webui?token=abc123"

    def test_url_trailing_webui_slash(self):
        """URL 为 .../webui/ 时应被正确处理"""
        url = _build_url("http://napcat.example.com:6099/webui/", "abc123")
        assert url == "http://napcat.example.com:6099/webui?token=abc123"

    def test_empty_base(self):
        """base 为空时直接返回空字符串"""
        url = _build_url("", "anything")
        assert url == ""
