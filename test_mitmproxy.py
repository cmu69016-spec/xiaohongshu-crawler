"""
mitmproxy 基础功能测试脚本
============================
用来验证 mitmproxy 能否正确加载脚本并调用钩子函数。

使用方法：
  mitmdump -s test_mitmproxy.py --listen-port 8888

然后用手机 / 浏览器 / curl 通过该代理发送任意 HTTP 请求，
终端应输出 "[TEST-REQ]" 和 "[TEST-RSP]" 日志。

如果没有任何输出，说明 mitmproxy 脚本加载本身有问题。
"""

import json
import os
import sys
import time

from mitmproxy import http

# ─── class-based addon ──────────────────────────────────

class TestAddon:
    """极简 addon，用于确认钩子是否被触发"""

    def __init__(self):
        self.req_count = 0
        self.rsp_count = 0

    def request(self, flow: http.HTTPFlow):
        self.req_count += 1
        print(
            f"[TEST-REQ #{self.req_count}] "
            f"{flow.request.method} {flow.request.pretty_url[:120]}"
        )

    def response(self, flow: http.HTTPFlow):
        self.rsp_count += 1
        ct = flow.response.headers.get("content-type", "")
        print(
            f"[TEST-RSP #{self.rsp_count}] "
            f"{flow.response.status_code} {flow.request.pretty_url[:120]}  "
            f"content-type={ct}"
        )

        # 如果是 JSON 响应，尝试解析并打印前 200 字符
        if "json" in ct.lower():
            try:
                body = flow.response.text or ""
                data = json.loads(body)
                preview = json.dumps(data, ensure_ascii=False)[:200]
                print(f"  ↳ JSON 预览: {preview}")
            except Exception as exc:
                print(f"  ↳ JSON 解析失败: {exc}")


# ─── module-level 后备 ──────────────────────────────────

_addon = TestAddon()


def request(flow: http.HTTPFlow):
    _addon.request(flow)


def response(flow: http.HTTPFlow):
    _addon.response(flow)


# ─── 注册 addon（推荐方式）────────────────────────────────

addons = [_addon]

# ─── 启动信息 ────────────────────────────────────────────

print("=" * 60)
print("  🧪 mitmproxy 测试脚本已加载")
print(f"  🐍 Python {sys.version}")
print(f"  📍 当前目录：{os.getcwd()}")
print(f"  ⏰ 启动时间：{time.strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 60)
print("  通过代理发送任意请求，如果终端显示")
print("  [TEST-REQ] 和 [TEST-RSP] 则表示钩子正常工作。")
print("=" * 60)
