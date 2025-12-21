"""New Yorker extraction/translation pipeline.

核心流程：
- DOM 剥离：找到正文容器，给需要翻译的块级文本节点打 data-translate-id。
- 序列化：将纯文本抽取成 JSON list（id + text），保留顺序。
- 上下文感知翻译：先做风格解析，再按批次翻译 JSON。
- 反序列化注入：按 id 把译文写回原 DOM，保持布局与媒体位置不变。
"""

import json
import logging
import os
import random
import re
import time
from typing import Dict, List, Optional, Sequence, Tuple

from bs4 import BeautifulSoup, Tag

try:
    from google import genai

    GEMINI_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    GEMINI_AVAILABLE = False

logger = logging.getLogger(__name__)
# Ensure this module logs even when called from standalone scripts.
logger.setLevel(logging.INFO)


def _ensure_logger_handlers() -> None:
    """Attach handlers if this logger has none (handles scripts with propagate=False)."""
    if logger.handlers:
        return

    # Try known script/app loggers first
    for name in ("extract_articles", "app.routers.articles", "app"):
        cand = logging.getLogger(name)
        if cand.handlers:
            for h in cand.handlers:
                logger.addHandler(h)
            logger.propagate = False
            return

    # If root has handlers, allow propagation
    root = logging.getLogger()
    if root.handlers:
        logger.propagate = True
        return

    # Fallback: basicConfig
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
# Ensure this module logs at INFO even if caller only configures root at runtime
logger.setLevel(logging.INFO)
# Ensure logging works when called from scripts that don't configure root handlers
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

# --------- Tunables --------- #
STYLE_MODEL_DEFAULT = "gemini-3-pro-preview"
TRANSLATE_MODEL_DEFAULT = "gemini-3-pro-preview"
STYLE_SAMPLE_CHARS = 8000  # 用于风格分析的字符上限
CHUNK_CHAR_LIMIT = 15000  # 每个翻译批次的字符上限

# Debug flag: 跳过 Gemini 翻译，使用 placeholder 中文（用于测试排版）
# 设置为 True 时跳过 Gemini API 调用，使用占位符中文测试排版
SKIP_GEMINI_TRANSLATION = True  # 手动修改为 True 以启用调试模式

# 只翻译这些块级节点，忽略脚注/广告等噪音
TARGET_TAGS = ("p", "h1", "h2", "h3", "h4", "h5", "h6", "figcaption", "li")
SKIP_CLASS_KEYWORDS = (
    "rubric",
    "newsletter",
    "subscribe",
    "paywall",
    "promo",
    "related",
    "footer",
    "comment",
    "credit",
    "caption__credit",
    "ad",
)


# --------- Public API --------- #
def translate_newyorker_html(
    html_content: str,
    api_key: Optional[str] = None,
    style_model: str = STYLE_MODEL_DEFAULT,
    translate_model: str = TRANSLATE_MODEL_DEFAULT,
    style_sample_chars: int = STYLE_SAMPLE_CHARS,
    chunk_char_limit: int = CHUNK_CHAR_LIMIT,
) -> Optional[str]:
    """End-to-end pipeline: extract -> style -> translate -> inject.

    Returns translated full HTML (same DOM结构) or None on failure.
    
    If SKIP_GEMINI_TRANSLATION is set, uses placeholder Chinese text instead.
    """
    _ensure_logger_handlers()
    logger.info("translate_newyorker_html called. SKIP_GEMINI_TRANSLATION = %s", SKIP_GEMINI_TRANSLATION)
    
    try:
        logger.debug("Calling extract_content_for_translation...")
        soup, payload = extract_content_for_translation(html_content)
        logger.info("Extracted %d text nodes from HTML.", len(payload) if payload else 0)
        if not payload:
            logger.warning("No translatable content found in HTML.")
            if SKIP_GEMINI_TRANSLATION:
                logger.info("No payload but placeholder mode active; returning original HTML.")
                return html_content
            return None

        # Debug mode: 跳过 Gemini，使用 placeholder
        if SKIP_GEMINI_TRANSLATION:
            logger.info("SKIP_GEMINI_TRANSLATION is enabled. Using placeholder Chinese text for layout testing.")
            logger.info("Extracted %d text nodes for placeholder translation.", len(payload))
            try:
                translated_items = _generate_placeholder_translations(payload)
                logger.info("Generated %d placeholder translations.", len(translated_items))
                translated_html = inject_translations(soup, translated_items)
                logger.info("Successfully injected placeholder translations into DOM. HTML length: %d chars", len(translated_html))
                return translated_html
            except Exception as exc:
                logger.error("Error in placeholder mode: %s", exc, exc_info=True)
            return None
    except Exception as exc:
        logger.error("Error in translate_newyorker_html (extraction/debug mode): %s", exc, exc_info=True)
        return None

    # Normal mode: 使用 Gemini 翻译
    if not GEMINI_AVAILABLE:
        logger.warning("google.genai not installed. Install with: pip install google-genai")
        return None
    
    if api_key is None:
        api_key = os.getenv("GEMINI_API_KEY")
    
    if not api_key:
        logger.warning("GEMINI_API_KEY not set. Skipping translation.")
        return None
    
    client = genai.Client(api_key=api_key)

    style_corpus = build_style_corpus(payload, style_sample_chars)
    style_notes = request_style_profile(client, style_corpus, style_model)

    translated_items = translate_payload_in_batches(
        client=client,
        payload=payload,
        style_notes=style_notes,
        model=translate_model,
        chunk_char_limit=chunk_char_limit,
    )

    if not translated_items:
        logger.error("Translation failed or returned empty payload.")
        return None
        
    translated_html = inject_translations(soup, translated_items)
    return translated_html


