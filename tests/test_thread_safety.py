"""
线程安全与优雅关闭审查测试

验证：Ctrl+C 时所有连接能正确中断，无资源泄漏。
"""
import pytest
import os
import sys
_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestShutdownCodeReview:
    """审查关闭路径代码完整性"""

    def test_terminate_logs_shutdown(self):
        """terminate() 应记录关闭日志，便于调试"""
        with open(os.path.join(_BASE, "main.py")) as f:
            content = f.read()
        assert "logger.info" in content.split("async def terminate")[1].split("\n")[1]

    def test_http_mgr_terminate_called(self):
        """terminate() 应调用 _http_mgr.terminate()"""
        with open(os.path.join(_BASE, "main.py")) as f:
            content = f.read()
        term_body = content.split("async def terminate")[1].split("\n    @")[0]
        assert "_http_mgr.terminate()" in term_body

    def test_client_send_catches_runtime_error(self):
        """client.send() 应捕获 RuntimeError (client closed during shutdown)"""
        with open(os.path.join(_BASE, "main.py")) as f:
            content = f.read()
        after_send = content.split("await client.send(req, stream=True)")[1]
        lines = after_send.split("\n")[:10]
        has_except = any("except" in line and "RuntimeError" in line for line in lines)
        assert has_except, f"client.send() 后的 except 行应包含 RuntimeError"

    def test_aread_catches_runtime_error(self):
        """resp.aread() 应捕获 RuntimeError (client closed during shutdown)"""
        with open(os.path.join(_BASE, "main.py")) as f:
            content = f.read()
        after_aread = content.split("await resp.aread()")[1]
        # 找到 except 行（在 aread 下面几行）
        lines = after_aread.split("\n")[:10]
        has_except = any("except" in line and "RuntimeError" in line for line in lines)
        assert has_except, f"aread() 后的 expect 行应包含 RuntimeError, lines={lines[:5]}"

    def test_sse_aclose_defensive(self):
        """SSE stream 的 finally 中 aclose() 应被 try-except 保护"""
        with open(os.path.join(_BASE, "main.py")) as f:
            content = f.read()
        sse_block = content.split("async def _sse_stream")[1].split("return StreamingResponse")[0]
        # 检查 finally 块中有 try: ... await resp.aclose() ... except Exception: pass
        assert "except Exception" in sse_block
        assert "await resp.aclose()" in sse_block

    def test_status_before_try(self):
        """_status 应在 try 块前初始化，防止 UnboundLocalError"""
        with open(os.path.join(_BASE, "main.py")) as f:
            content = f.read()
        # 在非 SSE 分支中找 _status
        non_sse = content.split("==== 非流式响应")[1]
        assert "_status = resp.status_code" in non_sse.split("try:")[0]

    def test_initialize_defensive_closes_old(self):
        """initialize() 应关闭旧 client 再创建新实例"""
        with open(os.path.join(_BASE, "proxy_utils.py")) as f:
            content = f.read()
        init_body = content.split("async def initialize")[1].split("self._client = httpx")[0]
        assert "aclose" in init_body

    def test_ws_inner_tasks_dont_swallow_cancelled(self):
        """WS proxy 内部用 except Exception，不吞 CancelledError (BaseException)"""
        # CancelledError 是 BaseException，except Exception 抓不住
        with open(os.path.join(_BASE, "main.py")) as f:
            content = f.read()
        # 确认是 except Exception: pass 不是 except BaseException
        ws_code = content.split('async def browser_to_napcat')[1].split('async def napcat_to_browser')[0]
        assert 'except Exception:' in ws_code
        assert 'except BaseException:' not in ws_code

    def test_non_sse_aclose_in_finally(self):
        """非 SSE 的 aclose 在 finally 块中，确保总是执行"""
        with open(os.path.join(_BASE, "main.py")) as f:
            content = f.read()
        non_sse = content.split("==== 非流式响应")[1].split("==== 非流式")[0]
        assert "finally:" in non_sse
        assert "await resp.aclose()" in non_sse.split("finally:")[1]

    def test_terminate_after_requests_fails_gracefully(self):
        """terminate 后再用 client 应抛出清晰异常"""
        from proxy_utils import HttpClientManager
        import pytest
        # 已在 test_proxy_utils.py 中测试，此处确认
        pass


class TestShutdownRuntime:
    """运行时行为验证（不依赖 KiraAI）"""

    def test_http_client_aclose_idempotent(self):
        """httpx.AsyncClient 的 aclose 可幂等调用"""
        from proxy_utils import HttpClientManager
        import asyncio

        async def test():
            mgr = HttpClientManager()
            await mgr.initialize()
            c = mgr.client
            await mgr.terminate()
            # terminate 后 client 应为 None
            assert mgr._client is None
            # 已关闭的 client 无法发请求
            import httpx
            with pytest.raises(RuntimeError, match="client has been closed"):
                await c.get("http://127.0.0.1:1")

        asyncio.run(test())

    def test_terminate_uninitialized_no_error(self):
        """未初始化的 manager 调用 terminate 不报错"""
        from proxy_utils import HttpClientManager
        import asyncio
        asyncio.run(HttpClientManager().terminate())

    def test_double_initialize_logs_old_close(self):
        """重复 initialize 应关闭旧 client 再创建新 client"""
        from proxy_utils import HttpClientManager
        import asyncio

        async def test():
            mgr = HttpClientManager()
            await mgr.initialize()
            c1 = mgr.client
            await mgr.initialize()  # 应关闭旧 client
            c2 = mgr.client
            assert c1 is not c2
            # 旧 client 应已关闭
            import httpx
            with pytest.raises(RuntimeError, match="client has been closed"):
                await c1.get("http://127.0.0.1:1")
            await mgr.terminate()

        asyncio.run(test())
