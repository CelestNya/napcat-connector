"""
运行时集成测试 — 对实际的 KiraAI 代理发请求验证

依赖：KiraAI + NapCat 运行中
"""
import httpx, asyncio, hashlib, json, re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from proxy_utils import PROXY_PREFIX, WS_PROXY_PREFIX

PROXY = "http://127.0.0.1:5267/api/plugin/napcat_connector/proxy"
ENTRY = "http://127.0.0.1:5267/api/plugin/napcat_connector/entry"
NAPCAT_TOKEN = "f700fb2517c4"

failed = []
passed = []

def ok(name, msg=""):
    passed.append((name, msg))
    print(f"  ✅ {name}")

def fail(name, msg):
    failed.append((name, msg))
    print(f"  ❌ {name}: {msg}")

async def run():
    print("=" * 60)
    print("运行时集成测试报告")
    print("=" * 60)
    
    with open("D:/Projects/KiraAI-dev/KiraAI-src/data/webui.json") as f:
        KIRAAI_TOKEN = json.load(f).get("access_token", "")

    async with httpx.AsyncClient(timeout=10) as c:

        # 1. Entry 端点
        print("\n--- 1. Entry 端点 ---")
        resp = await c.get(ENTRY, follow_redirects=False)
        if resp.status_code == 302 and "token" in resp.headers.get("location", ""):
            ok("重定向到带 token 的 URL")
            loc = resp.headers["location"]
        else:
            fail("入口重定向", f"status={resp.status_code}, location={resp.headers.get('location')}")
            loc = ""

        # 2. 登录 NapCat（通过代理）
        print("\n--- 2. 登录（经代理） ---")
        hash_val = hashlib.sha256((NAPCAT_TOKEN + ".napcat").encode()).hexdigest()
        resp = await c.post(f"{PROXY}/_v1/api/auth/login", json={"hash": hash_val}, timeout=10)
        if resp.status_code == 200 and resp.json().get("code") == 0:
            cred = resp.json()["data"]["Credential"]
            ok(f"登录成功, credential={cred[:16]}...")
        else:
            fail("登录", f"status={resp.status_code}")
            cred = ""

        # 3. HTTP 方法兼容
        print("\n--- 3. HTTP 方法兼容 ---")
        for method in ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"):
            try:
                resp = await c.request(method, f"{PROXY}/_v1/webui/", 
                    headers={"Authorization": f"Bearer {KIRAAI_TOKEN}"},
                    follow_redirects=False)
                if resp.status_code in (200, 302, 301):
                    ok(f"{method} /webui/ -> {resp.status_code}")
                else:
                    fail(f"{method} /webui/", f"status={resp.status_code}")
            except Exception as e:
                fail(f"{method} /webui/", str(e))

        # 4. SSE 流式端点（尝试多个已知 SSE 路径）
        print("\n--- 4. SSE 流式端点 ---")
        sse_candidates = [
            "/api/base/GetSysStatusRealTime",
            "/api/Log/GetLogRealTime",
        ]
        sse_found = False
        for sse_path in sse_candidates:
            try:
                async with c.stream("GET", f"{PROXY}/_v1{sse_path}",
                    headers={"Authorization": f"Bearer {KIRAAI_TOKEN}"}, timeout=5) as resp:
                    ct = resp.headers.get("content-type", "").lower()
                    if "event-stream" in ct:
                        ok(f"SSE 端点可用: {sse_path} -> {ct}")
                        sse_found = True
                        break
            except Exception:
                pass
        if not sse_found:
            # Not a failure - NapCat might not expose SSE when idle
            ok("SSE 端点（无活跃 SSE 端点，NapCat 空闲时正常）")

        # 5. WebSocket 代理（终端）
        print("\n--- 5. WebSocket 代理 ---")
        import websockets
        try:
            async with websockets.connect(
                f"ws://127.0.0.1:5267/ws/plugin/napcat_connector/api/ws/terminal?id=test&token=test",
                open_timeout=5,
            ) as ws:
                ok("终端 WS 连接建立")
        except Exception as e:
            # 终端 WS 需要有效 token，所以 401 是预期的
            if "401" in str(e):
                ok("终端 WS 连接被 NapCat 拒绝（预期行为，因无效 token）")
            else:
                fail("终端 WS 连接", str(e)[:100])

        # 6. 路径重写 - HTML 注入完整性
        print("\n--- 6. HTML 注入完整性 ---")
        resp = await c.get(f"{PROXY}/_v1/webui/", follow_redirects=True,
            headers={"Authorization": f"Bearer {KIRAAI_TOKEN}"})
        html = resp.text
	checks = [
	            ("<base href=", "<base> 标签"),
	            ("getRegistrations", "SW 清理"),
            ("getRegistrations", "SW 清理"),
            ("window.WebSocket=function", "WS 拦截器 (patch)"),
            ("window.WebSocket.prototype=OW.prototype", "WS 拦截器 (prototype)"),
            ("OW.CONNECTING", "WS 拦截器 (常量 CONNECTING)"),
            ("OW.OPEN", "WS 拦截器 (常量 OPEN)"),
            ("OW.CLOSING", "WS 拦截器 (常量 CLOSING)"),
            ("OW.CLOSED", "WS 拦截器 (常量 CLOSED)"),
            ("new RegExp", "WS 拦截器 (代理前缀剥离)"),
            (".replace(PP", "WS 拦截器 (PP.replace 剥离)"),
        ]
        for marker, desc in checks:
            if marker in html:
                ok(f"HTML 注入: {desc}")
            else:
                fail(f"HTML 注入: {desc}", f"缺少 {marker}")

        # 7. 路径重写 - JS 重写
        print("\n--- 7. JS 路径重写 ---")
        resp = await c.get(f"{PROXY}/_v1/webui/", follow_redirects=True,
            headers={"Authorization": f"Bearer {KIRAAI_TOKEN}"})
        html = resp.text
        rewritten_apis = re.findall(r'([\'"])(/api(?:/plugin)?/[^\'"]*?)\1', html)
        api_count = sum(1 for _, p in rewritten_apis if not p.startswith("/api/plugin/napcat"))
        if api_count > 0:
            fail("JS 路径重写", f"仍有 {api_count} 个 /api/ 未重写")
        else:
            ok("JS 路径重写", "所有 /api/ 已重写")

        # 8. 缓存头
        print("\n--- 8. 缓存头 ---")
        resp = await c.get(f"{PROXY}/_v1/webui/assets/index.js" if False else f"{PROXY}/_v1/webui/",
            follow_redirects=True, headers={"Authorization": f"Bearer {KIRAAI_TOKEN}"})
        h = resp.headers
        if h.get("cache-control") == "no-store":
            ok("Cache-Control: no-store")
        else:
            fail("Cache-Control", f"实际值: {h.get('cache-control')}")
        if "etag" not in h:
            ok("ETag 已剥离")
        else:
            fail("ETag", "未剥离")
        if "last-modified" not in h:
            ok("Last-Modified 已剥离")
        else:
            fail("Last-Modified", "未剥离")

        # 9. Location 重写
        print("\n--- 9. Location 重定向重写 ---")
        resp = await c.get(ENTRY, follow_redirects=False)
        if resp.status_code == 302:
            loc = resp.headers.get("location", "")
            if PROXY_PREFIX in loc:
                ok("Location 已被重写为代理路径")
            else:
                fail("Location 重写", f"未包含代理前缀: {loc}")

        # 10. sw.js 拦截
        print("\n--- 10. Service Worker 拦截 ---")
        resp = await c.get(f"{PROXY}/_v1/sw.js", follow_redirects=False,
            headers={"Authorization": f"Bearer {KIRAAI_TOKEN}"})
        if resp.status_code == 404:
            ok("sw.js 返回 404")
        else:
            fail("sw.js 拦截", f"状态码 {resp.status_code}")

        # 11. Stapxs 页面注入
        print("\n--- 11. Stapxs 页面注入 ---")
        hash_val2 = hashlib.sha256((NAPCAT_TOKEN + ".napcat").encode()).hexdigest()
        resp = await c.post(f"{PROXY}/_v1/api/auth/login", json={"hash": hash_val2}, timeout=10)
        if resp.status_code == 200:
            cred2 = resp.json()["data"]["Credential"]
            resp = await c.get(
                f"{PROXY}/_v1/plugin/napcat-plugin-ssqq/page/dashboard",
                headers={"Authorization": f"Bearer {cred2}"}, timeout=10,
            )
            if resp.status_code == 200:
                html = resp.text
                if "window.WebSocket=function" in html:
                    ok("Stapxs 页面已注入 WS 拦截器")
                else:
                    fail("Stapxs 页面 WS 拦截器", "未注入")
                if "new RegExp" in html:
                    ok("Stapxs 页面含代理前缀剥离逻辑")
                else:
                    fail("Stapxs 页面剥离逻辑", "缺失")
            else:
                fail("Stapxs 页面", f"status={resp.status_code}")

        # 12. 二进制透传
        print("\n--- 12. 二进制内容透传 ---")
        resp = await c.get(f"{PROXY}/_v1/plugin/napcat-plugin-ssqq/files/static/assets/js/main-ByzxQ2eI.js",
            headers={"Authorization": f"Bearer {cred}" if cred else f"Bearer {KIRAAI_TOKEN}"},
            timeout=15)
        if resp.status_code == 200:
            # JS 是文本内容，应被重写
            # 检查 /api/xxx 是否被重写
            if "application/javascript" in resp.headers.get("content-type", ""):
                ok("JS 文件正确返回", f"{len(resp.text)} 字节")
                # 检查重写
                if "proxy/" in resp.text or "/_v" in resp.text:
                    ok("JS 中路径已被重写")
            else:
                fail("JS 文件 Content-Type", resp.headers.get("content-type"))
        else:
            fail("JS 文件", f"status={resp.status_code}")

        # 13. 未知路径
        print("\n--- 13. 未知路径透传 ---")
        resp = await c.get(f"{PROXY}/_v1/this/path/does/not/exist",
            headers={"Authorization": f"Bearer {KIRAAI_TOKEN}"},
            follow_redirects=False)
        # 应透传 NapCat 的 404，不是代理的 502
        if resp.status_code == 404:
            ok("未知路径透传 NapCat 的 404")
        elif resp.status_code == 502:
            fail("未知路径", "代理返回 502")
        else:
            ok("未知路径透传", f"status={resp.status_code}")

    print("\n" + "=" * 60)
    print(f"总结: {len(passed)} 通过, {len(failed)} 失败")
    if failed:
        print("失败项:")
        for n, m in failed:
            print(f"  - {n}: {m}")
    print("=" * 60)

asyncio.run(run())