# --------- Extraction --------- #
def extract_content_for_translation(html_content: str) -> Tuple[BeautifulSoup, List[Dict[str, str]]]:
    """Parse HTML, locate article root, mark target nodes with ids, and serialize text."""
    soup = BeautifulSoup(html_content, "html.parser")
    article_root = _find_article_root(soup)

    if not article_root:
        logger.warning("Could not locate likely article container; using <body> as fallback.")
        article_root = soup.body or soup

    payload: List[Dict[str, str]] = []
    node_id = 0

    def collect_nodes(root: Tag, start_id: int) -> Tuple[List[Dict[str, str]], int]:
        collected: List[Dict[str, str]] = []
        idx = start_id
        for tag in root.find_all(TARGET_TAGS):
            if _should_skip(tag):
                continue
            text = tag.get_text(strip=True)
            if not text:
                continue
            tag["data-translate-id"] = str(idx)
            collected.append(
                {
                    "id": str(idx),
                    "text": text,
                    "tag": tag.name,
                }
            )
            idx += 1
        return collected, idx

    payload, node_id = collect_nodes(article_root, node_id)

    if not payload:
        logger.info("Primary article root yielded 0 nodes; falling back to full-document scan.")
        payload, node_id = collect_nodes(soup, 0)
        logger.info("Fallback full-document scan found %d nodes.", len(payload))

    if not payload:
        logger.warning("Fallback scan still found 0 nodes; running last-resort <p> scan without skip filter.")
        for tag in soup.find_all("p"):
            text = tag.get_text(strip=True)
            if not text:
                continue
            tag["data-translate-id"] = str(node_id)
            payload.append(
                {
                    "id": str(node_id),
                    "text": text,
                    "tag": tag.name,
                }
            )
            node_id += 1
        logger.info("Last-resort scan found %d nodes.", len(payload))

    # Debug aids: total <p> count and first snippet
    total_p = len(soup.find_all("p"))
    logger.debug("Total <p> tags in document: %d", total_p)
    if payload:
        logger.debug("First extracted text snippet: %s", payload[0]["text"][:200])
        logger.debug("First 5 extracted nodes: %s", [{"id": p["id"], "tag": p["tag"], "text_preview": p["text"][:50]} for p in payload[:5]])

    logger.info("Extracted %d text nodes for translation.", len(payload))
    return soup, payload


