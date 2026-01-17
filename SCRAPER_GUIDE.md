## 文章来源 Scraper 扩展指南（支持单篇导入 + 单日批量导入）

本文总结了当前项目里现有 scraper 的实现套路，抽象出**新增媒体来源**时可复用的参考规则与接入清单。目标是让未来新增网站时能同时支持：

- **单篇导入**：给一个文章 URL，抓取 HTML + 元信息，并保存到 `data/html/en`（可选翻译到 `data/html/zh`），随后被 importer 入库。
- **单日批量导入**：给一个日期（YYYY-MM-DD），从"当天文章列表页/归档页"找到该日所有文章 URL，逐篇抓取并保存、翻译、入库（像 Aeon / Nautilus 那样）。

**重要说明**：
- 当前项目的 **scheduled job（定时任务）仅支持 Aeon 和 Nautilus** 两个来源
- 本文档可用于帮助扩充其他来源的 scraper 实现
- **所有新增来源必须严格遵守合法合规原则**（见下文"合法合规要求"章节）

---

## ⚠️ 合法合规要求（必须严格遵守）

### Paywall/访问限制处理的核心原则

**在实现任何 scraper 之前，必须首先确认以下事项：**

1. **优先使用官方 API**
   - 如果目标站点提供官方 API（如 RSS API、Content API、Developer API 等），**必须优先使用官方 API**
   - 官方 API 通常提供更稳定、更合规的数据访问方式
   - 使用官方 API 时，请遵循 API 的使用条款和速率限制

2. **合法授权访问**
   - 如果目标内容需要订阅/会员/登录才能访问，**必须通过合法途径获得授权**
   - 不得绕过 paywall、登录验证或其他访问控制机制
   - 不得使用任何技术手段（如修改请求头、使用代理、破解验证等）来规避访问限制

3. **明确失败处理**
   - 如果遇到 paywall/访问限制且无法通过合法途径获得授权，**必须明确标记为失败并跳过**
   - 不得将"订阅提示"、"登录页面"、"访问受限提示"等当作正文内容保存
   - 在日志中清晰记录访问失败的原因

4. **遵守服务条款**
   - 在实现 scraper 前，必须阅读并理解目标站点的服务条款（Terms of Service）
   - 确保你的使用方式符合服务条款的要求
   - 如有疑问，应联系站点管理员或法律顾问

5. **数据使用合规**
   - 抓取的内容仅用于个人学习、研究或符合合理使用（Fair Use）原则的用途
   - 不得将抓取的内容用于商业用途，除非获得明确授权
   - 尊重版权，保留原始来源信息

**实现建议**：
- 在 scraper 代码中明确注释访问方式和授权状态
- 实现访问限制检测，遇到 paywall 时立即停止并记录日志
- 如果站点提供公开的 RSS feed 或 API，优先使用这些方式
- 定期检查站点政策变化，确保 scraper 始终合规

---

## 系统链路概览（你需要接入到哪里）

### 单篇导入链路（URL → HTML/JSON → 入库）

- **入口脚本**：`scripts/extract_articles_by_date.py`
  - `--url <article_url>` 会调用 `app.services.scrapers.get_scraper_for_url()` 选 scraper
  - 调用 `scraper.scrape(url)` 抓取
  - 用统一的命名规则落盘 HTML + JSON metadata（见下文"文件命名与元数据"）
- **入库**：`app/services/importer.py`
  - 扫描 `data/html/en/*.html`（以及同名 `data/html/zh/*.html`），结合 `.json` 元数据与 HTML meta 做兜底抽取
  - 根据 `original_url` / 规范化 URL / 文件名 / title+author+date 去重或更新

> 结论：新增来源要先保证 `get_scraper_for_url(url)` 能选到你写的 scraper，并且 `scraper.scrape()` 的元信息足够稳定（title/author/date/category/url）。

### 单日批量导入链路（date → URL list → HTML/JSON → 入库）

- **入口脚本**：仍是 `scripts/extract_articles_by_date.py`
  - 当前对 **Aeon 和 Nautilus** 实现了 `find_articles_by_date()` 搜索当天 URL 列表
  - 找到 URL 后逐篇调用 `save_article_html()` 抓取并落盘，再进行翻译与入库
- **定时触发**：`app/services/scheduler.py`
  - **当前仅支持 Aeon 和 Nautilus 的定时抓取**
  - 每日定时运行上述脚本（传入日期、输出目录、翻译开关等）
  - 脚本完成后（即使失败）也会调用 importer 兜底把已落盘文件入库

> 结论：新增来源要支持"每日批量"，不仅要写 scraper，还要把"按日期找 URL 列表"的逻辑接入脚本（或未来抽象成统一接口）。**注意：只有 Aeon 和 Nautilus 支持 scheduled job，其他来源需要手动触发或单独配置。**

