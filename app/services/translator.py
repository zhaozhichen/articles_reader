"""Translation service for article content."""
import os
import random
import time
import sys
from typing import Optional
from bs4 import BeautifulSoup

try:
    from google import genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False


def translate_html_with_gemini(html_content: str, api_key: Optional[str] = None) -> Optional[str]:
    """Translate only the article body content to Simplified Chinese using Gemini 3 Pro.
    
    Only translates the main article body, keeping navigation, scripts, styles, etc. in English.
    
    Args:
        html_content: Original HTML content
        api_key: Gemini API key (if None, uses GEMINI_API_KEY env var)
    
    Returns:
        Translated HTML content with only body translated, or None if translation fails
    """
    if not GEMINI_AVAILABLE:
        print("  Warning: google.genai not installed. Install with: pip install google-genai", file=sys.stderr)
        return None
    
    # Get API key (the client gets it from GEMINI_API_KEY env var automatically)
    # But we can check if it's set
    if api_key is None:
        api_key = os.getenv('GEMINI_API_KEY')
    
    if not api_key:
        print("  Warning: GEMINI_API_KEY not set. Skipping translation.", file=sys.stderr)
        return None
    
    try:
        # Extract article body - this should be done by the caller, but we'll try to find it
        # The caller should pass body_html separately, but for backward compatibility we extract here
        print("    Extracting article body content...", file=sys.stderr)
        body_html, body_element = _extract_article_body(html_content)
        
        if not body_html or not body_element:
            print("  Warning: Could not find article body content", file=sys.stderr)
            return None
        
        body_size = len(body_html)
        print(f"    Found article body (size: {body_size} chars)", file=sys.stderr)
        
        # Maximum size for single translation
        MAX_SINGLE_TRANSLATION = 200000
        
        # Check if body is too long to translate
        if body_size > MAX_SINGLE_TRANSLATION:
            print(f"    Article body is too long ({body_size:,} chars), skipping translation and showing placeholder", file=sys.stderr)
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Find the body element to replace
            original_body = None
            for selector in [('article', {}), ('.body__container', {}), ('.container--body-inner', {}), ('main', {})]:
                if selector[0].startswith('.'):
                    original_body = soup.select_one(selector[0])
                else:
                    tag_name = selector[0].split('.')[-1] if '.' in selector[0] else selector[0]
                    original_body = soup.find(tag_name, selector[1])
                if original_body:
                    break
            
            if original_body:
                # Create placeholder message with size information
                placeholder_html = f'<div style="padding: 2rem; text-align: center; font-family: Arial, sans-serif;"><p style="font-size: 18px; color: #666;">文章过长，无法翻译</p><p style="font-size: 14px; color: #999; margin-top: 1rem;">Article too long to translate, size: {body_size:,} characters</p></div>'
                placeholder_soup = BeautifulSoup(placeholder_html, 'html.parser')
                
                # Replace body content with placeholder
                original_body.clear()
                original_body.append(placeholder_soup.find('div'))
                
                return str(soup)
            else:
                # If we can't find the body, return original HTML with a note
                print("  Warning: Could not locate body element for placeholder insertion", file=sys.stderr)
                return html_content
        
        # The client gets the API key from the environment variable `GEMINI_API_KEY`
        client = genai.Client()
        
        # Create prompt for translation
        prompt = """请将以下HTML内容翻译成简体中文。

翻译流程：
第一步：仔细阅读全文
- 先完整阅读整篇文章，理解文章的主题、内容和结构
- 分析文章的行文风格（正式、轻松、学术、新闻等）
- 识别文章的语气和语调（严肃、幽默、批判、客观等）
- 注意文章的文体特征（叙述、议论、描写等）
- 理解文章的语境和背景

第二步：进行翻译
- 基于对文章风格和语气的理解，进行翻译
- 确保翻译非常流畅，完全符合现代汉语的写作习惯
- 使用自然、地道的现代汉语表达
- 避免生硬的直译，要意译为主，确保可读性
- 保持原文的风格和语气特征
- 专业术语要准确，但表达要符合中文习惯

技术性要求（非常重要）：
1. **只翻译文本内容**，保留所有HTML标签、属性和结构完全不变
2. **保留所有元素**：包括所有div、section、article、picture、img、style、script等元素
3. **保留所有属性**：包括class、id、style、data-*、src、srcset等所有属性
4. **保留所有CSS**：包括内联样式（style属性）和所有CSS类名
5. **保留所有图片和媒体**：不要移动、删除或修改任何图片、视频等媒体元素
6. **保留定位信息**：保持所有position、z-index、absolute、relative等CSS定位属性
7. **不翻译代码、URL或技术属性**：只翻译可见的文本内容
8. **保持HTML结构完全不变**：元素顺序、嵌套关系、空白字符都要保持原样
9. 返回完整的翻译后的HTML（只包含这个body部分的HTML）

特别注意：
- 对于有position:absolute或z-index的元素，必须完全保留其HTML结构和所有属性
- 图片元素（img、picture）及其所有父元素必须完整保留
- 所有style属性和CSS类必须原样保留

请开始翻译：

HTML内容：
""" + body_html
        
        # Generate translation using gemini-3-pro-preview
        print(f"    Sending article body to Gemini (size: {len(body_html)} chars)...", file=sys.stderr)
        
        response = client.models.generate_content(
            model="gemini-3-pro-preview",
            contents=prompt
        )
        
        # Check if response is valid
        if not response:
            print("  Error: Empty response from Gemini API", file=sys.stderr)
            return None
        
        # Get text from response - handle different response formats
        translated_html = None
        try:
            if hasattr(response, 'text') and response.text:
                translated_html = response.text
            elif hasattr(response, 'candidates') and len(response.candidates) > 0:
                candidate = response.candidates[0]
                if hasattr(candidate, 'content'):
                    if hasattr(candidate.content, 'parts') and len(candidate.content.parts) > 0:
                        translated_html = candidate.content.parts[0].text
                    elif hasattr(candidate.content, 'text'):
                        translated_html = candidate.content.text
            else:
                # Try to convert response to string
                translated_html = str(response)
        except Exception as e:
            print(f"  Error extracting text from response: {e}", file=sys.stderr)
            print(f"  Response type: {type(response)}", file=sys.stderr)
            if hasattr(response, '__dict__'):
                print(f"  Response attributes: {list(response.__dict__.keys())}", file=sys.stderr)
            return None
        
        if not translated_html or len(translated_html.strip()) == 0:
            print("  Error: Translation result is empty", file=sys.stderr)
            return None
        
        print(f"    Received translation (size: {len(translated_html)} chars)", file=sys.stderr)
        
        # Clean up the response (sometimes Gemini adds markdown formatting)
        # Remove markdown code blocks if present
        if translated_html.startswith('```html'):
            translated_html = translated_html[7:]
        elif translated_html.startswith('```'):
            translated_html = translated_html[3:]
        if translated_html.endswith('```'):
            translated_html = translated_html[:-3]
        translated_html = translated_html.strip()
        
        # Verify we got substantial HTML content
        if len(translated_html) < len(html_content) * 0.1:
            print(f"  Warning: Translation seems too short ({len(translated_html)} vs original {len(html_content)} chars)", file=sys.stderr)
            print(f"  This might indicate the translation was truncated or incomplete", file=sys.stderr)
        
        # Verify basic HTML structure
        if not translated_html or len(translated_html.strip()) < 100:
            print(f"  Warning: Translation result seems too short", file=sys.stderr)
            return None
        
        # Replace the original body with translated body in the full HTML
        soup = BeautifulSoup(html_content, 'html.parser')
        translated_body_soup = BeautifulSoup(translated_html, 'html.parser')
        
        # Use the body_element we found earlier (passed as a reference)
        # We need to find it again in the soup since we created a new soup object
        original_body = None
        for selector in [('article', {}), ('.body__container', {}), ('.container--body-inner', {}), ('main', {})]:
            if selector[0].startswith('.'):
                original_body = soup.select_one(selector[0])
            else:
                tag_name = selector[0].split('.')[-1] if '.' in selector[0] else selector[0]
                original_body = soup.find(tag_name, selector[1])
            if original_body:
                break
        
        if original_body:
            # Replace the original body content with translated content
            # Use a safer method: replace the inner HTML while preserving the element itself
            translated_root = translated_body_soup.find()
            if translated_root:
                # Get the inner HTML of translated root (preserves all structure)
                translated_inner = ''.join(str(child) for child in translated_root.children)
                # Replace inner content while preserving the original element's attributes
                original_body.clear()
                # Parse and append the translated content
                inner_soup = BeautifulSoup(translated_inner, 'html.parser')
                for child in inner_soup.children:
                    original_body.append(child)
            else:
                # Fallback: use the whole translated soup
                original_body.clear()
                for child in list(translated_body_soup.children):
                    original_body.append(child)
            
            print(f"    Replaced article body with translated version", file=sys.stderr)
            # Return the modified full HTML
            return str(soup)
        else:
            # If we can't find the body element, try to use body_element directly
            if body_element:
                # Create a new soup from original and replace
                soup = BeautifulSoup(html_content, 'html.parser')
                # Find the element by its position or attributes
                body_element.clear()
                translated_root = translated_body_soup.find()
                if translated_root:
                    for child in list(translated_root.children):
                        body_element.append(child)
                return str(soup)
            else:
                print("  Warning: Could not locate body element for replacement", file=sys.stderr)
                return None
        
    except Exception as e:
        print(f"  Error translating with Gemini: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return None


def translate_html_with_gemini_retry(html_content: str, api_key: Optional[str] = None, max_retries: int = 2) -> Optional[str]:
    """Translate HTML with retry mechanism.
    
    Args:
        html_content: Original HTML content
        api_key: Gemini API key (if None, uses GEMINI_API_KEY env var)
        max_retries: Maximum number of retries (default: 2, total attempts: 3)
    
    Returns:
        Translated HTML content, or None if all attempts fail
    """
    for attempt in range(max_retries + 1):  # 0, 1, 2 = 3 attempts total
        if attempt > 0:
            delay = random.uniform(5, 15)  # Wait 5-15 seconds before retry
            print(f"    Retry attempt {attempt}/{max_retries} after {delay:.1f}s delay...", file=sys.stderr)
            time.sleep(delay)
        
        result = translate_html_with_gemini(html_content, api_key)
        if result is not None:
            if attempt > 0:
                print(f"    Translation succeeded on attempt {attempt + 1}", file=sys.stderr)
            return result
        else:
            if attempt < max_retries:
                print(f"    Translation failed on attempt {attempt + 1}/{max_retries + 1}, will retry...", file=sys.stderr)
            else:
                print(f"    Translation failed after {max_retries + 1} attempts, giving up", file=sys.stderr)
    
    return None


def _extract_article_body(html_content: str) -> tuple:
    """Extract the main article body content from HTML.
    
    This is a helper function for backward compatibility.
    Scrapers should implement their own extract_body method.
    
    Returns a tuple of (body_html, body_element) where body_html is the HTML
    of the body section and body_element is the BeautifulSoup element.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Try to find article body using common selectors
    body_element = None
    
    # Try different selectors for article body
    selectors = [
        ('article', {}),
        ('.body__container', {}),
        ('.container--body-inner', {}),
        ('main', {}),
        ('[class*="body"]', {}),
        ('[class*="article"]', {}),
        ('[class*="content"]', {}),
    ]
    
    for selector, attrs in selectors:
        if selector.startswith('['):
            # Attribute selector
            body_element = soup.select_one(selector)
        else:
            body_element = soup.find(selector.split('.')[-1] if '.' in selector else selector, attrs)
        
        if body_element:
            # Check if it has substantial text content
            text_content = body_element.get_text(strip=True)
            if len(text_content) > 200:  # Has meaningful content
                break
    
    if not body_element:
        # Fallback: find the largest text-containing div
        all_divs = soup.find_all(['div', 'section', 'article'])
        max_text_length = 0
        for div in all_divs:
            text = div.get_text(strip=True)
            if len(text) > max_text_length:
                max_text_length = len(text)
                body_element = div
        
        if max_text_length < 200:
            return None, None
    
    return str(body_element), body_element
