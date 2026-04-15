"""
小红书手机抓包方案 - 电脑端代理拦截脚本（增强诊断版）
=========================================================
使用步骤：
  1. 电脑安装：pip install mitmproxy
  2. 运行：mitmdump -s xhs_phone_capture.py --listen-port 8888
  3. 手机 WiFi 设置代理：填电脑 IP，端口 8888
  4. 手机浏览器访问 http://mitm.it 安装证书
  5. iOS 还需：设置 -> 通用 -> VPN与设备管理 -> 信任证书
  6. 打开小红书 App 正常浏览即可，数据自动保存到 xhs_captured_data.json

修复要点：
  - 使用 class-based addon（兼容所有 mitmproxy 版本）
  - response() 中添加详细诊断日志
  - _save() / _load_existing() 增加异常捕获
  - 更灵活的 content-type 匹配
"""

import json
import os
import re
import sys
import time
import traceback
from pathlib import Path

from mitmproxy import http

# ────────────────────────── 配置 ──────────────────────────

OUTPUT_FILE = "xhs_captured_data.json"
KEYWORDS_FILTER: list[str] = []

# 小红书相关域名
XHS_DOMAINS = ["xiaohongshu.com", "xhscdn.com"]

# ────────────────────────── 数据结构 ──────────────────────

captured: dict = {
    "posts": [],
    "details": {},
    "comments": {},
    "meta": {
        "start_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "count": {"posts": 0, "details": 0, "comments": 0},
    },
}


# ────────────────────────── 持久化 ────────────────────────

def _load_existing():
    """
    启动时加载已有数据，兼容两种格式：
      正常格式：整个文件是一个 JSON 对象
      损坏格式：每行一个 JSON（误用 append 模式时产生）
    两种都能读，读完后统一重写为正常格式。
    """
    if not Path(OUTPUT_FILE).exists():
        print(f"[启动] 未发现历史文件 {OUTPUT_FILE}，将新建")
        return

    try:
        raw = Path(OUTPUT_FILE).read_text(encoding="utf-8").strip()
    except Exception as exc:
        print(f"[错误] 读取历史文件失败: {exc}")
        return

    if not raw:
        return

    # 先尝试正常格式
    try:
        existing = json.loads(raw)
        if isinstance(existing, dict) and "posts" in existing:
            captured["posts"] = existing.get("posts", [])
            captured["details"] = existing.get("details", {})
            captured["comments"] = existing.get("comments", {})
            print(f"[恢复] 加载历史数据：{len(captured['posts'])} 条笔记")
            return
    except json.JSONDecodeError:
        pass

    # 兼容损坏格式（每行一个 JSON）
    print("[恢复] 检测到旧格式，正在自动修复...")
    seen: set[str] = set()
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict) and "posts" in obj:
                for p in obj.get("posts", []):
                    nid = p.get("note_id")
                    if nid and nid not in seen:
                        captured["posts"].append(p)
                        seen.add(nid)
                captured["details"].update(obj.get("details", {}))
                captured["comments"].update(obj.get("comments", {}))
            elif isinstance(obj, dict) and "note_id" in obj:
                nid = obj["note_id"]
                if nid not in seen:
                    captured["posts"].append(obj)
                    seen.add(nid)
        except json.JSONDecodeError:
            continue

    print(f"[恢复] 修复完成，恢复 {len(captured['posts'])} 条笔记")
    _save()


def _save():
    """
    用覆盖写入（'w' 模式）保存完整 JSON 对象。
    绝对不使用追加模式，确保文件格式始终正确。
    """
    try:
        captured["meta"]["count"] = {
            "posts": len(captured["posts"]),
            "details": len(captured["details"]),
            "comments": len(captured["comments"]),
        }
        captured["meta"]["last_update"] = time.strftime("%Y-%m-%d %H:%M:%S")

        output_path = Path(OUTPUT_FILE)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(captured, f, ensure_ascii=False, indent=2)

        if output_path.exists():
            size = output_path.stat().st_size
            print(f"[保存] 成功 → {output_path.resolve()}  ({size} bytes)")
        else:
            print("[警告] 文件写入后验证失败！")

    except IOError as exc:
        print(f"[错误] 文件写入失败: {exc}")
        print(f"[提示] 检查目录写权限: {os.getcwd()}")
    except Exception as exc:
        print(f"[错误] 保存异常: {exc}")
        traceback.print_exc()


# ────────────────────────── 解析工具 ──────────────────────