---

## BaseScraper 接口约定（新增来源最小实现）

基类定义在 `app/services/scrapers/base.py`，核心是：**能判断是否处理该 URL、能抽元信息、能抽正文**。

你新增一个来源时，至少实现：

- **`can_handle(url) -> bool`**：URL 命中判断（建议尽量严格，避免误抓其他站点/镜像域名）
- **`get_source_name() -> str`**：展示用名称（入库字段 `source`）
- **`get_source_slug() -> str`**：文件命名与识别用 slug（必须稳定、唯一、URL-safe）
- **`extract_category(url, html) -> str`**：优先从 URL path/JSON-LD/meta 中提取栏目/分类；兜底返回站点名
- **`extract_metadata(html, url) -> dict`**：返回 `title/author/date/category/url`
- **`extract_body(html) -> (body_html, body_element)`**：返回正文 DOM（翻译/清洗可能依赖它），失败返回 `(None, None)`

可选实现（用于特殊保存逻辑）：

- **`save_article(...)`**：只有当你需要"除了保存 HTML/JSON 之外"的自定义逻辑时才覆盖（例如小宇宙要下载音频/转写）。普通媒体站点一般不需要。

---

## 现有 scraper 的"可复用套路"

### 1) Aeon：RSS feed + 按日过滤（按日批量）

典型特点：

- 使用 RSS feed 作为文章列表入口，高效且稳定
- RSS feed 通常包含文章 URL、标题、发布日期等元信息
- 按日过滤时，直接从 RSS feed 中筛选目标日期的文章

可复用规则：

- **RSS feed 优先**：如果站点提供 RSS feed，优先使用 RSS 而非 HTML 列表页
- **按日过滤**：从 RSS feed 的 `pubDate` 字段直接筛选目标日期
- **URL 规范化**：确保从 RSS feed 提取的 URL 是完整的绝对 URL

### 2) Nautilus：RSS feed + 按日过滤（按日批量）

典型特点：

- 同样使用 RSS feed 作为文章列表入口
- RSS feed 结构清晰，易于解析
- 支持按日期高效筛选

可复用规则：

- **RSS 解析**：使用标准 RSS 解析库（如 `feedparser`）处理 feed
- **日期匹配**：从 RSS item 的发布日期字段直接匹配目标日期
- **错误处理**：处理 RSS feed 不可用或格式异常的情况

---

## 通用参考规则（新增任何媒体站点都建议遵循）

### URL 命中与规范化

- **`can_handle()` 尽量严格**：
  - 推荐使用域名匹配（含必要的子域名），而不是简单 `in`（避免误伤聚合站/镜像）
  - 同时考虑 `http/https`、是否带 `www`
- 需要去重时建议使用 importer 里的 URL 规范化思想（去 query/fragment、去末尾 `/`），避免重复入库。

### 元信息抽取优先级（title/author/date/category）

推荐优先级（从"最稳"到"最脆"）：

1. **JSON-LD（`application/ld+json`）**：`headline`、`author.name`、`datePublished`、`articleSection`、`articleBody`
2. **OpenGraph / Article meta**：`og:title`、`article:author`、`article:published_time`、`article:section`
3. **页面结构**：`h1`、byline 区域、`time[datetime]`
4. **兜底**：`<title>`（注意去站点后缀），日期缺失则用 `date.today()`

作者字段务必做清洗：

- 丢弃 URL、路径、过短、`unknown/none/n/a`
- 必要时对 author URL 做"反推名字"（如 `/by/john-doe` → `John Doe`）

### 正文抽取（extract_body）

正文抽取的经验法则：

- **先列出站点稳定 selector 列表**（从最具体到最宽泛），命中后检查正文文本长度（例如 > 200）再接受
- **访问限制页（paywall/login/verify）**：**如果检测到 paywall，必须立即停止并标记失败，不得尝试绕过**
- **最终兜底**：在 `article/section/div/main` 中选文本量最大者（同样要阈值，避免抓到整页导航）

> 实战建议：正文抽取"宁可缺一点也别夹带导航/推荐/订阅组件"，翻译质量会差很多。**更重要的是，如果遇到 paywall，必须停止抓取，不得尝试绕过。**

### Paywall/验证页处理：合法合规优先（强制）

**重要：以下内容仅适用于页面响应中已经包含的公开数据，不得用于绕过 paywall**

你新增来源时，如果遇到 paywall/login/verify 页面：

1. **首先检查是否有合法访问方式**
   - 检查站点是否提供官方 API
   - 检查是否有公开的 RSS feed
   - 检查是否需要订阅/会员（如有，必须通过合法途径获得授权）

2. **如果无法合法访问，必须立即停止**
   - 标记为访问失败
   - 记录日志说明原因
   - **不得尝试从页面中提取任何内容**