def _find_article_root(soup: BeautifulSoup) -> Optional[Tag]:
    """Heuristic search for New Yorker body container."""
    candidates: List[Optional[Tag]] = [
        soup.find("article"),
        soup.select_one("main[role=main]"),
        soup.find("main"),
        soup.select_one("div[data-article]"),
        soup.select_one("div[data-content]"),
        soup.find("div", id=re.compile(r"article", re.I)),
        soup.find("div", class_=re.compile(r"article", re.I)),
        soup.find("div", class_=re.compile(r"content", re.I)),
        soup.find("section", class_=re.compile(r"article", re.I)),
        soup.find("section", class_=re.compile(r"body", re.I)),
    ]

    for cand in candidates:
        if cand and len(cand.get_text(strip=True)) > 50:
            return cand

    # Fallback: largest text block
    best: Optional[Tag] = None
    max_len = 0
    for block in soup.find_all(["article", "section", "div"]):
        text_len = len(block.get_text(strip=True))
        if text_len > max_len:
            max_len = text_len
            best = block
    if best:
        return best
    return soup.body or soup


def _should_skip(tag: Tag) -> bool:
    """Check if a tag should be skipped during extraction.
    
    Uses word-boundary matching to avoid false positives (e.g., 'has-dropcap' containing 'ad').
    For 'paywall' class, only skip if it's a short subscription message, not actual article content.
    """
    classes = tag.get("class", [])
    text = tag.get_text(strip=True)
    text_lower = text.lower()
    
    # Special handling for 'paywall' class: only skip if it's a short subscription message
    # New Yorker uses 'paywall' class on actual article paragraphs, not just subscription prompts
    if "paywall" in [c.lower() for c in classes]:
        # Skip only if it's a short message that looks like a subscription prompt
        is_short = len(text) < 100
        is_subscribe_msg = any(keyword in text_lower for keyword in [
            "subscribe", "sign up", "read more", "unlock", "become a subscriber",
            "get unlimited access", "already a subscriber"
        ])
        if is_short and is_subscribe_msg:
            return True
        # Otherwise, it's likely actual article content, don't skip
        # (fall through to check other skip conditions)
    
    # Check each class name individually for exact or prefix/suffix matches
    # This avoids false positives like 'has-dropcap' matching 'ad'
    for class_name in classes:
        class_lower = class_name.lower()
        for keyword in SKIP_CLASS_KEYWORDS:
            # Skip 'paywall' keyword check here since we handled it above
            if keyword == "paywall":
                continue
            # Special handling for 'credit' and 'caption__credit': only skip if it's a short credit line
            # Long text with 'credit' class might be actual content (like image captions)
            if keyword in ("credit", "caption__credit"):
                if len(text) < 30:  # Short credit lines
                    if class_lower == keyword or class_lower.endswith("_" + keyword):
                        return True
                continue
            # Exact match
            if class_lower == keyword:
                return True
            # Match as prefix (e.g., 'ad-banner', 'ad-wrapper')
            if class_lower.startswith(keyword + "-") or class_lower.startswith(keyword + "_"):
                return True
            # Match as suffix (e.g., 'banner-ad', 'wrapper-ad')
            if class_lower.endswith("-" + keyword) or class_lower.endswith("_" + keyword):
                return True
    
    if tag.name == "p" and len(text) < 2:
        return True
    return False


# --------- Style analysis --------- #
def build_style_corpus(payload: Sequence[Dict[str, str]], char_limit: int) -> str:
    """Join text for style analysis, capped to char_limit."""
    parts: List[str] = []
    total = 0
    for item in payload:
        text = item["text"].strip()
        if not text:
            continue
        if total + len(text) > char_limit:
            remaining = max(char_limit - total, 0)
            if remaining > 0:
                parts.append(text[:remaining])
                break
        parts.append(text)
        total += len(text)
    return "\n".join(parts)


def request_style_profile(client: "genai.Client", corpus: str, model: str) -> str:
    """Ask Gemini to summarize the style; fallback to empty string if it fails."""
    if not corpus:
        return ""

    prompt = (
        "你是一位精通中英的资深编辑，熟悉《纽约客》的写作风格。"
        "请阅读以下文章文本片段，总结 3-5 个中文 bullet，描述节奏、句法、口吻、幽默感、叙述视角等。"
        "仅输出风格要点，不要翻译原文。\n\n"
        f"文章片段：\n{corpus}"
    )

    try:
        response_text = _generate_text(client, model, prompt)
        logger.info("Style profile generated.")
        return response_text.strip()
    except Exception as exc:  # pragma: no cover - network path
        logger.warning("Style profile request failed: %s", exc)
        return ""


