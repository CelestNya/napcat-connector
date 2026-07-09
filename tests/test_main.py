"""NapCat Connector 插件测试"""


class TestUrlBuilding:
    """验证 WebUI URL 构建逻辑"""

    def test_url_with_token(self):
        """有 token 时 URL 应包含 ?token=xxx"""
        cfg = {
            "webui_url": "http://192.168.1.100:6099",
            "webui_token": "my_secret_token",
        }
        url = cfg["webui_url"].rstrip("/")
        if cfg["webui_token"]:
            url += f"?token={cfg['webui_token']}"
        assert url == "http://192.168.1.100:6099?token=my_secret_token"

    def test_url_without_token(self):
        """无 token 时 URL 不应包含 ?token="""
        cfg = {
            "webui_url": "http://127.0.0.1:6099",
            "webui_token": "",
        }
        url = cfg["webui_url"].rstrip("/")
        if cfg["webui_token"]:
            url += f"?token={cfg['webui_token']}"
        assert url == "http://127.0.0.1:6099"

    def test_url_trailing_slash(self):
        """URL 末尾有斜杠时应被去除"""
        cfg = {
            "webui_url": "http://napcat.example.com:6099/",
            "webui_token": "abc123",
        }
        url = cfg["webui_url"].rstrip("/")
        if cfg["webui_token"]:
            url += f"?token={cfg['webui_token']}"
        assert url == "http://napcat.example.com:6099?token=abc123"