3. **如果页面响应中确实包含公开的正文数据**（例如某些站点在 paywall 页面仍包含 JSON-LD 中的 articleBody），可以尝试提取，但必须：
   - 明确这是页面响应中已包含的公开数据
   - 不是通过技术手段绕过访问限制
   - 符合站点的服务条款

**必须做"访问限制页判定"**：

- 通过关键词（subscribe / log in / verify access / paywall 等）、遮罩层/弹窗结构、以及正文长度阈值综合判断
- 判定为访问限制后：**必须停止抓取，不要把整页导航/订阅文案当正文写入**

**明确失败条件（避免假阳性）**：

- 如果检测到 paywall 且无法通过合法途径访问，应把该 URL 标记为"需要授权访问"并停止重试
- 不要产生"保存了但其实没有正文"的坏数据

---

## 新增 Scraper 可执行 Checklist（一页版，强烈建议照单实现）

这是一份"写新来源时可直接照着做"的清单，目标是让每个新来源都具备健壮性：**主 DOM 抽不到时仍能从响应内数据源兜底抽取正文（仅限公开数据），并避免把订阅文案/导航当正文写入**。

### 0) 合法合规检查（必须，第一步）

- **检查官方 API**
  - 搜索目标站点是否提供官方 API（RSS API、Content API、Developer API 等）
  - 如有，优先使用官方 API，遵循 API 使用条款
- **检查访问要求**
  - 确认内容是否需要订阅/会员/登录
  - 如需，确认是否有合法途径获得授权
  - **如无合法途径，不得实现该 scraper**
- **阅读服务条款**
  - 阅读并理解目标站点的服务条款
  - 确保实现方式符合条款要求

### 1) 接入与可用性（必须）

- **实现并注册 scraper**
  - `can_handle()`：域名匹配要尽量严格（包含必要子域名），避免误命中
  - `get_source_name()` / `get_source_slug()`：slug 要稳定唯一
  - 在 `app/services/scrapers/__init__.py` 把实例加入 `SCRAPERS`
- **保证脚本可跑**
  - 单篇：`python scripts/extract_articles_by_date.py --url "<url>" ...`
  - 单日批量：实现 `find_articles_by_date()` 并接入脚本的按日期流程（注意：只有 Aeon 和 Nautilus 支持 scheduled job）

### 2) 元信息抽取（必须）

- **标题（必须）**
  - 优先：JSON-LD `headline` / OG `og:title` / `h1` / `<title>`（注意去站点后缀）
  - 兜底：无则用 `'untitled'`
- **作者（必须 + 清洗）**
  - 优先：JSON-LD `author.name` / meta `article:author` / byline（优先 link text）
  - 清洗规则（必须）：丢弃 URL、路径、过短、`unknown/none/n/a`
  - 推荐：支持从作者 URL 反推名称（`/by/john-doe` → `John Doe`）
- **日期（必须）**
  - 优先：meta `article:published_time` / JSON-LD `datePublished` / `time[datetime]`
  - 兜底：无则用 `date.today()`
- **分类（必须）**
  - 优先：URL path / JSON-LD `articleSection` / meta `article:section`
  - 兜底：站点名或 domain（不要空字符串）

### 3) 正文抽取主路径（必须）

- **站点 selector 列表（必须）**
  - 先放"最具体、最稳定"的容器，再到宽泛：如 `article`、`[data-module="ArticleBody"]`、`section[name="articleBody"]`、`main` 等
  - 每次命中后都做"正文足量"校验（见下文阈值）
- **去噪（推荐）**
  - 推荐在 `extract_body()` 里移除明显噪音节点再做长度判断（如 `nav`, `footer`, `aside`, `script`, `style`, 订阅弹窗容器等）

### 4) 访问限制页判定（必须）

必须提供一个统一的"访问限制/验证页"判定（可以是私有函数，例如 `_is_access_blocked(text, soup)`），并用于决定是否走兜底路径与是否拒绝输出"假正文"。

- **关键词判定（必须，大小写不敏感）**
  - 推荐关键词（按经验覆盖面）：  
    - `subscribe`, `subscription`, `sign in`, `log in`, `login`, `register`, `create account`, `verify access`, `already a subscriber`, `continue reading`, `to continue`, `unlock`, `trial`, `your access`, `captcha`
- **结构判定（推荐）**
  - 遮罩/弹窗：类名/属性包含 `paywall`, `meter`, `subscribe`, `overlay`, `modal`, `gateway`
- **兜底判定（必须）**
  - 如果正文候选区域的有效文本过短（低于阈值），即使没命中关键词，也要按"疑似阻断/抽取失败"处理，避免存入坏数据

**重要**：如果检测到 paywall 且无法通过合法途径访问，**必须立即停止并标记失败**。

