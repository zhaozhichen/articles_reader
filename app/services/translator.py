"""Article extraction/translation pipeline.

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
    from google.genai import types
    GEMINI_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    GEMINI_AVAILABLE = False
    types = None

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
STYLE_MODEL_DEFAULT = "gemini-3-flash-preview"
TRANSLATE_MODEL_DEFAULT = "gemini-3-flash-preview"
STYLE_SAMPLE_CHARS = 10000  # 用于风格分析的字符上限
CHUNK_CHAR_LIMIT = 100000  # 每个翻译批次的字符上限

# Debug flag: 跳过 Gemini 翻译，使用 placeholder 中文（用于测试排版）
# 设置为 True 时跳过 Gemini API 调用，使用占位符中文测试排版
SKIP_GEMINI_TRANSLATION = False  # 手动修改为 True 以启用调试模式

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
    
    # Record start time for total translation duration
    translation_start_time = time.time()
    
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
                logger.debug("About to generate placeholder translations...")
                translated_items = _generate_placeholder_translations(payload)
                logger.info("Generated %d placeholder translations.", len(translated_items))
                logger.debug("About to inject translations into DOM...")
                translated_html = inject_translations(soup, translated_items)
                logger.info("Successfully injected placeholder translations into DOM. HTML length: %d chars", len(translated_html))
                if not translated_html:
                    logger.error("inject_translations returned None or empty string")
                    return None
                
                # Log total translation time for placeholder mode
                translation_duration = time.time() - translation_start_time
                logger.info("Total translation time (placeholder mode): %.2f seconds", translation_duration)
                
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

    # Record time for style analysis
    style_start_time = time.time()
    style_corpus = build_style_corpus(payload, style_sample_chars)
    style_notes = request_style_profile(client, style_corpus, style_model)
    style_duration = time.time() - style_start_time
    logger.info("Style analysis completed in %.2f seconds", style_duration)

    # Record time for translation
    translation_batch_start_time = time.time()
    translated_items = translate_payload_in_batches(
        client=client,
        payload=payload,
        style_notes=style_notes,
        model=translate_model,
        chunk_char_limit=chunk_char_limit,
    )
    translation_batch_duration = time.time() - translation_batch_start_time
    logger.info("Translation batches completed in %.2f seconds", translation_batch_duration)

    if not translated_items:
        logger.error("Translation failed or returned empty payload.")
        return None
        
    translated_html = inject_translations(soup, translated_items)
    
    # Log total translation time (including style analysis and translation)
    total_duration = time.time() - translation_start_time
    logger.info("Total translation time (style analysis + translation): %.2f seconds (style: %.2f s, translation: %.2f s)", 
                total_duration, style_duration, translation_batch_duration)
    
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

    # Additional scan: look for paragraphs that might be in accordion/collapsible components
    # These might not be in the article root but are still part of the article content
    # Also check <div> tags that might contain article content (e.g., div[role="heading"])
    if payload:
        # Check if we're missing some long paragraphs that might be in special containers
        # Scan for <p> tags and <div> tags with substantial text that weren't captured
        existing_texts = {item["text"][:50] for item in payload}  # Use first 50 chars as fingerprint
        initial_count = len(payload)
        
        # Scan <p> tags
        for p in soup.find_all("p"):
            text = p.get_text(strip=True)
            if not text or len(text) < 100:  # Only consider substantial paragraphs
                continue
            text_fingerprint = text[:50]
            if text_fingerprint in existing_texts:
                continue  # Already captured
            
            # Check if it should be skipped
            if _should_skip(p):
                continue
            
            # This is a substantial paragraph that wasn't captured, add it
            p["data-translate-id"] = str(node_id)
            payload.append(
                {
                    "id": str(node_id),
                    "text": text,
                    "tag": p.name,
                }
            )
            node_id += 1
            logger.debug("Found additional paragraph outside article root: %s", text[:100])
        
        # Scan <div> tags that might contain article content
        # Look for divs with role="heading" or divs with substantial text content
        # Be more selective to avoid UI elements and duplicate content
        for div in soup.find_all("div"):
            text = div.get_text(strip=True)
            if not text or len(text) < 200:  # Only consider substantial content (increased threshold)
                continue
            text_fingerprint = text[:50]
            if text_fingerprint in existing_texts:
                continue  # Already captured
            
            # Check if it looks like article content
            # Priority: divs with role="heading" are likely article content
            role = div.get("role", "")
            aria_level = div.get("aria-level", "")
            
            # Skip if it has UI-related classes or is clearly not content
            classes = div.get("class", [])
            class_str = " ".join(classes).lower()
            if any(ui_keyword in class_str for ui_keyword in [
                "button", "icon", "control", "widget", "menu", "nav", "header", "footer",
                "sidebar", "ad", "promo", "newsletter", "subscribe", "social", "share",
                "byline", "rubric", "accreditation"  # These are metadata, not content
            ]):
                continue
            
            # Skip common non-content text patterns
            text_lower = text.lower()
            if any(skip_pattern in text_lower for skip_pattern in [
                "you're reading", "open questions", "new yorker favorites",
                "the best movies", "sign up", "subscribe", "newsletter"
            ]):
                continue
            
            # For divs, be more selective:
            # 1. Accept divs with role="heading" (these are likely article headings/paragraphs)
            # 2. Accept divs with substantial text (200+ chars) that don't look like UI
            # 3. Skip very long divs that might be the entire page wrapper
            # 4. Only accept divs that are likely article content (not metadata/UI)
            if role == "heading":
                # Divs with role="heading" are likely article content
                if _should_skip(div):
                    continue
                div["data-translate-id"] = str(node_id)
                payload.append(
                    {
                        "id": str(node_id),
                        "text": text,
                        "tag": div.name,
                    }
                )
                node_id += 1
                logger.debug("Found additional div (role=heading) outside article root: %s", text[:100])
            elif len(text) >= 200 and len(text) < 5000:
                # For other divs, be very selective - only if they look like article paragraphs
                # Check if it should be skipped
                if _should_skip(div):
                    continue
                
                # Additional check: skip if it contains mostly links or looks like navigation
                links = div.find_all("a")
                if links and len(links) > len(text) / 50:  # Too many links relative to text
                    continue
                
                # This is a substantial div that might contain article content, add it
                div["data-translate-id"] = str(node_id)
                payload.append(
                    {
                        "id": str(node_id),
                        "text": text,
                        "tag": div.name,
                    }
                )
                node_id += 1
                logger.debug("Found additional div with content outside article root: %s", text[:100])
        
        additional_count = len(payload) - initial_count
        if additional_count > 0:
            logger.info("Additional scan found %d more nodes outside article root.", additional_count)

    # Debug aids: total <p> count and first snippet
    total_p = len(soup.find_all("p"))
    logger.debug("Total <p> tags in document: %d", total_p)
    if payload:
        logger.debug("First extracted text snippet: %s", payload[0]["text"][:200])
        logger.debug("First 5 extracted nodes: %s", [{"id": p["id"], "tag": p["tag"], "text_preview": p["text"][:50]} for p in payload[:5]])

    logger.info("Extracted %d text nodes for translation.", len(payload))
    return soup, payload


def _find_article_root(soup: BeautifulSoup) -> Optional[Tag]:
    """Heuristic search for article body container."""
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
    # Some sites use 'paywall' class on actual article paragraphs, not just subscription prompts
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

    prompt = f"""
