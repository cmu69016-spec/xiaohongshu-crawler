"""
小红书学术数据采集工具  v4.2
================================
新增：
  - 优先使用 PC 已登录页面抓取详情全文，移动端 H5 仅作为兜底
  - DeepSeek API 深度分析
  - 分析结果写入 HTML 报告

依赖：pip install selenium webdriver-manager undetected-chromedriver pandas requests
DeepSeek API Key 申请：
  https://platform.deepseek.com/api_keys
"""

import time, random, sys, re, pickle, json, hashlib, subprocess, requests, html
import pandas as pd
from datetime import datetime
from pathlib import Path

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException,
    StaleElementReferenceException, WebDriverException,
)

try:
    import undetected_chromedriver as uc
    USE_UC = True
except ImportError:
    USE_UC = False
    print("建议：pip install undetected-chromedriver")


# =========================================================
# 全局配置
# =========================================================
XHS_HOME       = "https://www.xiaohongshu.com"
XHS_EXPLORE_URL = "https://www.xiaohongshu.com/explore"
XHS_SEARCH_URL = "https://www.xiaohongshu.com/search_result?keyword={kw}&type=51&sort=hot"
SCRIPT_DIR     = Path(__file__).resolve().parent
COOKIE_FILE    = SCRIPT_DIR / "xhs_cookies.pkl"
CONFIG_FILE    = SCRIPT_DIR / "xhs_config.json"

LOGIN_TIMEOUT     = 120
TARGET_POSTS      = 100
MAX_COMMENTS      = 10
MAX_SCROLL_ROUNDS = 30

# DeepSeek API（OpenAI-compatible Chat Completions）
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"

# ---- 移动端 UA：让小红书走手机渲染路径，绕过"扫码才能看"限制 ----
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.0 Mobile/15E148 Safari/604.1"
)

# ---- XPath 选择器 ----
SEL = {
    "search_input": [
        '//input[@placeholder="搜索"]',
        '//input[contains(@class,"search-input")]',
        '//input[@type="search"]',
        '//input[contains(@class,"input")]',
    ],
    # PC 版小红书搜索结果的笔记卡片容器（多版本备用）
    "note_items": [
        '//div[contains(@class,"note-item")]',
        '//section[contains(@class,"note-item")]',
        '//div[@id="search-notes-feed"]//section',
        '//div[contains(@class,"search-feed")]//div[contains(@class,"note")]',
        '//div[contains(@class,"feeds-page")]//div[contains(@class,"cover")]/..',
        # 新版 PC DOM 结构
        '//div[contains(@class,"masonry")]//section',
        '//div[contains(@class,"masonry")]//div[@class and .//a[@href]]',
        '//section[contains(@class,"search")]',
        '//div[contains(@class,"card-container")]',
        '//div[@data-v]//section[.//a[@href]]',
        # 兜底：页面上所有包含链接的 section
        '//main//section[.//a[contains(@href,"xiaohongshu")]]',
    ],
    "title": [
        './/span[contains(@class,"title")]',
        './/p[contains(@class,"desc")]',
        './/div[contains(@class,"title")]',
        './/a[contains(@class,"title")]',
        './/span[contains(@class,"note-title")]',
        './/footer//span',
        './/div[contains(@class,"footer")]//span',
    ],
    "like_count": [
        './/span[contains(@class,"like-wrapper")]//span[contains(@class,"count")]',
        './/div[contains(@class,"like")]//span[contains(@class,"count")]',
        './/span[contains(@class,"likes-count")]',
        './/span[contains(@class,"like-count")]',
        './/div[contains(@class,"interact")]//span[1]',
    ],
    "collect_count": [
        './/span[contains(@class,"collect-wrapper")]//span[contains(@class,"count")]',
        './/div[contains(@class,"collect")]//span[contains(@class,"count")]',
        './/span[contains(@class,"collect-count")]',
        './/div[contains(@class,"interact")]//span[2]',
    ],
    "comment_count": [
        './/span[contains(@class,"chat-wrapper")]//span[contains(@class,"count")]',
        './/div[contains(@class,"comment")]//span[contains(@class,"count")]',
        './/span[contains(@class,"comment-count")]',
        './/div[contains(@class,"interact")]//span[3]',
    ],
    # ---- 详情页：笔记正文 ----
    "note_body": [
        '//*[@id="detail-desc"]//*[contains(@class,"note-text")]',
        '//*[@id="detail-desc"]',
        '//div[contains(@class,"note-content")]//*[contains(@class,"note-text")]',
        '//div[contains(@class,"note-content")]//span[contains(@class,"note-text")]',
        '//div[contains(@class,"note-content")]',
        '//div[contains(@class,"note-detail")]//div[contains(@class,"desc")]',
        '//div[contains(@id,"detail-desc")]',
        '//div[contains(@class,"desc")]//span',
        '//div[contains(@class,"content")]//p',
        '//article//p',
    ],
    # ---- 详情页：评论 ----
    "comment_items": [
        '//div[contains(@class,"comment-item")]',
        '//div[contains(@class,"commentItem")]',
        '//li[contains(@class,"comment")]',
    ],
    "comment_text": [
        './/span[contains(@class,"content")]',
        './/p[contains(@class,"content")]',
        './/div[contains(@class,"comment-content")]',
    ],
    "comment_like": [
        './/span[contains(@class,"like-count")]',
        './/span[contains(@class,"count")]',
        './/div[contains(@class,"like")]//span',
    ],
    "comment_author": [
        './/span[contains(@class,"author")]',
        './/a[contains(@class,"author")]',
        './/div[contains(@class,"user-info")]//span',
    ],
}


# =========================================================
# 工具函数
# =========================================================

def random_sleep(lo=2.0, hi=5.0):
    time.sleep(random.uniform(lo, hi))

def parse_number(text):
    if not text:
        return 0.0
    text = text.strip().replace(",", "")
    try:
        if "万" in text:
            return float(text.replace("万", "")) * 10000
        if text.lower().endswith("k"):
            return float(text[:-1]) * 1000
        return float(text)
    except ValueError:
        return 0.0

def find_el(root, xpaths):
    for xp in xpaths:
        try:
            el = root.find_element(By.XPATH, xp)
            if el:
                return el, xp
        except (NoSuchElementException, StaleElementReferenceException):
            continue
    return None, None

def find_els(root, xpaths):
    best, best_xp = [], None
    for xp in xpaths:
        try:
            els = root.find_elements(By.XPATH, xp)
            if len(els) > len(best):
                best, best_xp = els, xp
        except Exception:
            continue
    if best_xp:
        print(f"    [XPath] {best_xp} -> {len(best)} 个元素")
    return best