### 5) 访问限制页兜底抽取（仅限公开数据，必须遵守合规原则）

**重要说明**：以下方法仅适用于页面响应中已经包含的公开数据，不得用于绕过 paywall 或访问限制。

当 `4)` 判定为访问限制页或主 selector 抽取失败时，**首先检查是否有合法访问方式**：

- 如果站点提供官方 API，优先使用 API
- 如果无法合法访问，必须停止并标记失败

只有在确认页面响应中确实包含公开正文数据时，才可尝试以下方法：

- **JSON-LD 兜底（仅限公开数据）**
  - 实现 `_extract_from_json_ld(soup)`：
    - 扫描所有 `script[type="application/ld+json"]`
    - 支持直接字段 `articleBody`
    - 支持 `@graph` 数组内嵌对象的 `articleBody`
  - **注意**：仅当这些数据确实存在于页面响应中，且不是通过技术手段绕过访问限制时，才可使用
- **JS state 兜底（仅限公开数据，强烈建议）**
  - 实现 `_extract_from_javascript(html)`：
    - 在 HTML 字符串中查找类似 `__INITIAL_STATE__` / `__PRELOADED_STATE__` 的 JSON 对象（或站点常见 state）
    - 递归遍历字典/列表以寻找 `articleBody`（可实现 `_find_article_body_in_dict(data)`）
  - 注意：只把**确实存在于响应中的文本**当作正文；不要依赖浏览器执行 JS 后才出现的内容
  - **注意**：仅当这些数据确实存在于页面响应中，且不是通过技术手段绕过访问限制时，才可使用
- **公开轻页面（推荐）**
  - 如果站点存在无需额外权限的公开版本（AMP/print/reader），可在 `fetch_page()` 前对 URL 做"候选变体"尝试（实现为白名单规则，避免误判）

### 6) 正文"足量/可信"阈值（必须）

建议在 `extract_body()` 中统一做以下校验（满足才输出正文，否则返回 `(None, None)` 触发上层失败/重试逻辑）：

- **最小文本长度**：`>= 200` 字符（与现有实现一致；长文站点可提高到 `>= 500`）
- **段落数（推荐）**：正文容器内 `<p>` 有效段落 `>= 3`
- **噪音占比（推荐）**：正文文本中如果订阅/登录/免责声明等关键词占比过高，判定为失败
- **标题/作者联动（推荐）**：若作者为 `unknown` 且正文也不足量，直接判失败（防止抓到索引页/专题页）

### 7) 单日批量：URL 列表侧的必做项（必须）

- **URL 抽取去重 + 规范化（必须）**
  - 相对链接补全为绝对 URL
  - 去掉明显非文章链接（`/latest`、`/about`、`/podcast`、`/video` 等按站点定制）
- **按日过滤策略（必须选一种）**
  - **优先**：从"按日归档页/RSS"直接得到当天列表（省请求、抗风控）
  - **否则**：latest 倒序流 + 逐篇查 `datePublished`（必要时并发）+ 早停（当确认全页都早于目标日）

### 8) 代码模板（复制即用，按站点改 TODO）

下面提供两个模板：

- **模板 A（单篇抓取）**：实现 `BaseScraper` 必需方法 + "访问限制判定 + JSON-LD/JS state 兜底 + 阈值校验"
- **模板 B（单日批量）**：提供 `find_articles_by_date()` 的常用结构（归档页/RSS 优先，或 latest + 查日期 + 早停）

> 注意：模板中的"访问限制/兜底抽取"只针对**同一次 HTTP 响应中已经存在的公开数据**（JSON-LD / 初始 state / 公开轻页面）——**不得用于绕过 paywall 或访问限制**。

#### 模板 A：单篇 Scraper 骨架（推荐每站都从这里起步）

