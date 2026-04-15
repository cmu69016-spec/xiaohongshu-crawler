"""
小红书手机抓包方案 - 电脑端代理拦截脚本
=========================================
使用步骤：
  1. 电脑安装：pip install mitmproxy
  2. 运行：mitmdump -s xhs_phone_capture.py --listen-port 8888
  3. 手机 WiFi 设置代理：填电脑 IP，端口 8888
  4. 手机浏览器访问 http://mitm.it 安装证书
  5. iOS 还需：设置 -> 通用 -> VPN与设备管理 -> 信任证书
  6. 打开小红书 App 正常浏览即可，数据自动保存到 xhs_captured_data.json
"""

import json
import time
import re
from pathlib import Path
from mitmproxy import http

OUTPUT_FILE     = "xhs_captured_data.json"
KEYWORDS_FILTER = []

# 内存数据结构
captured = {
    "posts":    [],
    "details":  {},
    "comments": {},
    "meta": {
        "start_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "count": {"posts": 0, "details": 0, "comments": 0},
    }
}


def _load_existing():
    """
    启动时加载已有数据，兼容两种格式：
      正常格式：整个文件是一个 JSON 对象
      损坏格式：每行一个 JSON（误用 append 模式时产生）
    两种都能读，读完后统一重写为正常格式。
    """
    if not Path(OUTPUT_FILE).exists():
        return
    raw = Path(OUTPUT_FILE).read_text(encoding="utf-8").strip()
    if not raw:
        return

    # 先尝试正常格式
    try:
        existing = json.loads(raw)
        if isinstance(existing, dict) and "posts" in existing:
            captured["posts"]    = existing.get("posts", [])
            captured["details"]  = existing.get("details", {})
            captured["comments"] = existing.get("comments", {})
            print(f"[恢复] 加载历史数据：{len(captured['posts'])} 条笔记")
            return
    except json.JSONDecodeError:
        pass

    # 兼容损坏格式（每行一个 JSON）
    print("[恢复] 检测到旧格式，正在自动修复...")
    seen = set()
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict) and "posts" in obj:
                for p in obj.get("posts", []):
                    if p.get("note_id") not in seen:
                        captured["posts"].append(p)
                        seen.add(p["note_id"])
                captured["details"].update(obj.get("details", {}))
                captured["comments"].update(obj.get("comments", {}))
            elif isinstance(obj, dict) and "note_id" in obj:
                if obj["note_id"] not in seen:
                    captured["posts"].append(obj)
                    seen.add(obj["note_id"])
        except json.JSONDecodeError:
            continue

    print(f"[恢复] 修复完成，恢复 {len(captured['posts'])} 条笔记")
    _save()  # 立刻重写为正常格式


def _save():
    """
    用覆盖写入（'w' 模式）保存完整 JSON 对象。
    绝对不使用追加模式，确保文件格式始终正确。
    """
    captured["meta"]["count"] = {
        "posts":    len(captured["posts"]),
        "details":  len(captured["details"]),
        "comments": len(captured["comments"]),
    }
    captured["meta"]["last_update"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(captured, f, ensure_ascii=False, indent=2)


def _parse_note_card(card: dict, source: str = "") -> dict | None:
    if not card:
        return None
    note_id = card.get("id") or card.get("note_id") or card.get("noteId", "")
    if not note_id:
        return None
    interact = card.get("interact_info", {}) or card.get("interactInfo", {}) or {}
    return {
        "note_id":     note_id,
        "title":       card.get("title", "") or card.get("display_title", ""),
        "desc":        card.get("desc", ""),
        "type":        card.get("type", ""),
        "like":        interact.get("liked_count",    0),
        "collect":     interact.get("collected_count", 0),
        "comment":     interact.get("comment_count",  0),
        "share":       interact.get("share_count",    0),
        "author":      (card.get("user", {}) or {}).get("nickname", ""),
        "author_id":   (card.get("user", {}) or {}).get("user_id", ""),
        "link":        f"https://www.xiaohongshu.com/explore/{note_id}",
        "source":      source,
        "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


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
            "note_id":     nid,
            "desc":        desc,
            "tags":        tags,
            "title":       card.get("title", ""),
            "image_list":  [img.get("url", "") for img in card.get("image_list", [])],
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
            "content":    c.get("content", ""),
            "like_count": c.get("like_count", 0),
            "author":     (c.get("user_info", {}) or {}).get("nickname", "匿名"),
            "author_id":  (c.get("user_info", {}) or {}).get("user_id", ""),
            "sub_comments": [
                {
                    "content":    sc.get("content", ""),
                    "like_count": sc.get("like_count", 0),
                    "author":     (sc.get("user_info", {}) or {}).get("nickname", "匿名"),
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


def response(flow: http.HTTPFlow):
    """mitmproxy 钩子：拦截并解析小红书 API 响应"""
    url = flow.request.pretty_url

    if "xiaohongshu.com" not in url and "xhscdn.com" not in url:
        return
    if "json" not in flow.response.headers.get("content-type", ""):
        return

    try:
        data = json.loads(flow.response.text or "")
    except Exception:
        return

    # 提取 note_id
    note_id = ""
    m = re.search(r'/(?:explore|item|note)/([a-f0-9]{24})', url)
    if m:
        note_id = m.group(1)
    if not note_id:
        req = flow.request.text or ""
        m2 = re.search(r'"(?:note_id|source_note_id)"\s*:\s*"([a-f0-9]{24})"', req + url)
        if m2:
            note_id = m2.group(1)

    if any(p in url for p in ["/search/notes", "/search_result"]):
        _handle_search(data)
    elif "/feed" in url or "/note/detail" in url:
        _handle_feed(data, note_id)
    elif "/comment" in url:
        _handle_comments(data, note_id)
    elif "/homefeed" in url:
        _handle_search(data)


# 启动时加载历史数据
_load_existing()

print("=" * 55)
print("  小红书手机抓包代理已启动")
print(f"  数据保存至：{OUTPUT_FILE}")
print("=" * 55)
print(f"  手机代理设置 → IP: 你的电脑局域网 IP，端口: 8888")
print("  首次使用请在手机浏览器打开 http://mitm.it 安装证书")
print("=" * 55)