# --------- Translation --------- #
def translate_payload_in_batches(
    client: "genai.Client",
    payload: Sequence[Dict[str, str]],
    style_notes: str,
    model: str,
    chunk_char_limit: int,
) -> List[Dict[str, str]]:
    """Chunk payload by character budget and translate each batch."""
    batches: List[List[Dict[str, str]]] = []
    current: List[Dict[str, str]] = []
    current_len = 0

    for item in payload:
        item_len = len(item["text"])
        if current and current_len + item_len > chunk_char_limit:
            batches.append(current)
            current = []
            current_len = 0
        current.append(item)
        current_len += item_len
    if current:
        batches.append(current)

    results: List[Dict[str, str]] = []
    for idx, batch in enumerate(batches):
        logger.info("Translating batch %d/%d (size: %d chars).", idx + 1, len(batches), sum(len(i["text"]) for i in batch))
        prompt = _build_translation_prompt(batch, style_notes)
        response_text = _generate_text(client, model, prompt)
        batch_result = _parse_translation_response(response_text)
        if not batch_result:
            raise RuntimeError("Empty translation batch result.")
        results.extend(batch_result)

    return results


def _build_translation_prompt(batch: Sequence[Dict[str, str]], style_notes: str) -> str:
    style_block = style_notes or "保持《纽约客》特有的知性、冷静、长句叙事风格。"
    return (
        "你是《纽约客》中文创译编辑。请先理解整体风格，再按 JSON 翻译。"
        "翻译原则：信达雅，保持长句节奏，避免直译腔，术语前后一致，避免口语化。"
        f"\n\n风格参考（中文要点）：\n{style_block}\n"
        "\n输出要求：\n"
        "- 只输出 JSON list（无 Markdown、无额外解释）。\n"
        '- 每个对象字段：{"id": <string>, "translated": <string>}。\n'
        "- 保留原顺序，id 原样返回。\n"
        "- 只翻译 text 字段内容，别增加或省略节点。\n"
        "\n待翻译 JSON：\n"
        f"{json.dumps(batch, ensure_ascii=False)}"
    )


def _generate_text(client: "genai.Client", model: str, prompt: str) -> str:
    """Call Gemini and normalize text output."""
    response = client.models.generate_content(model=model, contents=prompt)
    if not response:
        raise RuntimeError("Empty response from Gemini.")

    if hasattr(response, "text") and response.text:
        text = response.text
    elif hasattr(response, "candidates") and response.candidates:
        candidate = response.candidates[0]
        parts = getattr(getattr(candidate, "content", None), "parts", None)
        if parts and parts[0].text:
            text = parts[0].text
        else:
            text = str(response)

    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)[-1]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return cleaned.strip()


def _parse_translation_response(raw: str) -> List[Dict[str, str]]:
    """Parse JSON list from model output."""
    cleaned = raw.strip()
    if cleaned.startswith("json"):
        cleaned = cleaned[4:].strip()

    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\[.*\]", cleaned, flags=re.S)
    if match:
        return json.loads(match.group(0))

    raise ValueError("Model response is not valid JSON.")