```python
import json
import re
from datetime import datetime, date as date_type
from typing import Optional, Tuple, Iterable
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.services.scrapers.base import BaseScraper


class ExampleSiteScraper(BaseScraper):
    """
    TODO: rename to XxxScraper
    TODO: update domain checks + selectors + mappings
    
    IMPORTANT: Before implementing, ensure you have legal access to the content.
    - Check if the site provides an official API (preferred)
    - Verify if content requires subscription/membership (if so, obtain legal authorization)
    - Read and comply with the site's Terms of Service
    """

    # ---- Required: identification ----
    def can_handle(self, url: str) -> bool:
        # TODO: make this strict (domain + optional path prefixes)
        return urlparse(url).netloc in {"www.example.com", "example.com"}

    def get_source_name(self) -> str:
        return "Example Site"

    def get_source_slug(self) -> str:
        return "examplesite"

    # ---- Required: category ----
    def extract_category(self, url: str, html: str) -> str:
        # TODO: prefer URL path segment or JSON-LD articleSection
        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.strip("/").split("/") if p]
        if path_parts:
            return path_parts[0]
        return self.get_source_name()

    # ---- Required: metadata ----
    def extract_metadata(self, html: str, url: str) -> dict:
        soup = BeautifulSoup(html, "html.parser")

        title = self._extract_title(soup)
        author = self._extract_author(soup)
        article_date = self._extract_publish_date(soup) or date_type.today()
        category = self.extract_category(url, html)

        return {
            "title": title or "untitled",
            "author": author or "unknown",
            "date": article_date,
            "category": category or self.get_source_name(),
            "url": url,
        }

    # ---- Required: body ----
    def extract_body(self, html: str) -> Tuple[Optional[str], Optional[BeautifulSoup]]:
        soup = BeautifulSoup(html, "html.parser")

        # IMPORTANT: Check for paywall/access restrictions first
        if self._is_access_blocked(soup):
            # If paywall detected and no legal access, must stop here
            # TODO: Check if you have legal access (API, subscription, etc.)
            # If no legal access, return (None, None) immediately
            # Do NOT attempt to bypass paywall
            return None, None

        # 1) Main DOM selectors (TODO: tune these per site)
        body = self._extract_from_selectors(soup)
        if body and self._is_body_sufficient(body):
            return str(body), body

        # 2) Fallback to response-embedded data sources (only if legal)
        # Only use if data is already in the response and you have legal access
        # 2.1 JSON-LD articleBody (only if publicly available in response)
        body = self._extract_from_json_ld(soup)
        if body and self._is_body_sufficient(body):
            return str(body), body

        # 2.2 JS initial state articleBody (only if publicly available in response)
        body = self._extract_from_javascript(html)
        if body and self._is_body_sufficient(body):
            return str(body), body

        # 3) Last resort: biggest container (still must pass sufficiency checks)
        body = self._extract_largest_text_container(soup)
        if body and self._is_body_sufficient(body):
            return str(body), body

        return None, None

    # -------------------------
    # Helpers: title/author/date
    # -------------------------
    def _extract_title(self, soup: BeautifulSoup) -> str:
        # JSON-LD headline
        headline = self._jsonld_first(soup, keys=("headline",))
        if headline:
            return headline

        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            return og_title["content"].strip()

        h1 = soup.find("h1")
        if h1:
            t = h1.get_text(strip=True)
            if t:
                return t

        title_tag = soup.find("title")
        if title_tag:
            return title_tag.get_text(strip=True)

        return "untitled"

    def _extract_author(self, soup: BeautifulSoup) -> str:
        # JSON-LD author.name
        author_name = self._jsonld_first_author_name(soup)
        cleaned = self._clean_author(author_name)
        if cleaned:
            return cleaned

        meta_author = soup.find("meta", property="article:author") or soup.find("meta", attrs={"name": "author"})
        if meta_author and meta_author.get("content"):
            cleaned = self._clean_author(meta_author["content"])
            if cleaned:
                return cleaned

        # TODO: site-specific byline selectors / author links
        return "unknown"

    def _extract_publish_date(self, soup: BeautifulSoup) -> Optional[date_type]:
        meta = soup.find("meta", property="article:published_time")
        if meta and meta.get("content"):
            dt = self._parse_iso_date(meta["content"])
            if dt:
                return dt

        # JSON-LD datePublished
        date_published = self._jsonld_first(soup, keys=("datePublished",))
        dt = self._parse_iso_date(date_published)
        if dt:
            return dt

        time_tag = soup.find("time")
        if time_tag and time_tag.get("datetime"):
            dt = self._parse_iso_date(time_tag["datetime"])
            if dt:
                return dt

        return None

    def _parse_iso_date(self, s: Optional[str]) -> Optional[date_type]:
        if not s:
            return None
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt.date()
        except Exception:
            return None

    def _clean_author(self, author: Optional[str]) -> Optional[str]:
        if not author:
            return None
        a = author.strip()
        if not a:
            return None
        # Drop obvious URLs / paths
        if a.startswith(("http://", "https://", "www.")) or "/" in a and a.count("/") > 2:
            return None
        if len(a) < 2 or a.lower() in {"unknown", "none", "n/a"}:
            return None
        # Remove any embedded URLs that slipped in
        a = re.sub(r"https?://\S+", "", a).strip()
        return a or None

    # -------------------------
    # Helpers: access-block + extraction
    # -------------------------
    def _is_access_blocked(self, soup: BeautifulSoup) -> bool:
        text = soup.get_text(" ", strip=True).lower()
        keywords = (
            "subscribe",
            "subscription",
            "sign in",
            "log in",
            "login",
            "register",
            "create account",
            "verify access",
            "continue reading",
            "unlock",
            "trial",
            "captcha",
        )
        if any(k in text for k in keywords):
            return True

        # TODO: site-specific overlay/modal markers
        return False

    def _extract_from_selectors(self, soup: BeautifulSoup) -> Optional[BeautifulSoup]:
        # TODO: tune selectors; keep them ordered from most-specific to least-specific
        selectors = [
            "article",
            "section[name='articleBody']",
            "[data-module='ArticleBody']",
            "main",
        ]
        for sel in selectors:
            el = soup.select_one(sel)
            if el:
                return el
        return None

    def _extract_from_json_ld(self, soup: BeautifulSoup) -> Optional[BeautifulSoup]:
        # IMPORTANT: Only use if data is publicly available in response
        # Do NOT use to bypass paywall
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
            except Exception:
                continue

            # Direct object: articleBody
            body = self._find_in_json_like(data, key="articleBody")
            if isinstance(body, str) and body.strip():
                # Wrap as HTML for downstream processing
                wrap = BeautifulSoup(f"<div class='extracted-body'>{body}</div>", "html.parser")
                return wrap.find("div")
        return None

    def _extract_from_javascript(self, html: str) -> Optional[BeautifulSoup]:
        # IMPORTANT: Only use if data is publicly available in response
        # Do NOT use to bypass paywall
        # TODO: add site-specific patterns (e.g. __NEXT_DATA__)
        patterns = [
            r"window\.__INITIAL_STATE__\s*=\s*({.+?});",
            r"window\.__PRELOADED_STATE__\s*=\s*({.+?});",
        ]
        for pat in patterns:
            for m in re.finditer(pat, html, flags=re.DOTALL):
                try:
                    data = json.loads(m.group(1))
                except Exception:
                    continue
                body = self._find_in_json_like(data, key="articleBody")
                if isinstance(body, str) and body.strip():
                    wrap = BeautifulSoup(f"<div class='extracted-body'>{body}</div>", "html.parser")
                    return wrap.find("div")
        return None

    def _extract_largest_text_container(self, soup: BeautifulSoup) -> Optional[BeautifulSoup]:
        candidates: Iterable[BeautifulSoup] = soup.find_all(["article", "section", "div", "main"])
        best = None
        best_len = 0
        for el in candidates:
            t = el.get_text(" ", strip=True)
            if len(t) > best_len:
                best_len = len(t)
                best = el
        return best

    def _is_body_sufficient(self, body: BeautifulSoup) -> bool:
        # Thresholds: tune per site; keep conservative to avoid saving paywall copy
        text = body.get_text(" ", strip=True)
        if len(text) < 200:
            return False
        # Optional paragraph count check
        ps = [p.get_text(" ", strip=True) for p in body.find_all("p")]
        ps = [p for p in ps if len(p) >= 30]
        if ps and len(ps) < 3:
            return False
        return True

    # -------------------------
    # Helpers: JSON-LD scanning
    # -------------------------
    def _jsonld_first(self, soup: BeautifulSoup, keys: Tuple[str, ...]) -> Optional[str]:
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
            except Exception:
                continue
            for k in keys:
                v = self._find_in_json_like(data, key=k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
        return None

    def _jsonld_first_author_name(self, soup: BeautifulSoup) -> Optional[str]:
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
            except Exception:
                continue
            author = self._find_in_json_like(data, key="author")
            if isinstance(author, dict):
                name = author.get("name")
                if isinstance(name, str):
                    return name
            if isinstance(author, list) and author:
                first = author[0]
                if isinstance(first, dict) and isinstance(first.get("name"), str):
                    return first["name"]
                if isinstance(first, str):
                    return first
            if isinstance(author, str):
                return author
        return None

    def _find_in_json_like(self, obj, key: str):
        # Generic recursive finder: dict/list traversal
        if isinstance(obj, dict):
            if key in obj:
                return obj[key]
            for v in obj.values():
                found = self._find_in_json_like(v, key)
                if found is not None:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = self._find_in_json_like(item, key)
                if found is not None:
                    return found
        return None
```

