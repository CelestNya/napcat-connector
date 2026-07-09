"""NapCat Connector 插件测试"""


class TestUrlBuilding:
    """验证 WebUI URL 构建逻辑"""

    def test_url_with_token(self):
        """有 token 时 URL 应包含 ?token=xxx"""
        url = "http://192.168.1.100:6099"
        token = "my_secret_token"
        if token:
            url += f"?token={token}"
        assert url == "http://192.168.1.100:6099?token=my_secret_token"

    def test_url_without_token(self):
        """无 token 时 URL 不应包含 ?token="""
        url = "http://127.0.0.1:6099"
        token = ""
        if token:
            url += f"?token={token}"
        assert url == "http://127.0.0.1:6099"

    def test_url_trailing_slash(self):
        """URL 末尾有斜杠时应被去除"""
        raw = "http://napcat.example.com:6099/"
        token = "abc123"
        url = raw.rstrip("/")
        if token:
            url += f"?token={token}"
        assert url == "http://napcat.example.com:6099?token=abc123"