请阅读以下文章文本片段，总结 3-5 个中文 bullet，描述节奏、句法、口吻、幽默感、叙述视角等。

请重点关注：
1. 【语域定位】：是像"知乎高赞回答"那样通俗，还是像"三联生活周刊"那样书卷气？
2. 【句式重构】：长难句应该彻底切碎，还是保留一定的缠绕感？
3. 【关键词映射】：如果有专有名词或特定梗，指出其中文对应调性。

仅输出这 3 点策略（中文），不要翻译原文，不要废话。

文章片段：
{corpus}
"""

    try:
        # Use GenerateContentConfig for better control
        if types and hasattr(types, 'GenerateContentConfig'):
            config = types.GenerateContentConfig(
                temperature=0.5,  # Slightly higher for creative analysis
                system_instruction="你是一位精通中英的资深编辑，擅长分析英文文章的写作风格。"
            )
            response_text = _generate_text(client, model, prompt, config=config)
        else:
            # Fallback for older SDK versions
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
        # Log full prompt for debugging
        # logger.info("=== Full Translation Prompt (Batch %d/%d) ===", idx + 1, len(batches))
        # logger.info("%s", prompt)
        # logger.info("=== End of Prompt ===")
        
        # Use GenerateContentConfig with forced JSON output
        if types and hasattr(types, 'GenerateContentConfig'):
            config = types.GenerateContentConfig(
                temperature=0.3,  # Lower temperature for stable JSON output
                top_p=0.95,
                response_mime_type="application/json",  # Force JSON output
                system_instruction="你是一位专业的中文创译编辑和非虚构写作专家。你的任务不是逐字翻译，而是依据英文原意进行中文重写（Re-writing）。"
            )
            response_text = _generate_text(client, model, prompt, config=config)
        else:
            # Fallback for older SDK versions
            response_text = _generate_text(client, model, prompt)
        
        # Log raw response for debugging
        # logger.info("=== Raw Gemini Response (Batch %d/%d) ===", idx + 1, len(batches))
        # logger.info("Response length: %d chars", len(response_text))
        # logger.info("First 500 chars: %s", response_text[:500])
        # logger.info("Last 500 chars: %s", response_text[-500:] if len(response_text) > 500 else response_text)
        # logger.info("=== End of Raw Response ===")
        batch_result = _parse_translation_response(response_text)
        if not batch_result:
            raise RuntimeError("Empty translation batch result.")
        results.extend(batch_result)

    return results


def _build_translation_prompt(batch: Sequence[Dict[str, str]], style_notes: str) -> str:
    """Build translation prompt with style guide."""
    style_block = style_notes or "保持原文的写作风格和语调，包括句法结构、叙述节奏和语言特色。"
    return f"""