def uid_of(title, href):
    return hashlib.md5((title + href).encode()).hexdigest()

def load_config():
    if Path(CONFIG_FILE).exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def _clean_text(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), text)
    text = text.replace("\\n", "\n").replace("\\/", "/")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# =========================================================
# 浏览器初始化
# =========================================================

def detect_chrome_version():
    bins = {
        "darwin": ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"],
        "win32":  [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                   r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"],
        "linux":  ["google-chrome", "chromium-browser"],
    }
    for cmd in bins.get(sys.platform, ["google-chrome"]):
        try:
            out = subprocess.check_output(
                [cmd, "--version"], stderr=subprocess.DEVNULL, timeout=5
            ).decode()
            m = re.search(r"(\d+)\.", out)
            if m:
                v = int(m.group(1))
                print(f"  Chrome 版本：{v}")
                return v
        except Exception:
            continue
    return None


def _resolve_chromedriver_path(cfg: dict) -> str | None:
    """
    按优先级查找可用的 ChromeDriver 路径：
      1. 用户手动指定并保存在 config 里的路径
      2. webdriver-manager 自动管理的本地缓存
    找到后验证文件存在且可执行，返回路径；找不到返回 None。
    """
    # 优先：用户手动指定
    saved = cfg.get("chromedriver_path", "")
    if saved and Path(saved).exists():
        print(f"  使用已保存的 ChromeDriver：{saved}")
        return saved

    # 次选：webdriver-manager 本地缓存
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        print("  正在获取本地 ChromeDriver（首次需联网下载，约数秒）...")
        path = ChromeDriverManager().install()
        if Path(path).exists():
            print(f"  ChromeDriver 路径：{path}")
            return path
    except Exception as e:
        print(f"  webdriver-manager 获取失败：{e}")

    return None


def init_driver(cfg: dict | None = None):
    """
    启动浏览器，三级降级策略。

    根本修复：
    ① 接收 cfg 参数，优先使用用户手动指定的 ChromeDriver 路径，
      解决 Mac ARM 上 webdriver-manager 下载的驱动 status -9 问题。
    ② 窗口尺寸改为 PC（1280x800），搜索列表页用 PC 版 DOM，
      XPath 选择器才能正确命中笔记卡片。
      （移动端模拟仅在进入详情页时动态开启，见 set_mobile_mode）
    ③ 不在启动时全局注入移动端 UA，避免搜索页加载手机版布局。
    """
    if cfg is None:
        cfg = load_config()
    chrome_ver = detect_chrome_version()
    driver_path = _resolve_chromedriver_path(cfg)

    # ---------- PC 尺寸 Options（搜索列表页使用）----------
    def _make_opts(use_uc: bool):
        if use_uc:
            opts = uc.ChromeOptions()
        else:
            from selenium import webdriver as _wd
            opts = _wd.ChromeOptions()
            opts.add_experimental_option("excludeSwitches", ["enable-automation"])
            opts.add_experimental_option("useAutomationExtension", False)
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument("--window-size=1280,800")   # PC 尺寸，搜索列表 DOM 正常
        opts.add_argument("--lang=zh-CN")
        # 使用普通桌面 UA，确保搜索结果页走 PC 版渲染
        opts.add_argument(
            "user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
        return opts

    driver = None

    # 策略 1：uc + 指定本地 ChromeDriver 路径（跳过 uc 联网下载）
    if USE_UC and driver_path:
        try:
            # macOS Gatekeeper 会拦截未授权的二进制文件（status -9 = SIGKILL）
            # 用 xattr 解除隔离标记，确保 chromedriver 可以正常执行
            if sys.platform == "darwin":
                try:
                    subprocess.run(
                        ["xattr", "-d", "com.apple.quarantine", driver_path],
                        capture_output=True, timeout=5
                    )
                    # 顺便确保有执行权限
                    subprocess.run(["chmod", "+x", driver_path],
                                   capture_output=True, timeout=5)
                except Exception:
                    pass   # xattr 失败不影响继续尝试
            opts = _make_opts(use_uc=True)
            kw = {"options": opts, "driver_executable_path": driver_path}
            if chrome_ver:
                kw["version_main"] = chrome_ver
            driver = uc.Chrome(**kw)
            print("  启动方式：undetected-chromedriver + 指定驱动（策略 1）")
        except Exception as e:
            print(f"  策略 1 失败：{e}")

    # 策略 2：uc 不指定路径，让它自己找
    if driver is None and USE_UC:
        try:
            opts = _make_opts(use_uc=True)
            kw = {"options": opts}
            if chrome_ver:
                kw["version_main"] = chrome_ver
            driver = uc.Chrome(**kw)
            print("  启动方式：undetected-chromedriver 自动（策略 2）")
        except Exception as e:
            print(f"  策略 2 失败：{e}")

    # 策略 3：纯 selenium（最终兜底）
    if driver is None:
        print("  降级到纯 selenium 模式（策略 3）...")
        from selenium import webdriver as _wd
        from selenium.webdriver.chrome.service import Service
        opts = _make_opts(use_uc=False)
        if driver_path:
            from selenium.webdriver.chrome.service import Service
            driver = _wd.Chrome(service=Service(driver_path), options=opts)
        else:
            from webdriver_manager.chrome import ChromeDriverManager
            from selenium.webdriver.chrome.service import Service
            driver = _wd.Chrome(
                service=Service(ChromeDriverManager().install()), options=opts
            )
        print("  启动方式：selenium（策略 3）")

    if driver is None:
        raise RuntimeError("三种启动策略均失败，请检查 Chrome 安装及 ChromeDriver 路径")

    # 隐藏自动化特征（所有策略共用）
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": """
        Object.defineProperty(navigator, 'webdriver',  { get: () => undefined });
        Object.defineProperty(navigator, 'plugins',    { get: () => [1,2,3,4,5] });
        Object.defineProperty(navigator, 'languages',  { get: () => ['zh-CN','zh','en'] });
        window.chrome = { runtime: {} };
    """})
    return driver


def set_mobile_mode(driver, enable: bool):
    """
    动态切换移动端模拟。
    enable=True：进入详情页前调用，让小红书走手机渲染路径（可看正文）
    enable=False：返回搜索列表页前调用，恢复 PC 模式（XPath 选择器正常工作）
    """
    if enable:
        driver.execute_cdp_cmd("Network.setUserAgentOverride", {
            "userAgent": MOBILE_UA,
            "platform": "iPhone",
        })
        driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {
            "width": 390, "height": 844,
            "deviceScaleFactor": 3,
            "mobile": True,
        })
    else:
        driver.execute_cdp_cmd("Network.setUserAgentOverride", {
            "userAgent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "platform": "MacIntel",
        })
        driver.execute_cdp_cmd("Emulation.clearDeviceMetricsOverride", {})




# =========================================================
# 登录管理（多重检测，不依赖单一 XPath）
# =========================================================

def _is_logged_in(driver):
    """
    三重条件判断登录状态：
    1. URL 不含登录页关键字
    2. Cookie 中存在登录态字段（web_session / a1）
    3. 页面上无可见登录弹窗
    """
    if any(k in driver.current_url for k in ["/login", "/signin", "sso.xhs"]):
        return False
    cookies = {c["name"]: c["value"] for c in driver.get_cookies()}
    if not any(k in cookies for k in ["web_session", "a1", "customer-sso-sid"]):
        return False
    try:
        modal = driver.find_element(
            By.XPATH, '//div[contains(@class,"login") and contains(@class,"modal")]'
        )
        if modal.is_displayed():
            return False
    except NoSuchElementException:
        pass
    return True


def save_cookies(driver):
    """把当前浏览器 Cookie 序列化保存，下次直接复用"""
    with open(COOKIE_FILE, "wb") as f:
        pickle.dump(driver.get_cookies(), f)
    print(f"  Cookie 已保存 -> {COOKIE_FILE}")


# ---- Cookie 手动导入 ----------------------------------------

def parse_cookie_string(raw: str) -> dict:
    """
    解析从浏览器 DevTools 复制来的 Cookie 字符串。
    支持两种格式：
      格式 A（Request Header 格式）：
        a1=abc123; web_session=xyz; foo=bar
      格式 B（逐行 key=value，用换行分隔）：
        a1=abc123
        web_session=xyz
    返回 {name: value} 字典。
    """
    result = {}
    # 统一换行符，再按分号或换行切分
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    # 如果包含换行，按行切；否则按分号切
    sep = "\n" if "\n" in raw else ";"
    for part in raw.split(sep):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, _, val = part.partition("=")
        key = key.strip()
        val = val.strip()
        if key:
            result[key] = val
    return result


def inject_cookie_string(driver, cookie_str: str) -> bool:
    """
    把手动粘贴的 Cookie 字符串注入浏览器，然后刷新验证登录状态。
    成功返回 True 并持久化保存；失败返回 False。
    """
    parsed = parse_cookie_string(cookie_str)
    if not parsed:
        print("  ✗ 解析失败：未找到任何 key=value 对，请检查格式")
        return False

    print(f"  解析到 {len(parsed)} 个 Cookie 字段：{', '.join(parsed.keys())}")

    # 先导航到目标域，才能写入该域的 Cookie
    driver.get(XHS_HOME)
    random_sleep(2, 3)

    injected = 0
    for name, value in parsed.items():
        try:
            driver.add_cookie({
                "name":   name,
                "value":  value,
                "domain": ".xiaohongshu.com",
                "path":   "/",
            })
            injected += 1
        except Exception as e:
            print(f"    跳过 {name}：{e}")

    print(f"  成功注入 {injected} 个字段，刷新验证...")
    driver.refresh()
    random_sleep(3, 5)

    if _is_logged_in(driver):
        print("  ✓ Cookie 导入成功，已登录！")
        save_cookies(driver)          # 同时保存为 pkl，下次自动复用
        return True
    else:
        print("  ✗ 注入后仍未检测到登录态")
        print("    常见原因：web_session 或 a1 字段缺失 / 已过期")
        return False


def import_cookie_interactively(driver) -> bool:
    """
    交互式 Cookie 导入向导。
    打印详细的操作步骤，引导用户从浏览器复制 Cookie 并粘贴。
    """
    print("\n" + "=" * 60)
    print("  📋  Cookie 手动导入向导")
    print("=" * 60)
    print("""
  操作步骤：
  ① 用 Chrome / Safari 打开 https://www.xiaohongshu.com
     并确保已登录（如未登录请先完成登录）

  ② 打开开发者工具：
     · Mac：Cmd + Option + I
     · Windows：F12 或 Ctrl + Shift + I

  ③ 切换到「Application（应用程序）」标签
     → 左侧展开「Cookies」→ 点击 https://www.xiaohongshu.com

  ④ 找到以下两个关键字段（必须有）：
     · web_session   ← 最重要，标识登录会话
     · a1            ← 设备指纹

  ⑤ 复制方式（二选一）：

     【方式 A · 推荐】在「Network」标签随便点一个请求
       → 右侧 Headers → Request Headers → 找到「cookie:」那行
       → 右键复制整行的值（格式：a1=xxx; web_session=yyy; ...）

     【方式 B】在「Application → Cookies」逐行复制，
       每行格式：字段名=字段值
       （只需复制 web_session 和 a1 两行也能工作）

  ⑥ 在下方提示符处粘贴，输入完毕后按两次回车确认
""")
    print("-" * 60)
    print("  请粘贴 Cookie（粘贴后连按两次回车）：")

    lines = []
    try:
        while True:
            line = input()
            if line == "" and lines and lines[-1] == "":
                break          # 连续两个空行 = 结束输入
            lines.append(line)
    except EOFError:
        pass

    raw = "\n".join(lines).strip()
    if not raw:
        print("  未输入任何内容，跳过导入")
        return False

    return inject_cookie_string(driver, raw)


# ---- 自动 pkl Cookie 加载 -----------------------------------

def load_cookies(driver) -> bool:
    """尝试加载上次保存的 pkl Cookie 文件"""
    if not Path(COOKIE_FILE).exists():
        return False
    driver.get(XHS_HOME)
    random_sleep(2, 3)
    for c in pickle.load(open(COOKIE_FILE, "rb")):
        c.pop("expiry", None)
        c.pop("sameSite", None)
        try:
            driver.add_cookie(c)
        except Exception:
            pass
    driver.refresh()
    random_sleep(3, 5)
    ok = _is_logged_in(driver)
    print("  ✓ Cookie 文件登录成功" if ok else "  Cookie 文件已过期")
    return ok


# ---- 扫码登录（保留作为最后兜底）--------------------------

def manual_login(driver) -> bool:
    """引导用户在浏览器里扫码/验证码登录"""
    driver.get(XHS_HOME)
    random_sleep(2, 3)
    print("\n" + "=" * 55)
    print("  请在浏览器中完成登录（微信扫码 / 验证码均可）")
    print(f"  最长等待 {LOGIN_TIMEOUT} 秒，成功后自动继续")
    print("=" * 55)
    deadline = time.time() + LOGIN_TIMEOUT
    while time.time() < deadline:
        time.sleep(2)
        try:
            if _is_logged_in(driver):
                print("\n  登录成功！")
                save_cookies(driver)
                cfg = load_config()
                cfg["login_method"] = "cookie"
                save_config(cfg)
                return True
        except WebDriverException:
            pass
        remaining = int(deadline - time.time())
        if remaining > 0 and remaining % 20 == 0:
            print(f"  等待中，剩余 {remaining} 秒...")
    print("  登录超时")
    return False


# ---- 登录总入口 --------------------------------------------

def ensure_login(driver) -> bool:
    """
    登录优先级：
      1. 自动加载已保存的 pkl Cookie（最快）
      2. 手动粘贴 Cookie 字符串（适合从浏览器/App 复制）
      3. 扫码/验证码登录（兜底）
    """
    # 优先级 1：pkl 文件
    if load_cookies(driver):
        return True

    # 优先级 2 & 3：询问用户
    print("\n  Cookie 文件不可用，请选择登录方式：")
    print("  [1] 粘贴浏览器 Cookie（推荐，从 DevTools 复制）")
    print("  [2] 扫码 / 验证码登录（在弹出浏览器中操作）")
    choice = input("  请输入 1 或 2（默认 1）：").strip()

    if choice == "2":
        return manual_login(driver)
    else:
        # 先运行导入向导
        if import_cookie_interactively(driver):
            return True
        # 粘贴失败，再问要不要扫码
        fallback = input("\n  Cookie 导入失败，是否改用扫码登录？(y/N)：").strip().lower()
        if fallback == "y":
            return manual_login(driver)
        return False


# =========================================================
# 搜索
# =========================================================

def _sniff_note_selector(driver) -> str | None:
    """
    实时嗅探当前页面的笔记卡片容器。
    小红书 DOM 结构经常更新，通过遍历页面上所有元素，
    找到数量最多且包含链接的那组候选，返回其 XPath。
    """
    # 候选规则：元素本身或子元素包含 xiaohongshu 链接，且数量 >= 3
    candidates = [
        '//section[.//a[contains(@href,"xiaohongshu")]]',
        '//div[contains(@class,"note")][.//a]',
        '//div[contains(@class,"card")][.//a[contains(@href,"explore")]]',
        '//li[.//a[contains(@href,"explore")]]',
        # 通用兜底：页面主体内任何包含笔记链接的块级元素
        '//main//section',
        '//div[@id and .//a[contains(@href,"explore")]]',
        # Vue 组件根节点（小红书前端框架特征）
        '//div[@data-v-app]//section',
        '//*[@class and contains(@class,"note") and .//a]',
    ]
    best_xp, best_count = None, 0
    for xp in candidates:
        try:
            els = driver.find_elements(By.XPATH, xp)
            if len(els) > best_count:
                best_count, best_xp = len(els), xp
        except Exception:
            continue
    if best_xp and best_count >= 2:
        print(f"  [嗅探] 命中：{best_xp}（{best_count} 个元素）")
        return best_xp
    return None


def search_keyword(driver, keyword):
    """
    搜索关键词并等待结果加载。
    修复：加载成功后立即嗅探实际 DOM 结构，把命中的 XPath
    动态追加到 SEL["note_items"] 最前面，保证后续采集能用上。
    """
    print(f"\n搜索：{keyword}")
    driver.get(XHS_SEARCH_URL.format(kw=keyword))
    random_sleep(3, 6)

    print(f"  页面标题：{driver.title}")

    # ① 先用预设选择器尝试
    loaded_xp = None
    for xp in SEL["note_items"]:
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, xp))
            )
            loaded_xp = xp
            print(f"  预设选择器命中：{xp[:60]}")
            break
        except TimeoutException:
            continue

    # ② 预设全部超时 → 实时嗅探
    if not loaded_xp:
        print("  预设选择器全部超时，启动实时 DOM 嗅探...")
        random_sleep(2, 4)   # 再等一会，让 JS 渲染完成
        loaded_xp = _sniff_note_selector(driver)
        if loaded_xp and loaded_xp not in SEL["note_items"]:
            SEL["note_items"].insert(0, loaded_xp)   # 动态写入，后续采集直接用

    # ③ 还是没找到 → 打印源码片段 + 尝试搜索框
    if not loaded_xp:
        print("  嗅探也未命中，打印页面源码片段供调试：")
        try:
            src = driver.page_source
            # 找 class 属性里含 note/card/feed 的标签，帮助定位正确选择器
            import re as _re
            hits = _re.findall(r'class="([^"]*(?:note|card|feed|search)[^"]*)"', src)
            unique = list(dict.fromkeys(hits))[:15]
            print(f"  含关键字的 class 值（前15个）：{unique}")
        except Exception:
            pass
        # 尝试搜索框
        box, _ = find_el(driver, SEL["search_input"])
        if box:
            print("  改用搜索框重试...")
            box.click(); random_sleep(0.3, 0.6); box.clear()
            for ch in keyword:
                box.send_keys(ch); time.sleep(random.uniform(0.05, 0.15))
            box.send_keys(Keys.RETURN)
            random_sleep(3, 5)
            # 搜索框提交后再嗅探一次
            sniffed = _sniff_note_selector(driver)
            if sniffed and sniffed not in SEL["note_items"]:
                SEL["note_items"].insert(0, sniffed)
        else:
            print("  搜索框也未找到，请检查登录状态或网络")


# =========================================================
# 边滚边抓笔记列表
# =========================================================

def _extract_post(el):
    try:
        title_el, _ = find_el(el, SEL["title"])
        title = title_el.text.strip() if title_el else el.text.split("\n")[0].strip()
        if not title:
            return None
        like_el,    _ = find_el(el, SEL["like_count"])
        collect_el, _ = find_el(el, SEL["collect_count"])
        comment_el, _ = find_el(el, SEL["comment_count"])
        raw_like    = like_el.text.strip()    if like_el    else ""
        raw_collect = collect_el.text.strip() if collect_el else ""
        raw_comment = comment_el.text.strip() if comment_el else ""
        try:
            href = el.find_element(By.XPATH, './/a[@href]').get_attribute("href") or ""
        except NoSuchElementException:
            href = ""
        return {
            "uid": uid_of(title, href), "title": title, "link": href,
            "like": parse_number(raw_like),
            "collect": parse_number(raw_collect),
            "comment": parse_number(raw_comment),
            "raw_like": raw_like, "raw_collect": raw_collect, "raw_comment": raw_comment,
        }
    except Exception:
        return None

def _harvest_visible(driver, seen, results):
    """
    采集当前视口内可见的笔记。
    若预设选择器全部返回空，自动触发一次 DOM 嗅探并更新选择器列表。
    """
    items = find_els(driver, SEL["note_items"])

    # 预设全部为空时，嗅探一次
    if not items:
        sniffed = _sniff_note_selector(driver)
        if sniffed:
            if sniffed not in SEL["note_items"]:
                SEL["note_items"].insert(0, sniffed)
            items = driver.find_elements(By.XPATH, sniffed)

    added = 0
    for el in items:
        try:
            d = _extract_post(el)
            if d and d["uid"] not in seen:
                seen.add(d["uid"]); results.append(d); added += 1
        except StaleElementReferenceException:
            continue
    return added

def scroll_and_collect(driver, target=TARGET_POSTS):
    """
    边滚动边抓取。
    小红书使用虚拟列表，滚出视口的 DOM 节点会被删除，
    必须每次滚动后立即采集，否则漏掉大量内容。
    """
    print(f"\n开始采集，目标 >= {target} 条...")
    seen, results, last_h = set(), [], driver.execute_script("return document.body.scrollHeight")
    n = _harvest_visible(driver, seen, results)
    print(f"  首屏：+{n}，累计 {len(results)}")
    for rnd in range(MAX_SCROLL_ROUNDS):
        if len(results) >= target:
            print(f"  已达 {target} 条目标"); break
        driver.execute_script(f"window.scrollBy(0, {random.randint(600,1000)});")
        if random.random() < 0.15:
            back = random.randint(80, 200)
            driver.execute_script(f"window.scrollBy(0, -{back});")
            time.sleep(random.uniform(0.3, 0.8))
            driver.execute_script(f"window.scrollBy(0, {back});")
        random_sleep(2.0, 4.0)
        n = _harvest_visible(driver, seen, results)
        print(f"  第 {rnd+1} 轮：+{n}，累计 {len(results)}")
        new_h = driver.execute_script("return document.body.scrollHeight")
        if new_h == last_h and n == 0:
            print("  已到底部"); break
        last_h = new_h
    print(f"  采集完成：{len(results)} 条")
    return results


# =========================================================
# 详情页：抓取正文 + 评论
# 关键改进：优先使用 PC 已登录详情页，移动端 H5 仅作为兜底
# =========================================================

def _click_expand_buttons(driver):
    """小红书详情页正文有时默认折叠，先尝试点开。"""
    candidates = [
        '//*[self::button or self::span or self::div][normalize-space()="展开"]',
        '//*[self::button or self::span or self::div][contains(normalize-space(),"展开更多")]',
        '//*[self::button or self::span or self::div][contains(normalize-space(),"更多")]',
    ]
    for xp in candidates:
        try:
            for el in driver.find_elements(By.XPATH, xp)[:3]:
                if el.is_displayed():
                    driver.execute_script("arguments[0].click();", el)
                    random_sleep(0.4, 0.9)
        except Exception:
            continue


def _extract_note_body(driver) -> tuple[str, str]:
    """
    从当前详情页提取正文，返回 (正文, 来源)。
    先读页面可见 DOM；如果前端把数据塞进脚本状态里，再从源码兜底提取。
    """
    _click_expand_buttons(driver)
    candidates = []

    # 1. Selenium XPath：兼容当前配置中的多套 DOM。
    for xp in SEL["note_body"]:
        try:
            parts = driver.find_elements(By.XPATH, xp)
            text = " ".join(p.text.strip() for p in parts if p.text.strip())
            text = _clean_text(text)
            if text:
                candidates.append((text, f"XPath: {xp[:48]}"))
        except Exception:
            continue

    # 2. JS 直接读 innerText：有些节点 Selenium .text 会为空。
    try:
        js_texts = driver.execute_script("""
            const selectors = [
              '#detail-desc .note-text',
              '#detail-desc',
              '.note-content .note-text',
              '.note-content',
              '.note-detail .desc',
              '[class*="note-text"]',
              '[class*="desc"]'
            ];
            const out = [];
            for (const sel of selectors) {
              for (const el of document.querySelectorAll(sel)) {
                const text = (el.innerText || el.textContent || '').trim();
                if (text) out.push([text, sel]);
              }
            }
            return out;
        """)
        for text, sel in js_texts or []:
            text = _clean_text(text)
            if text:
                candidates.append((text, f"CSS: {sel}"))
    except Exception:
        pass

    # 3. 源码兜底：新版页面常把 desc/content 放在 hydration JSON 里。
    try:
        src = driver.page_source
        patterns = [
            r'"desc"\s*:\s*"((?:\\.|[^"\\]){20,})"',
            r'"description"\s*:\s*"((?:\\.|[^"\\]){20,})"',
            r'"content"\s*:\s*"((?:\\.|[^"\\]){20,})"',
            r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']{20,})["\']',
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']{20,})["\']',
        ]
        for pat in patterns:
            for match in re.findall(pat, src):
                text = _clean_text(match)
                if text and "小红书" not in text[:12]:
                    candidates.append((text, "page state/meta"))
    except Exception:
        pass

    bad_words = (
        "登录", "扫码", "打开小红书", "下载小红书", "验证码",
        "当前内容仅支持", "APP 内查看", "APP内查看",
    )
    filtered = [
        (text, source) for text, source in candidates
        if len(text) >= 8 and not any(w in text[:80] for w in bad_words)
    ]
    if not filtered:
        return "", ""

    # 同一正文可能被多个选择器命中，取最长的有效文本。
    best_text, best_source = max(filtered, key=lambda item: len(item[0]))
    return best_text, best_source

def scrape_detail(driver, post, max_comments=MAX_COMMENTS):
    """
    进入笔记详情页，抓取：
    - 完整正文（优先使用当前已登录 PC 页面）
    - 点赞最高的前 N 条评论
    """
    link = post.get("link", "")
    if not link:
        return "", []

    print(f"    详情页：{post['title'][:28]}...")
    original_url = driver.current_url
    try:
        # 先用 PC 登录态打开。你在网页上能看全文时，这条路径最稳定。
        set_mobile_mode(driver, enable=False)
        driver.get(link)
        random_sleep(3, 5)

        body_text, source = _extract_note_body(driver)

        # 如果 PC 详情页没有输出正文，再尝试移动端 H5。当前环境里这个路径可能被风控，
        # 所以只作为兜底，避免一开始就破坏正常网页登录态。
        if not body_text:
            try:
                set_mobile_mode(driver, enable=True)
                driver.get(link)
                random_sleep(3, 5)
                body_text, source = _extract_note_body(driver)
            except Exception as e:
                print(f"      移动端兜底失败：{e}")

        if not body_text:
            print("      正文未找到（可能仍需登录或 DOM 结构已更新）")
        else:
            print(f"      正文抓取成功（{len(body_text)} 字，{source}）")

        # 滚动加载评论
        for _ in range(3):
            driver.execute_script("window.scrollBy(0, 600);")
            random_sleep(1.5, 3.0)

        comment_els = find_els(driver, SEL["comment_items"])
        comments = []
        for el in comment_els:
            try:
                text_el,   _ = find_el(el, SEL["comment_text"])
                text = text_el.text.strip() if text_el else ""
                if not text:
                    continue
                like_el,   _ = find_el(el, SEL["comment_like"])
                author_el, _ = find_el(el, SEL["comment_author"])
                like_raw = like_el.text.strip() if like_el else "0"
                author   = author_el.text.strip() if author_el else "匿名"
                comments.append({
                    "post_uid": post["uid"], "post_title": post["title"],
                    "comment_text": text,
                    "comment_like": parse_number(like_raw),
                    "comment_like_raw": like_raw,
                    "author": author,
                })
            except Exception:
                continue

        comments.sort(key=lambda x: x["comment_like"], reverse=True)
        top = comments[:max_comments]
        print(f"      评论：找到 {len(comment_els)} 条，取 Top {len(top)}")
        return body_text, top

    except Exception as e:
        print(f"      详情页异常：{e}")
        return "", []
    finally:
        try:
            # 返回搜索列表页前恢复 PC 模式，保证选择器正常
            set_mobile_mode(driver, enable=False)
            driver.get(original_url)
            random_sleep(2, 4)
        except Exception:
            pass


def scrape_all_details(driver, top10_posts):
    """对 Top10 笔记逐一抓正文+评论"""
    print(f"\n抓取 Top10 笔记详情...")
    all_comments = []
    for i, post in enumerate(top10_posts, 1):
        print(f"  [{i}/10] {post['title'][:30]}")
        body, cmts = scrape_detail(driver, post)
        post["body"] = body          # 正文写回 post 字典
        all_comments.extend(cmts)
        random_sleep(3, 7)
    print(f"  详情抓取完成，共 {len(all_comments)} 条评论")
    return all_comments


# =========================================================
# DeepSeek AI 分析
# 申请 Key：https://platform.deepseek.com/api_keys
# =========================================================

def call_deepseek(api_key: str, prompt: str, max_tokens: int = 2048) -> str:
    """调用 DeepSeek Chat API"""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": "你是一位严谨的社会学/传播学研究助理。"},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.4,
    }
    try:
        resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=90)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except requests.exceptions.HTTPError as e:
        if resp.status_code == 429:
            return "⚠️ DeepSeek API 请求过于频繁或额度不足，请稍后再试"
        return f"⚠️ API 请求失败：{e}"
    except Exception as e:
        return f"⚠️ 解析响应失败：{e}"


def build_analysis_prompt(keyword: str, top10: list, all_comments: list) -> str:
    """
    构建发给 DeepSeek 的分析提示词。
    包含 Top10 标题+正文摘要+热评，让 AI 做深度学术分析。
    """
    posts_text = ""
    for i, p in enumerate(top10, 1):
        body_preview = (p.get("body", "") or "（正文未获取到）")[:300]
        posts_text += (
            f"\n【第{i}篇】{p['title']}\n"
            f"  互动：点赞{int(p['like'])} 收藏{int(p['collect'])} 评论{int(p['comment'])}\n"
            f"  正文摘要：{body_preview}\n"
        )
        post_cmts = [c for c in all_comments if c["post_uid"] == p["uid"]]
        if post_cmts:
            posts_text += "  热门评论：\n"
            for c in post_cmts[:5]:
                posts_text += f"    · {c['author']}（👍{c['comment_like_raw']}）：{c['comment_text'][:80]}\n"

    prompt = f"""你是一位社会学/传播学研究助理，请对以下小红书数据进行学术分析。

关键词：「{keyword}」
数据来源：小红书平台 Top10 热门笔记（按综合热度排序）

{posts_text}

请从以下维度进行分析（每项约 150-200 字，使用正式学术语言）：

1. **内容主题归纳**
   归纳 Top10 笔记的核心议题和话题类型，识别高频词汇与主导叙事框架。

2. **用户情感与态度**
   基于正文内容和评论，分析用户对该话题的主要情感倾向和态度立场。

3. **互动模式分析**
   分析点赞、收藏、评论的分布规律，探讨哪类内容更容易引发用户互动。

4. **传播特征总结**
   从传播学视角总结该话题在小红书平台上的传播特点。

5. **研究局限与建议**
   指出本次数据采集的局限性，并对后续研究提出建议。

请以 Markdown 格式输出，语言简洁专业，适合直接引用于学术论文。"""
    return prompt


def run_ai_analysis(api_key: str, keyword: str, top10_posts: list, all_comments: list) -> str:
    """执行 DeepSeek 分析，返回分析报告文本"""
    if not api_key or api_key == "YOUR_DEEPSEEK_API_KEY":
        return "（未配置 DeepSeek API Key，跳过 AI 分析）"

    print("\nDeepSeek AI 分析中...")
    prompt = build_analysis_prompt(keyword, top10_posts, all_comments)
    result = call_deepseek(api_key, prompt)
    print("  AI 分析完成")
    return result


# =========================================================
# 分析与评分
# =========================================================

def compute_score(row):
    return row["like"] * 1.0 + row["collect"] * 1.5 + row["comment"] * 0.8

def analyze(df, keyword):
    if df.empty:
        print("数据为空"); return df
    df = df.copy()
    df["score"] = df.apply(compute_score, axis=1)
    top10 = df.sort_values("score", ascending=False).head(10).reset_index(drop=True)
    print(f"\n{'='*62}")
    print(f"  Top10 热门笔记 · 关键词「{keyword}」")
    print(f"{'='*62}")
    for i, r in top10.iterrows():
        print(f"  {i+1:2d}. {r['title'][:28]:<28}  "
              f"👍{int(r['like']):<6} ⭐{int(r['collect']):<6} 💬{int(r['comment']):<6} 分:{int(r['score'])}")
    return top10


# =========================================================
# HTML 报告（含正文摘要 + 评论 + AI 分析）
# =========================================================

def md_to_html(text: str) -> str:
    """极简 Markdown -> HTML 转换（仅处理标题和加粗，避免引入第三方库）"""
    lines = []
    for line in text.split("\n"):
        line = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', line)
        if line.startswith("## "):
            lines.append(f"<h3>{line[3:]}</h3>")
        elif line.startswith("# "):
            lines.append(f"<h2>{line[2:]}</h2>")
        elif line.startswith("### "):
            lines.append(f"<h4>{line[4:]}</h4>")
        elif line.strip().startswith("- ") or line.strip().startswith("· "):
            lines.append(f"<li>{line.strip()[2:]}</li>")
        elif line.strip() == "":
            lines.append("<br>")
        else:
            lines.append(f"<p>{line}</p>")
    return "\n".join(lines)


def generate_html_report(df, top10, comments_df, keyword, ai_analysis=""):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    def bar(val, mx, color):
        pct = min(int(val / mx * 100), 100) if mx else 0
        return (f'<div style="background:{color};height:8px;width:{pct}%;'
                f'border-radius:4px;min-width:2px;margin-bottom:2px"></div>')

    ml = top10["like"].max() or 1
    mc = top10["collect"].max() or 1
    mo = top10["comment"].max() or 1

    rows_html = ""
    for i, r in top10.iterrows():
        rank  = i + 1
        medal = ["🥇","🥈","🥉"][rank-1] if rank <= 3 else f"#{rank}"
        lnk   = (f'<a href="{r["link"]}" target="_blank" '
                 f'style="color:#e0384c;margin-left:4px;text-decoration:none">↗</a>'
                 if r.get("link") else "")

        # 正文摘要（截取前 200 字）
        body = r.get("body", "") or ""
        body_block = ""
        if body:
            body_block = (
                f'<div style="font-size:12px;color:#666;margin:6px 0;'
                f'padding:8px;background:#f9f9f9;border-radius:6px;line-height:1.6">'
                f'📝 {body[:200]}{"..." if len(body)>200 else ""}</div>'
            )

        # 评论块
        cmt_block = ""
        if not comments_df.empty:
            post_cmts = comments_df[comments_df["post_uid"] == r["uid"]]
            if not post_cmts.empty:
                cmt_items = "".join(
                    f'<div style="padding:5px 0;border-bottom:1px solid #f0f0f0;font-size:12px">'
                    f'<span style="color:#e0384c;font-weight:500">{row["author"]}</span>'
                    f'<span style="color:#ccc;margin:0 5px">·</span>'
                    f'<span style="color:#aaa">👍{row["comment_like_raw"] or int(row["comment_like"])}</span>'
                    f'<div style="color:#555;margin-top:2px">{row["comment_text"]}</div>'
                    f'</div>'
                    for _, row in post_cmts.iterrows()
                )
                cmt_block = (
                    f'<div style="margin-top:8px">'
                    f'<div style="font-size:11px;color:#bbb;margin-bottom:4px">热门评论 Top{len(post_cmts)}</div>'
                    f'{cmt_items}</div>'
                )

        rows_html += f"""
        <tr>
          <td style="text-align:center;font-size:18px;white-space:nowrap;vertical-align:top;padding-top:14px">{medal}</td>
          <td style="vertical-align:top">
            <div><span title="{r['title']}">{r['title'][:40]}{"…" if len(r['title'])>40 else ""}</span>{lnk}</div>
            {body_block}
            {cmt_block}
          </td>
          <td style="vertical-align:top">{bar(r['like'],    ml,'#e85d42')}<span style="font-size:11px;color:#aaa">{r['raw_like']    or int(r['like'])}</span></td>
          <td style="vertical-align:top">{bar(r['collect'], mc,'#f5a623')}<span style="font-size:11px;color:#aaa">{r['raw_collect'] or int(r['collect'])}</span></td>
          <td style="vertical-align:top">{bar(r['comment'], mo,'#4a90e2')}<span style="font-size:11px;color:#aaa">{r['raw_comment'] or int(r['comment'])}</span></td>
          <td style="text-align:right;font-weight:600;color:#e0384c;vertical-align:top">{int(r['score'])}</td>
        </tr>"""

    ai_section = ""
    if ai_analysis and "未配置" not in ai_analysis:
        ai_section = f"""
        <h2 style="font-size:16px;margin:28px 0 12px;color:#444">🤖 DeepSeek AI 学术分析</h2>
        <div style="background:#fff;border-radius:12px;padding:20px 24px;
                    box-shadow:0 2px 10px rgba(0,0,0,.06);line-height:1.8;font-size:14px;color:#333">
          {md_to_html(ai_analysis)}
        </div>"""

    total    = len(df)
    avg_like = int(df["like"].mean()) if not df.empty else 0
    avg_col  = int(df["collect"].mean()) if not df.empty else 0
    cmt_tot  = len(comments_df) if not comments_df.empty else 0

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>小红书分析 · {keyword}</title>
<style>
  *{{box-sizing:border-box}}
  body{{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB",sans-serif;
       background:#f7f7f7;color:#333;max-width:980px;margin:0 auto;padding:28px 20px}}
  h1{{color:#e0384c;border-bottom:3px solid #e0384c;padding-bottom:10px;font-size:22px;margin-bottom:6px}}
  .cards{{display:flex;gap:14px;flex-wrap:wrap;margin:16px 0 24px}}
  .card{{background:#fff;border-radius:12px;padding:16px 20px;flex:1;min-width:130px;
         box-shadow:0 2px 10px rgba(0,0,0,.06);text-align:center}}
  .card .num{{font-size:24px;font-weight:700;color:#e0384c}}
  .card .lbl{{font-size:12px;color:#999;margin-top:4px}}
  table{{width:100%;border-collapse:collapse;background:#fff;
         border-radius:12px;overflow:hidden;box-shadow:0 2px 10px rgba(0,0,0,.06)}}
  th{{background:#e0384c;color:#fff;padding:10px 12px;font-size:13px;font-weight:500;text-align:left}}
  td{{padding:10px 12px;border-bottom:1px solid #f2f2f2;font-size:13px}}
  tr:last-child>td{{border-bottom:none}}
  .footer{{text-align:center;color:#ccc;font-size:11px;margin-top:28px}}
</style>
</head>
<body>
<h1>小红书数据分析报告</h1>
<p style="color:#999;font-size:13px">关键词：<strong style="color:#333">「{keyword}」</strong>&emsp;生成时间：{ts}</p>

<div class="cards">
  <div class="card"><div class="num">{total}</div><div class="lbl">抓取笔记总数</div></div>
  <div class="card"><div class="num">{avg_like:,}</div><div class="lbl">平均点赞量</div></div>
  <div class="card"><div class="num">{avg_col:,}</div><div class="lbl">平均收藏量</div></div>
  <div class="card"><div class="num">{cmt_tot}</div><div class="lbl">热评总数</div></div>
</div>

<h2 style="font-size:16px;margin:0 0 12px;color:#444">Top 10 热门笔记（含正文摘要与热门评论）</h2>
<table>
  <thead><tr>
    <th width="48">排名</th><th>标题 / 正文摘要 / 热评</th>
    <th width="100">点赞</th><th width="100">收藏</th>
    <th width="100">评论数</th><th width="68">综合分</th>
  </tr></thead>
  <tbody>{rows_html}</tbody>
</table>
<p style="font-size:11px;color:#ccc;margin-top:8px">综合分 = 点赞×1.0 + 收藏×1.5 + 评论×0.8</p>

{ai_section}

<div class="footer">本报告由小红书学术数据采集工具 v4.2 生成 · 仅供学术研究使用</div>
</body></html>"""

    fname = f"report_{keyword}_{datetime.now().strftime('%Y%m%d_%H%M')}.html"
    with open(fname, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  HTML 报告 -> {fname}")
    return fname


# =========================================================
# 主流程
# =========================================================

def run(keyword, target=TARGET_POSTS, deepseek_key="", cfg=None):
    if cfg is None:
        cfg = load_config()
    driver = init_driver(cfg=cfg)
    try:
        # 1. 登录
        if not ensure_login(driver):
            print("登录失败，退出"); return
        random_sleep(2, 4)

        # 2. 搜索 + 批量采集
        search_keyword(driver, keyword)
        posts = scroll_and_collect(driver, target=target)
        if not posts:
            print("未抓到任何笔记"); return

        df = pd.DataFrame(posts)
        df["score"] = df.apply(compute_score, axis=1)
        top10_df    = df.sort_values("score", ascending=False).head(10).reset_index(drop=True)
        top10_posts = top10_df.to_dict("records")

        # 3. 进入详情页抓正文 + 评论（优先使用 PC 已登录页面）
        all_comments = scrape_all_details(driver, top10_posts)
        # 把正文写回 top10_df
        for p in top10_posts:
            top10_df.loc[top10_df["uid"] == p["uid"], "body"] = p.get("body", "")
        comments_df = pd.DataFrame(all_comments) if all_comments else pd.DataFrame()

        # 4. 控制台 Top10 打印
        analyze(df, keyword)

        # 5. DeepSeek AI 分析
        ai_result = run_ai_analysis(deepseek_key, keyword, top10_posts, all_comments)
        if ai_result and "未配置" not in ai_result:
            print("\n===== AI 分析摘要（前 500 字）=====")
            print(ai_result[:500] + "...\n（完整内容见 HTML 报告）")

        # 6. 保存文件
        ts  = datetime.now().strftime("%Y%m%d_%H%M")
        raw = f"raw_{keyword}_{ts}.csv"
        top = f"top10_{keyword}_{ts}.csv"
        cmt = f"comments_{keyword}_{ts}.csv"
        ai_txt = f"ai_analysis_{keyword}_{ts}.txt"

        df.to_csv(raw, index=False, encoding="utf-8-sig")
        top10_df.to_csv(top, index=False, encoding="utf-8-sig")
        if not comments_df.empty:
            comments_df.to_csv(cmt, index=False, encoding="utf-8-sig")
        if ai_result and "未配置" not in ai_result:
            with open(ai_txt, "w", encoding="utf-8") as f:
                f.write(ai_result)

        report = generate_html_report(df, top10_df, comments_df, keyword, ai_result)

        cfg = load_config(); cfg["last_keyword"] = keyword; save_config(cfg)

        print(f"\n{'='*55}")
        print(f"  全部完成！")
        print(f"  全量笔记：{raw}（{len(df)} 条）")
        print(f"  Top10：   {top}")
        if not comments_df.empty:
            print(f"  热评：    {cmt}（{len(comments_df)} 条）")
        if ai_result and "未配置" not in ai_result:
            print(f"  AI分析：  {ai_txt}")
        print(f"  报告：    {report}")
        print(f"{'='*55}")

    except KeyboardInterrupt:
        print("\n已手动中断")
    finally:
        random_sleep(1, 2)
        driver.quit()


# =========================================================
# 入口
# =========================================================

if __name__ == "__main__":
    print("=" * 55)
    print("  小红书学术数据采集工具  v4.2")
    print("  仅供学术研究，请遵守平台使用规范")
    print("=" * 55)

    cfg     = load_config()
    last_kw = cfg.get("last_keyword", "")

    kw = input(f"\n请输入关键词（上次：{last_kw or '无'}）: ").strip() or last_kw
    if not kw:
        print("请输入关键词"); sys.exit(1)

    t_in   = input(f"目标笔记数（默认 {TARGET_POSTS}，建议 100-300）: ").strip()
    target = int(t_in) if t_in.isdigit() and int(t_in) > 0 else TARGET_POSTS

    print("\n--- DeepSeek AI 分析配置 ---")
    print("  申请 Key：https://platform.deepseek.com/api_keys")
    saved_key = cfg.get("deepseek_key", "")
    if saved_key:
        use_saved = input(f"  检测到已保存的 Key（...{saved_key[-6:]}），直接使用？(Y/n): ").strip().lower()
        deepseek_key = saved_key if use_saved != "n" else input("  请输入新的 DeepSeek API Key（留空跳过）: ").strip()
    else:
        deepseek_key = input("  请输入 DeepSeek API Key（留空跳过 AI 分析）: ").strip()

    if deepseek_key and deepseek_key != saved_key:
        cfg["deepseek_key"] = deepseek_key
        save_config(cfg)
        print("  Key 已保存，下次自动使用")

    # ChromeDriver 路径配置
    saved_driver = cfg.get("chromedriver_path", "")
    print("\n--- ChromeDriver 配置 ---")
    if saved_driver and Path(saved_driver).exists():
        print(f"  已保存路径：{saved_driver}")
        change = input("  是否更换？(y/N): ").strip().lower()
        if change == "y":
            saved_driver = ""
    if not saved_driver:
        print("  请输入 ChromeDriver 完整路径")
        print("  （留空则由程序自动查找；手动下载的请粘贴路径，如：")
        print("   /Users/你的用户名/Downloads/chromedriver-mac-arm64/chromedriver）")
        new_path = input("  路径：").strip()
        if new_path and Path(new_path).exists():
            cfg["chromedriver_path"] = new_path
            save_config(cfg)
            print(f"  路径已保存，下次自动使用")
        elif new_path:
            print(f"  警告：路径不存在，将尝试自动查找")

    run(kw, target, deepseek_key, cfg=cfg)
