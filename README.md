# 小红书手机抓包工具

通过 mitmproxy 代理拦截手机上小红书 App 的流量，自动提取笔记数据并保存为 JSON。

## 文件说明

| 文件 | 说明 |
|------|------|
| `xhs_phone_capture.py` | **推荐** 增强诊断版抓包脚本（class-based addon + 详细日志） |
| `xhs_scraper_v4_2_fixed.py` | 原版抓包脚本（已同步修复错误处理） |
| `test_mitmproxy.py` | 测试 mitmproxy 是否能正常加载脚本并触发钩子 |

## 快速开始

### 1. 安装 mitmproxy

```bash
pip install mitmproxy
```

### 2. 启动代理

```bash
# 推荐：使用增强诊断版
mitmdump -s xhs_phone_capture.py --listen-port 8888

# 或使用原版
mitmdump -s xhs_scraper_v4_2_fixed.py --listen-port 8888
```

### 3. 手机配置

1. 确保手机和电脑在同一 WiFi 网络
2. 手机 WiFi 设置 → HTTP 代理 → 手动
   - 服务器：电脑的局域网 IP（终端输入 `ifconfig` 或 `ipconfig` 查看）
   - 端口：`8888`
3. 手机浏览器访问 `http://mitm.it` 安装 CA 证书
4. **iOS 用户**还需：设置 → 通用 → 关于本机 → 证书信任设置 → 启用 mitmproxy 证书

### 4. 开始抓包

打开小红书 App，正常浏览。电脑终端应显示：

```
[拦截] 200 https://edith.xiaohongshu.com/api/...  content-type=application/json
[搜索] 新增 3 条，累计 3 条笔记
[保存] 成功 → /path/to/xhs_captured_data.json  (1234 bytes)
```

数据自动保存到 `xhs_captured_data.json`。

## 故障排查

### 如果脚本没有任何输出

先用测试脚本确认 mitmproxy 工作正常：

```bash
mitmdump -s test_mitmproxy.py --listen-port 8888
```

然后通过代理发送任意请求，终端应显示 `[TEST-REQ]` 和 `[TEST-RSP]`。

### 常见问题

| 问题 | 解决方法 |
|------|---------|
| 手机无法连接代理 | 确认电脑和手机在同一局域网，检查防火墙 |
| HTTPS 请求失败 | 手机访问 `http://mitm.it` 安装证书，iOS 记得信任证书 |
| 有拦截日志但无数据保存 | 检查终端是否有 `[错误]` 提示，检查目录写权限 |
| `response()` 不触发 | 使用 `xhs_phone_capture.py`（class-based addon 更兼容） |
| mitmproxy 版本不兼容 | `pip install --upgrade mitmproxy` |

### 查看详细日志

```bash
mitmdump -s xhs_phone_capture.py --listen-port 8888 -v
```

## 数据格式

`xhs_captured_data.json` 结构：

```json
{
  "posts": [
    {
      "note_id": "...",
      "title": "...",
      "desc": "...",
      "like": 100,
      "collect": 50,
      "comment": 20,
      "author": "...",
      "link": "https://www.xiaohongshu.com/explore/..."
    }
  ],
  "details": { "note_id": { "desc": "...", "tags": [...] } },
  "comments": { "note_id": [{ "content": "...", "like_count": 10 }] },
  "meta": { "count": { "posts": 10 }, "last_update": "2024-01-01 12:00:00" }
}
```

## 环境要求

- Python 3.10+
- mitmproxy 8.0+
- 手机与电脑在同一局域网