#### 模板 B：单日批量 `find_articles_by_date()` 结构（按站点改入口）

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date as date_type
from typing import List, Optional, Tuple
import feedparser  # For RSS feed parsing


class ExampleSiteScraper(BaseScraper):
    # ... 省略模板 A 的内容 ...

    def find_articles_by_date(
        self,
        target_date: date_type,
        max_pages: int = 50,
        max_workers: int = 8,
    ) -> List[str]:
        """
        TODO: 选择一种策略实现：
        - A) RSS feed（强推）：如果站点提供 RSS，优先使用
        - B) 归档页：直接访问当天 archive URL，抽出当天 URLs
        - C) latest 倒序流：翻页抽 URLs -> 并发查日期 -> 早停
        """
        matching: List[str] = []

        # Strategy A (preferred): RSS feed
        # TODO: if the site has an RSS feed, use it here
        # rss_url = "https://www.example.com/feed"
        # feed = feedparser.parse(rss_url)
        # for entry in feed.entries:
        #     pub_date = self._parse_feed_date(entry.get('published'))
        #     if pub_date == target_date:
        #         matching.append(entry.link)
        # if matching:
        #     return matching

        # Strategy B: daily archive
        # TODO: if the site has a stable archive endpoint, do it here
        # archive_url = f"https://www.example.com/archive/{target_date:%Y/%m/%d}/"
        # html = self.fetch_page(archive_url, verbose=True)
        # if html:
        #     return self.extract_article_urls_from_page(html)

        # Strategy C: latest pages with early stop
        for page in range(1, max_pages + 1):
            latest_url = f"https://www.example.com/latest?page={page}"
            html = self.fetch_page(latest_url, verbose=True)
            if not html:
                break

            urls = self.extract_article_urls_from_page(html)
            if not urls:
                break

            # Concurrent date checks
            page_dates = {}
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                fut_to_url = {ex.submit(self.get_article_date, u): u for u in urls}
                for fut in as_completed(fut_to_url):
                    u = fut_to_url[fut]
                    try:
                        pub, mod = fut.result()
                    except Exception:
                        pub, mod = (None, None)
                    page_dates[u] = (pub, mod)

                    check = mod or pub
                    if check == target_date:
                        matching.append(u)

            # Early stop: if all known dates on page are older than target_date
            checks = [(mod or pub) for (pub, mod) in page_dates.values() if (mod or pub)]
            if checks and len(checks) == len(urls) and all(d < target_date for d in checks):
                break

        return matching

    def extract_article_urls_from_page(self, html_content: str) -> List[str]:
        """
        TODO: 从归档页 / latest 页提取文章 URL 列表
        - 去重
        - 过滤非文章链接
        - 相对路径补全
        """
        soup = BeautifulSoup(html_content, "html.parser")
        urls: List[str] = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            # TODO: implement site-specific filters
            # TODO: normalize to absolute URL
            if href.startswith("https://www.example.com/"):
                if href not in urls:
                    urls.append(href)
        return urls

    def get_article_date(self, url: str) -> Tuple[Optional[date_type], Optional[date_type]]:
        """Fetch single article and return (publish_date, modified_date)."""
        html = self.fetch_page(url, verbose=False)
        if not html:
            return (None, None)
        soup = BeautifulSoup(html, "html.parser")
        publish_date = self._extract_publish_date(soup)
        # TODO: add modified_time extraction if site provides it
        return (publish_date, None)