def _generate_placeholder_translations(payload: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    """Generate placeholder Chinese text for debugging layout.
    
    Returns a list with same structure as real translation, but with placeholder text.
    """
    placeholders = []
    for idx, item in enumerate(payload):
        tag_name = item.get("tag", "p")
        original_len = len(item.get("text", ""))
        
        # 根据标签类型生成不同的 placeholder
        if tag_name.startswith("h"):
            placeholder_text = f"【标题 {idx + 1}】这是占位符中文标题，用于测试排版效果。原始长度：{original_len} 字符。"
        elif tag_name == "figcaption":
            placeholder_text = f"【图片说明 {idx + 1}】这是占位符中文图片说明，用于测试排版效果。原始长度：{original_len} 字符。"
        elif tag_name == "li":
            placeholder_text = f"【列表项 {idx + 1}】这是占位符中文列表项，用于测试排版效果。原始长度：{original_len} 字符。"
        else:
            placeholder_text = f"【段落 {idx + 1}】这是占位符中文段落，用于测试排版效果。原始长度：{original_len} 字符。"
        
        placeholders.append({
            "id": item["id"],
            "translated": placeholder_text
        })
    
    return placeholders


# --------- Injection --------- #
def inject_translations(soup: BeautifulSoup, translated_items: Sequence[Dict[str, str]]) -> str:
    """Write translated text back to DOM using data-translate-id."""
    lookup: Dict[str, str] = {item["id"]: item["translated"] for item in translated_items if "translated" in item}
    nodes = soup.find_all(attrs={"data-translate-id": True})

    logger.debug("Found %d nodes with data-translate-id, lookup has %d items", len(nodes), len(lookup))
    
    replaced = 0
    for node in nodes:
        node_id = node.get("data-translate-id")
        if node_id is None:
            logger.debug("Node has data-translate-id attribute but value is None")
            continue
        if node_id not in lookup:
            logger.debug("Node ID %s not found in lookup", node_id)
            continue
        
        # Store original text for debugging
        original_text = node.get_text(strip=True)
        
        # Clear all children and set new text content
        # This works even if node has nested elements
        node.clear()
        node.append(lookup[node_id])
        del node["data-translate-id"]
        replaced += 1
        
        # Debug: log first few replacements
        if replaced <= 3:
            logger.debug("Replaced node %s: '%s' -> '%s'", node_id, original_text[:50], lookup[node_id][:50])

    logger.info("Injected %d translated nodes back into DOM.", replaced)
    return str(soup)


# --------- Backward compatibility wrappers --------- #
def translate_html_with_gemini(html_content: str, api_key: Optional[str] = None, debug_filename: Optional[str] = None) -> Optional[str]:
    """Legacy entrypoint kept for existing callers."""
    debug_tag = f" [{debug_filename}]" if debug_filename else ""
    try:
        logger.info("%s Dispatching to translate_newyorker_html pipeline.", debug_tag)
        return translate_newyorker_html(html_content, api_key=api_key)
    except Exception as exc:  # pragma: no cover - network path
        logger.error("translate_html_with_gemini failed%s: %s", debug_tag, exc, exc_info=True)
    return None


def translate_html_with_gemini_retry(
    html_content: str,
    api_key: Optional[str] = None,
    max_retries: int = 2,
    filename: Optional[str] = None,
) -> Optional[str]:
    """Retry wrapper compatible with previous interface."""
    _ensure_logger_handlers()
    tag = f" [{filename}]" if filename else ""
    try:
        logger.info("%s translate_html_with_gemini_retry called", tag)
        logger.info("%s Checking SKIP_GEMINI_TRANSLATION flag (current value: %s)", tag, SKIP_GEMINI_TRANSLATION)
        logger.debug("%s HTML content length: %d chars", tag, len(html_content))

        if SKIP_GEMINI_TRANSLATION:
            logger.info("%s SKIP_GEMINI_TRANSLATION is True - will use placeholder mode (no retries needed).", tag)
            result = translate_newyorker_html(html_content, api_key=api_key)
            logger.debug("%s translate_newyorker_html returned: %s, length: %d", tag, type(result).__name__, len(result) if result else 0)
            if result is None:
                logger.error("%s Placeholder translation returned None - check logs above for errors.", tag)
            else:
                logger.info("%s Placeholder translation succeeded, returned HTML length: %d chars", tag, len(result) if result else 0)
            return result

        # Normal mode with retries
        for attempt in range(max_retries + 1):
            start = time.time()
            if attempt:
                delay = random.uniform(5, 12)
                logger.info("%s Retry %d/%d after %.1fs pause.", tag, attempt + 1, max_retries + 1, delay)
                time.sleep(delay)

            logger.info("%s Starting attempt %d/%d.", tag, attempt + 1, max_retries + 1)
            result = translate_newyorker_html(html_content, api_key=api_key)
            elapsed = time.time() - start
            logger.info("%s Attempt %d finished in %.1fs.", tag, attempt + 1, elapsed)
            if result is not None:
                return result

        logger.error("%s Translation failed after %d attempts.", tag, max_retries + 1)
        return None

    except Exception as exc:
        logger.error("%s Unexpected exception in translate_html_with_gemini_retry: %s", tag, exc, exc_info=True)
        return None