请参考【翻译策略】，将输入的 JSON 内容转换为地道的中文。

核心原则（必须严格执行）：
1. 【反翻译腔】：严禁使用"被...所..."、"当...的时候"、"...之一"等生硬的翻译体。
2. 【流水句重构】：把英文的复杂从句（Clause）拆解为中文的短句或流水句。
3. 【词汇渲染】：用词要精准且有质感。

【翻译策略】：
{style_block}

输出格式要求：
- 仅输出纯净的 JSON List。
- 严禁包含 Markdown 标记。
- id 必须与原文严格一致。
- 每个对象必须包含字段：{{"id": <string>, "translated": <string>, "tag": <string>}}
- 翻译后的中文内容放在 "translated" 字段中，不要使用 "text" 字段。

待处理数据：
{json.dumps(batch, ensure_ascii=False)}
"""


def _generate_text(client: "genai.Client", model: str, prompt: str, config=None) -> str:
    """Call Gemini and normalize text output.
    
    Args:
        client: Gemini client instance
        model: Model name
        prompt: Prompt text
        config: Optional GenerateContentConfig (for new SDK)
    """
    if config:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=config
        )
    else:
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
    else:
        text = str(response)

    cleaned = text.strip()
    # Only clean markdown if not using forced JSON output
    if config and hasattr(config, 'response_mime_type') and config.response_mime_type == "application/json":
        # With forced JSON, response should already be clean JSON
        return cleaned
    else:
        # Clean markdown code blocks for text responses
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```", 2)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        return cleaned.strip()


def _parse_translation_response(raw: str) -> List[Dict[str, str]]:
    """Parse JSON list from model output and normalize field names."""
    cleaned = raw.strip()
    
    # Remove markdown code blocks if present
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:].strip()
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:].strip()
    
    if cleaned.startswith("json"):
        cleaned = cleaned[4:].strip()

    if cleaned.endswith("```"):
        cleaned = cleaned[:-3].strip()

    # Try direct JSON parse
    parsed = None
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.debug("Direct JSON parse failed: %s", e)
        logger.debug("Cleaned text (first 500 chars): %s", cleaned[:500])
        pass

    # Try to find JSON array in the text if direct parse failed
    if parsed is None:
        match = re.search(r"\[.*\]", cleaned, flags=re.S)
        if match:
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError as e:
                logger.debug("JSON array extraction failed: %s", e)
                logger.debug("Matched text (first 500 chars): %s", match.group(0)[:500])
                pass

    if parsed is None:
        # Log the full response for debugging
        logger.error("Failed to parse JSON from response. Full response (first 1000 chars): %s", raw[:1000])
        logger.error("Cleaned text (first 1000 chars): %s", cleaned[:1000])
        raise ValueError("Model response is not valid JSON.")
    
    # Normalize field names: if response has "text" field instead of "translated", rename it
    normalized = []
    for item in parsed:
        normalized_item = dict(item)
        # If item has "text" but not "translated", rename "text" to "translated"
        if "text" in normalized_item and "translated" not in normalized_item:
            normalized_item["translated"] = normalized_item.pop("text")
        normalized.append(normalized_item)
    
    return normalized


def _generate_placeholder_translations(payload: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    """Generate placeholder Chinese text for debugging layout.
    
    Returns a list with same structure as real translation, but with placeholder text.
    """
    placeholders = []
    for idx, item in enumerate(payload):
        tag_name = item.get("tag", "p")
        original_text = item.get("text", "")
        original_len = len(original_text)
        
        # 提取前五个词和最后五个词
        words = original_text.split()
        first_five = " ".join(words[:5]) if len(words) >= 5 else " ".join(words)
        last_five = " ".join(words[-5:]) if len(words) >= 5 else " ".join(words)
        
        # 根据标签类型生成不同的 placeholder
        if tag_name.startswith("h"):
            placeholder_text = f"【标题 {idx + 1}】这是占位符中文标题，用于测试排版效果。原始长度：{original_len} 字符。开头：{first_five} ... 结尾：{last_five}"
        elif tag_name == "figcaption":
            placeholder_text = f"【图片说明 {idx + 1}】这是占位符中文图片说明，用于测试排版效果。原始长度：{original_len} 字符。开头：{first_five} ... 结尾：{last_five}"
        elif tag_name == "li":
            placeholder_text = f"【列表项 {idx + 1}】这是占位符中文列表项，用于测试排版效果。原始长度：{original_len} 字符。开头：{first_five} ... 结尾：{last_five}"
        else:
            placeholder_text = f"【段落 {idx + 1}】这是占位符中文段落，用于测试排版效果。原始长度：{original_len} 字符。开头：{first_five} ... 结尾：{last_five}"
        
        placeholders.append({
            "id": item["id"],
            "tag": item.get("tag", ""),  # Preserve tag info for meta tag replacement
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
    skipped_ids = []
    for node in nodes:
        node_id = node.get("data-translate-id")
        if node_id is None:
            logger.debug("Node has data-translate-id attribute but value is None")
            continue
        if node_id not in lookup:
            skipped_ids.append(node_id)
            logger.debug("Node ID %s not found in lookup", node_id)
            continue
        
        # Store original text for debugging
        original_text = node.get_text(strip=True)
        
        # Preserve images and other non-text elements before clearing
        # Find all img, picture, figure, and other media elements within this node
        # We need to preserve ALL media elements, not just direct children
        preserved_elements = []
        media_tags = ['img', 'picture', 'figure', 'video', 'audio', 'iframe', 'svg']
        
        # Find all media elements within this node
        for media_elem in node.find_all(media_tags):
            # Check if this element is actually within the current node (not just a descendant)
            # by walking up the tree to see if we reach the node
            current = media_elem.find_parent()
            is_within_node = False
            while current:
                if current == node:
                    is_within_node = True
                break
                current = current.find_parent()
            
            if is_within_node:
                # Extract the entire media container (picture, figure, etc.) if it exists
                # Otherwise extract the media element itself
                container = None
                for tag_name in ['picture', 'figure']:
                    container = media_elem.find_parent(tag_name)
                    if container:
                        # Check if container is within node
                        container_parent = container.find_parent()
                        while container_parent:
                            if container_parent == node:
                                preserved_elements.append(container.extract())
                                break
                            container_parent = container_parent.find_parent()
                        if container_parent == node:
                            break
                    if container and container in preserved_elements:
                        break
                
                # If no container was found, extract the element itself
                if not container or container not in preserved_elements:
                    # Make sure we haven't already extracted a parent
                    already_extracted = False
                    for preserved in preserved_elements:
                        if media_elem in preserved.find_all(media_tags):
                            already_extracted = True
                            break
                    if not already_extracted:
                        preserved_elements.append(media_elem.extract())
        
        # Clear all children and set new text content
        # This works even if node has nested elements
        try:
            node.clear()
            node.append(lookup[node_id])
            
            # Re-insert preserved media elements after the text
            for elem in preserved_elements:
                node.append(elem)
            
            del node["data-translate-id"]
            replaced += 1
            
            # Debug: log first few replacements (especially h1 titles)
            if replaced <= 5 or node.name == "h1":
                logger.info("Replaced node %s (%s): '%s' -> '%s'", node_id, node.name, original_text[:50], lookup[node_id][:50])
                if preserved_elements:
                    logger.debug("Preserved %d media element(s) in node %s", len(preserved_elements), node_id)
        except Exception as exc:
            logger.error("Error replacing node %s (%s): %s", node_id, node.name, exc, exc_info=True)
            continue

    if skipped_ids:
        logger.warning("Skipped %d nodes not found in lookup: %s", len(skipped_ids), skipped_ids[:10])
    logger.info("Injected %d translated nodes back into DOM.", replaced)
    
    # Also replace title in meta tags (og:title, twitter:title, title tag)
    # Find the first h1 translation (usually ID 0) to use as the page title
    title_translation = None
    for item in translated_items:
        # Check if this is an h1 translation (by tag field or by checking ID 0 which is usually h1)
        if item.get("tag") == "h1" and "translated" in item:
            title_translation = item["translated"]
            break
        # Fallback: if no tag field, check if ID is "0" (usually the h1)
        elif item.get("id") == "0" and "translated" in item:
            # Verify it's actually an h1 by checking the original payload structure
            # For now, assume ID 0 is h1 (this is the common case)
            title_translation = item["translated"]
            logger.debug("Found title translation by ID 0 fallback")
            break
                    
    if title_translation:
        # Replace <title> tag
        title_tag = soup.find("title")
        if title_tag:
            # Preserve any " | " suffix (e.g., " | The New Yorker", " | The New York Times")
            original_title = title_tag.get_text()
            if " | " in original_title:
                suffix = " | " + original_title.split(" | ", 1)[1]
                title_tag.string = f"{title_translation}{suffix}"
            else:
                title_tag.string = title_translation
            logger.debug("Replaced <title> tag with translated title")
        
        # Replace og:title meta tag
        og_title = soup.find("meta", property="og:title")
        if og_title:
            og_title["content"] = title_translation
            logger.debug("Replaced og:title meta tag")
        
        # Replace twitter:title meta tag
        twitter_title = soup.find("meta", attrs={"name": "twitter:title"})
        if twitter_title:
            twitter_title["content"] = title_translation
            logger.debug("Replaced twitter:title meta tag")
    
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