```

### 按日期批量：4 种常见实现策略（按站点选最省请求的）

1. **RSS feed（强推荐）**
   - 如果站点提供 RSS feed，优先使用 RSS（如 Aeon、Nautilus）
   - 高效、稳定、符合标准
2. **按日归档页（推荐）**
   - 如果站点有 `.../YYYY/MM/DD/` 或 "Daily archive" 页面，优先从归档页直接拿当天 URL（省去逐篇查日期）
3. **/latest（倒序）+ 逐篇查 date + 早停**
   - 适合分页最新流
4. **/latest 单页 + 逐篇查 date**
   - 适合单页最新流

并发与反爬注意：

- 项目 `fetch_page()` 默认每次请求都会 sleep（3–7s），并发线程多时会拖慢但更"礼貌"；新来源如果风控强，建议把 `max_workers` 控制在 3–8。
- 列表页抽 URL 后最好去重，避免重复请求同一文章。

---

## 文件命名与元数据（强约束，影响 importer 入库）

脚本落盘的命名规则是：

- **HTML 文件名**：`YYYY-MM-DD_{source_slug}_{category}_{author}_{title}.html`（各字段会做 sanitize）
- **JSON 元数据**：同名 `.json`，包含：
  - `date/category/author/source/title/url/original_file/translated_file`

新增来源请确保：

- `get_source_slug()` 唯一且稳定（否则 importer 对"新格式文件名"的解析会误判）
- `extract_category()` 返回值不要是空；若实在提不出，返回站点名或 domain

---

## 新增来源的接入步骤 Checklist（做完这几步就能跑起来）

### 合法合规检查（必须，第一步）

- **检查官方 API**
  - 搜索目标站点是否提供官方 API
  - 如有，优先使用官方 API
- **检查访问要求**
  - 确认内容是否需要订阅/会员/登录
  - 如需，确认是否有合法途径获得授权
  - **如无合法途径，不得实现该 scraper**
- **阅读服务条款**
  - 阅读并理解目标站点的服务条款
  - 确保实现方式符合条款要求

### 单篇导入（必须）

- 在 `app/services/scrapers/` 新增 `xxx.py`（类名建议 `XxxScraper`）
- 在 `app/services/scrapers/__init__.py`：
  - import 新 scraper
  - 把实例加入 `SCRAPERS` 列表（确保 `get_scraper_for_url()` 能选中）
- （可选但推荐）在 `app/services/importer.py` 的 `parse_filename_for_import()` 里，把你的 `source_slug` 加到 `known_sources`：
  - 这样即使未来某些 HTML/JSON 缺失 URL，也能仅靠文件名正确解析出 `source_slug`
- 运行脚本（示例）：
  - `python scripts/extract_articles_by_date.py --url "<article_url>" --output-dir data/html/en --zh-dir data/html/zh --translate`
  - **若目标站点存在访问控制：必须通过合法途径获得授权；没有合法途径则应在抓取日志中清晰提示并跳过**

### 单日批量导入（必须）

当前"按日期找 URL 列表"的逻辑在 `scripts/extract_articles_by_date.py` 里支持 **Aeon 和 Nautilus**。

**重要**：当前项目的 **scheduled job（定时任务）仅支持 Aeon 和 Nautilus**。其他来源需要手动触发或单独配置。

新增来源要支持 daily batch，请做其中一种：

- **推荐（最贴合现状）**：在你的 scraper 里实现 `find_articles_by_date(target_date, ...) -> list[str]`，然后在脚本里把该来源加入"按日期搜索"的流程。
- **更通用（未来可重构）**：把"按日期找 URL 列表"抽象成统一接口/注册表（本文只记录现状与建议，不在此实现）。

---

## 待新增站点清单（写 scraper 前先做的"站点侦察"）

下面这些站点已列入未来新增来源。建议每个站点先做 10 分钟侦察，回答两件事：

1) **单篇页面是否包含 JSON-LD `NewsArticle`（含 headline/datePublished/author/articleBody）？**
2) **是否存在稳定的"按日归档/最新列表/RSS feed"入口，用于单日批量？**
3) **是否有 paywall/访问限制？如有，是否有合法访问方式（官方 API、订阅等）？**

建议记录字段：

- 域名与 URL 规范（是否 `www`、是否多语言路径）
- 文章 URL pattern（能否从 URL 直接解析日期/栏目）
- daily 入口候选（archive / latest / rss / sitemap）
- paywall 情况与是否能从 JSON-LD/JS 抽出正文（**仅限公开数据**）
- **是否有官方 API 可用（优先）**
- **访问是否需要授权（如需要，确认合法途径）**

站点列表：

- Aeon — `aeon.co` ✅（已实现，支持 scheduled job）
- Nautilus — `nautil.us` ✅（已实现，支持 scheduled job）
- Wired — `wired.com`
- The Economist — `economist.com`
- Harper's Magazine — `harpers.org`
- The New York Review of Books — `nyrb.com`
- The Paris Review — `theparisreview.org`
- London Review of Books — `lrb.co.uk`
- Rest of World — `restofworld.org`
- Foreign Affairs — `foreignaffairs.com`
- The Sunday Long Read — `sundaylongread.com`
- Longreads — `longreads.com`

> 备注：这些站点的 daily 入口形式差异很大（有的偏"杂志期刊归档"，有的偏"最新流"，有的依赖 newsletter/RSS）。优先选择"按日归档页或 RSS"来减少请求量与反爬风险。**更重要的是，在实现前必须确认是否有合法访问方式。**

### 快速定位 daily 入口的实用技巧（不依赖猜 URL）

- **优先找 RSS/Atom**：
  - 打开站点首页或栏目页，查看 `<head>` 是否有类似：
    - `<link rel="alternate" type="application/rss+xml" href="...">`
    - `<link rel="alternate" type="application/atom+xml" href="...">`
  - 常见 RSS 入口命名（仅作线索，不保证每站都有）：`/feed`、`/rss`、`/rss.xml`、`/feed.xml`、`/atom.xml`
- **找"archive / past issues / latest / today"**：
  - 期刊型（Economist/LRB/NYRB/Harper's 等）经常按"期/刊期"归档，而不是按自然日；这类站点做"单日批量"时通常需要先定义"当天对应的 issue"口径，或退而求其次用 RSS/最新流按 `datePublished` 过滤。
- **确认是否可用 requests 直抓**：
  - 若页面严重依赖 JS 渲染或有强风控（Cloudflare/强登录），优先寻找：
    - 官方 API（最优先）
    - AMP/print 版本（有些站点提供 `amp` / `print` / `?output=1` 风格的轻页面）
    - JSON-LD 或页面内初始数据（`__NEXT_DATA__`、`__APOLLO_STATE__` 等）中是否含正文（**仅限公开数据**）
- **检查 paywall 和访问要求**：
  - 确认内容是否需要订阅/会员/登录
  - 如有，确认是否有合法途径获得授权
  - **如无合法途径，不得实现该 scraper**
