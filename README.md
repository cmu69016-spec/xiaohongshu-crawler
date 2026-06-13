Uploading R# 小红书学术数据采集工具

> 基于 Selenium + DeepSeek AI 的小红书内容采集与分析工具，仅供学术研究使用。

![Python](https://img.shields.io/badge/Python-3.10%2B-blue) ![License](https://img.shields.io/badge/license-MIT-green) ![Version](https://img.shields.io/badge/version-4.2-orange)

---

## 功能特性

- **关键词搜索采集**：按热度搜索笔记，支持自定义采集数量（推荐 100–300 条）
- **正文全文抓取**：优先使用 PC 已登录页面抓取详情全文，移动端 H5 作为兜底方案
- **互动数据提取**：自动提取点赞、收藏、评论数，支持"万"/"k"等中文数字格式
- **热评采集**：进入 Top10 笔记详情页，抓取最多 10 条热门评论
- **DeepSeek AI 深度分析**：调用 DeepSeek API 对采集内容进行学术分析，支持自定义分析 Prompt
- **HTML 可视化报告**：自动生成含统计卡片、Top10 排行表、AI 分析的 HTML 报告
- **反检测机制**：三级 ChromeDriver 启动降级策略，隐藏自动化特征，随机延迟模拟真人操作
- **Cookie 持久化**：登录状态自动保存，下次运行无需重复扫码登录

---

## 输出文件

每次运行结束后，程序会在当前目录生成以下文件：

| 文件名 | 内容 |
|---|---|
| `raw_{关键词}_{时间}.csv` | 全量采集笔记数据 |
| `top10_{关键词}_{时间}.csv` | 综合评分 Top10 笔记（含正文） |
| `comments_{关键词}_{时间}.csv` | Top10 笔记的热门评论 |
| `ai_analysis_{关键词}_{时间}.txt` | DeepSeek AI 分析全文 |
| `report_{关键词}_{时间}.html` | 可视化 HTML 报告（含 AI 分析） |

> 综合评分公式：`分数 = 点赞 × 1.0 + 收藏 × 1.5 + 评论 × 0.8`

---

## 环境要求

- Python 3.10+
- Google Chrome 浏览器（与 ChromeDriver 版本需匹配）
- ChromeDriver（程序可自动查找，也支持手动指定路径）

---

## 安装依赖

```bash
pip install selenium webdriver-manager undetected-chromedriver pandas requests
```

---

## 快速开始

### 1. 获取 DeepSeek API Key（可选）

前往 [DeepSeek 开放平台](https://platform.deepseek.com/api_keys) 申请 API Key。不配置则跳过 AI 分析，其余功能正常使用。

### 2. 运行脚本

```bash
python demo.py
```

按照交互提示依次输入：

1. **搜索关键词**（例如：`老年认知障碍`）
2. **目标采集数量**（默认 100，建议 100–300）
3. **DeepSeek API Key**（留空跳过 AI 分析；已保存的 Key 可直接回车复用）
4. **AI 分析 Prompt**（选填，例如：`请从养老服务需求角度分析照护痛点和服务缺口`）
5. **ChromeDriver 路径**（留空则自动查找；Mac ARM 用户建议手动指定路径）

### 3. 登录小红书

程序启动后会打开 Chrome 浏览器并跳转至小红书，**手动完成扫码登录**（限时 120 秒）。登录状态会通过 Cookie 保存，下次运行可跳过此步骤。

---

## ChromeDriver 配置说明

程序采用三级降级策略自动查找驱动：

1. **优先**：读取用户手动保存在 `xhs_config.json` 中的路径
2. **次选**：扫描 `webdriver-manager` 本地缓存（`~/.wdm/drivers/chromedriver`）
3. **兜底**：调用 `webdriver-manager` 联网自动下载

**Mac Apple Silicon（M1/M2/M3）用户注意：**

建议手动下载与 Chrome 版本对应的 ARM64 ChromeDriver，并在首次运行时粘贴完整路径。程序会自动执行 `xattr` 解除 Gatekeeper 隔离。

手动下载地址：[https://googlechromelabs.github.io/chrome-for-testing/](https://googlechromelabs.github.io/chrome-for-testing/)

---

## 配置文件

程序运行后会在脚本目录生成 `xhs_config.json`，保存以下配置：

```json
{
  "last_keyword": "上次搜索的关键词",
  "deepseek_key": "你的 DeepSeek API Key",
  "chromedriver_path": "/path/to/chromedriver"
}
```

可直接编辑此文件修改默认配置。

---

## 注意事项

- 本工具**仅供学术研究使用**，请遵守小红书平台使用规范及相关法律法规
- 请勿用于商业目的或大规模爬取
- 建议采集间隔不低于默认随机延迟，避免对平台造成过大压力
- 平台页面结构可能随时更新，如遇采集失败请检查 XPath 选择器

---

## 项目结构

```
.
├── demo.py            # 主程序
├── xhs_config.json    # 配置文件（运行后自动生成）
├── xhs_cookies.pkl    # Cookie 缓存（登录后自动生成）
└── README.md
```

---

## License

MIT License — 仅供学术研究，使用者自行承担法律责任。
EADME.md…]()