def _parse_note_card(card: dict, source: str = "") -> dict | None:
    if not card:
        return None
    note_id = card.get("id") or card.get("note_id") or card.get("noteId", "")
    if not note_id:
        return None
    interact = card.get("interact_info", {}) or card.get("interactInfo", {}) or {}
    return {
        "note_id": note_id,
        "title": card.get("title", "") or card.get("display_title", ""),
        "desc": card.get("desc", ""),
        "type": card.get("type", ""),
        "like": interact.get("liked_count", 0),
        "collect": interact.get("collected_count", 0),
        "comment": interact.get("comment_count", 0),
        "share": interact.get("share_count", 0),
        "author": (card.get("user", {}) or {}).get("nickname", ""),
        "author_id": (card.get("user", {}) or {}).get("user_id", ""),
        "link": f"https://www.xiaohongshu.com/explore/{note_id}",
        "source": source,
        "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


# ────────────────────────── 分类处理 ──────────────────────

def _handle_search(data: dict):
    items = (data.get("data", {}) or {}).get("items", [])
    added = 0
    existing_ids = {p["note_id"] for p in captured["posts"]}
    for item in items:
        card = item.get("note_card") or item.get("noteCard") or item
        parsed = _parse_note_card(card, source="search")
        if parsed and parsed["note_id"] not in existing_ids:
            captured["posts"].append(parsed)
            existing_ids.add(parsed["note_id"])
            added += 1
    if added:
        print(f"[搜索] 新增 {added} 条，累计 {len(captured['posts'])} 条笔记")
        _save()


def _handle_feed(data: dict, note_id: str = ""):
    items = (data.get("data", {}) or {}).get("items", [])
    for item in items:
        card = item.get("note_card", {})
        nid = note_id or card.get("id") or card.get("note_id", "")
        if not nid:
            continue
        desc = card.get("desc", "")
        tags = [t.get("name", "") for t in card.get("tag_list", []) if t.get("name")]
        captured["details"][nid] = {
            "note_id": nid,
            "desc": desc,
            "tags": tags,
            "title": card.get("title", ""),
            "image_list": [img.get("url", "") for img in card.get("image_list", [])],
            "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        print(f"[详情] {nid[:8]}  正文 {len(desc)} 字  标签 {tags[:3]}")
        _save()


def _handle_comments(data: dict, note_id: str = ""):
    comments_raw = (data.get("data", {}) or {}).get("comments", [])
    if not comments_raw:
        return
    comments = []
    for c in comments_raw:
        comments.append({
            "content": c.get("content", ""),
            "like_count": c.get("like_count", 0),
            "author": (c.get("user_info", {}) or {}).get("nickname", "匿名"),
            "author_id": (c.get("user_info", {}) or {}).get("user_id", ""),
            "sub_comments": [
                {
                    "content": sc.get("content", ""),
                    "like_count": sc.get("like_count", 0),
                    "author": (sc.get("user_info", {}) or {}).get("nickname", "匿名"),
                }
                for sc in c.get("sub_comments", [])
            ],
        })
    comments.sort(key=lambda x: x["like_count"], reverse=True)
    if note_id:
        captured["comments"][note_id] = comments
        top = comments[0]["like_count"] if comments else 0
        print(f"[评论] {note_id[:8]}  共 {len(comments)} 条  最高点赞 {top}")
        _save()


# ────────────────────────── mitmproxy class-based addon ───

class XhsCaptureAddon:
    """
    使用 class-based addon，兼容 mitmproxy 5.x / 8.x / 10.x+。
    mitmproxy 加载脚本后会在 addons 列表中查找实例，
    并对每个 HTTP 响应调用 response() 方法。
    """

    def response(self, flow: http.HTTPFlow):
        """mitmproxy 钩子：拦截并解析小红书 API 响应"""
        try:
            url = flow.request.pretty_url

            # ── 诊断：打印所有小红书请求 ──
            if any(d in url for d in XHS_DOMAINS):
                ct = flow.response.headers.get("content-type", "")
                print(f"[拦截] {flow.response.status_code} {url[:120]}  content-type={ct}")

            # 非小红书域名直接跳过
            if not any(d in url for d in XHS_DOMAINS):
                return

            # 检查 content-type（兼容 text/json, application/json 等）
            content_type = flow.response.headers.get("content-type", "").lower()
            if "json" not in content_type:
                return

            # 解析 JSON
            body = flow.response.text or ""
            if not body:
                print(f"[跳过] 响应体为空: {url[:100]}")
                return

            try:
                data = json.loads(body)
            except Exception as exc:
                print(f"[解析错误] {url[:80]}  {exc}")
                return

            # 提取 note_id
            note_id = ""
            m = re.search(r"/(?:explore|item|note)/([a-f0-9]{24})", url)
            if m:
                note_id = m.group(1)
            if not note_id:
                combined = (flow.request.text or "") + url
                m2 = re.search(
                    r'"(?:note_id|source_note_id)"\s*:\s*"([a-f0-9]{24})"',
                    combined,
                )
                if m2:
                    note_id = m2.group(1)

            # 路由到对应处理器
            if any(p in url for p in ["/search/notes", "/search_result"]):
                _handle_search(data)
            elif "/feed" in url or "/note/detail" in url:
                _handle_feed(data, note_id)
            elif "/comment" in url:
                _handle_comments(data, note_id)
            elif "/homefeed" in url:
                _handle_search(data)
            # 其他小红书 JSON 请求不做处理（避免静态资源产生大量日志）

        except Exception as exc:
            print(f"[异常] response() 处理失败: {exc}")
            traceback.print_exc()


# ────────────────────────── 同时保留 module-level 函数 ────
# 作为 class-based addon 的后备方案：
# 如果 mitmproxy 版本不识别 addons 列表，会回退到 module-level 函数。

_addon = XhsCaptureAddon()


def response(flow: http.HTTPFlow):
    """module-level 后备钩子（兼容旧版 mitmproxy）"""
    _addon.response(flow)


# ────────────────────────── 注册 addon ────────────────────
# mitmproxy 8+ 的推荐方式：通过 addons 列表注册
addons = [_addon]

# ────────────────────────── 启动逻辑 ──────────────────────

_load_existing()

print("=" * 60)
print("  🚀 小红书手机抓包代理已启动（增强诊断版）")
print(f"  📁 数据保存至：{os.path.abspath(OUTPUT_FILE)}")
print(f"  📍 当前目录：{os.getcwd()}")
print(f"  🐍 Python {sys.version}")
print("=" * 60)
print("  📱 手机代理设置 → IP: 你的电脑局域网 IP，端口: 8888")
print("  🔒 首次使用请在手机浏览器打开 http://mitm.it 安装证书")
print("  ✅ 打开小红书 App 开始浏览，数据自动保存")
print("=" * 60)
