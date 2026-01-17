"""Xiaoyuzhou podcast processing services: audio download, transcription, and summary generation."""
import os
import re
import time
import logging
from pathlib import Path
from typing import Optional
import requests
from bs4 import BeautifulSoup

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

logger = logging.getLogger(__name__)

def _ensure_logger_handlers():
    """Ensure logger has handlers - try to use extract_articles logger's handlers."""
    if logger.handlers:
        return
    # Try to get handlers from extract_articles logger (used by scripts)
    extract_logger = logging.getLogger("extract_articles")
    if extract_logger.handlers:
        for handler in extract_logger.handlers:
            logger.addHandler(handler)
        logger.propagate = False
    else:
        # Fallback: allow propagation to root logger
        logger.propagate = True
    logger.setLevel(logging.INFO)


def download_xiaoyuzhou_audio(episode_url: str, output_dir: Path) -> tuple[Optional[Path], Optional[str]]:
    """Download MP3 audio file from Xiaoyuzhou episode page.
    
    Args:
        episode_url: URL of the Xiaoyuzhou episode page
        output_dir: Directory to save the audio file
        
    Returns:
        Tuple of (Path to downloaded audio file, episode_id), or (None, None) if download failed.
        If audio file already exists, returns (existing_path, episode_id) without downloading.
    """
    # Ensure logger has handlers before logging
    _ensure_logger_handlers()
    
    try:
        logger.info(f"Fetching episode page: {episode_url}")
        logger.info("This may take a moment...")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        }
        
        response = requests.get(episode_url, headers=headers, timeout=30)
        response.raise_for_status()
        logger.info("✓ Episode page fetched successfully")
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Try to find audio URL in various ways
        audio_url = None
        
        # Method 1: Look for audio tag
        audio_tag = soup.find('audio')
        if audio_tag:
            audio_url = audio_tag.get('src') or audio_tag.find('source', {}).get('src') if audio_tag.find('source') else None
        
        # Method 2: Look for audio URL in script tags (JSON data)
        if not audio_url:
            scripts = soup.find_all('script')
            for script in scripts:
                if script.string:
                    # Look for MP3 URLs in script content (more comprehensive pattern)
                    mp3_matches = re.findall(r'https?://[^\s"\'<>\)]+\.mp3[^\s"\'<>\)]*', script.string, re.IGNORECASE)
                    if mp3_matches:
                        # Prefer URLs that look like CDN or audio hosting
                        for url in mp3_matches:
                            if 'cdn' in url.lower() or 'audio' in url.lower() or 'media' in url.lower():
                                audio_url = url
                                break
                        if not audio_url:
                            audio_url = mp3_matches[0]
                        break
                    
                    # Look for audio URL in JSON-LD structured data
                    if script.get('type') == 'application/ld+json':
                        try:
                            import json
                            data = json.loads(script.string)
                            if isinstance(data, dict):
                                # Check for audio in various possible locations
                                audio_url = (data.get('audio') or 
                                           data.get('episode', {}).get('audio') or
                                           data.get('associatedMedia', {}).get('contentUrl') or
                                           data.get('contentUrl'))
                                if audio_url:
                                    break
                        except (json.JSONDecodeError, AttributeError):
                            pass
                    
                    # Look for audio URL in JSON structures (more flexible pattern)
                    try:
                        import json
                        # Try to find larger JSON objects that might contain audio
                        # Look for patterns like "audio": "url" or "audioUrl": "url"
                        json_patterns = [
                            r'"audio"\s*:\s*"([^"]+\.mp3[^"]*)"',
                            r'"audioUrl"\s*:\s*"([^"]+\.mp3[^"]*)"',
                            r'"audio_url"\s*:\s*"([^"]+\.mp3[^"]*)"',
                            r'"url"\s*:\s*"([^"]+\.mp3[^"]*)"',
                        ]
                        for pattern in json_patterns:
                            matches = re.findall(pattern, script.string, re.IGNORECASE)
                            if matches:
                                audio_url = matches[0]
                                break
                        if audio_url:
                            break
                    except:
                        pass
        
        # Method 3: Look for data attributes
        if not audio_url:
            audio_elements = soup.find_all(attrs={'data-audio': True})
            if audio_elements:
                audio_url = audio_elements[0].get('data-audio')
        
        if not audio_url:
            logger.error("✗ Could not find audio URL in episode page")
            logger.error("Please check if the episode page structure has changed")
            return None, None
        
        logger.info(f"✓ Found audio URL: {audio_url}")
        
        # Download the audio file
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Extract episode ID from URL (format: https://www.xiaoyuzhoufm.com/episode/68805b4f96cb2d7109e16b63)
        episode_id = None
        episode_id_match = re.search(r'/episode/([a-f0-9]+)', episode_url)
        if episode_id_match:
            episode_id = episode_id_match.group(1)
            logger.info(f"Extracted episode ID: {episode_id}")
        else:
            # Fallback: try to extract from other URL patterns
            episode_id_match = re.search(r'episode[_-]?([a-f0-9]+)', episode_url)
            if episode_id_match:
                episode_id = episode_id_match.group(1)
                logger.info(f"Extracted episode ID (fallback): {episode_id}")
        
        # Check if audio file already exists
        if episode_id:
            filename = f"episode_{episode_id}.mp3"
            audio_path = output_dir / filename
            if audio_path.exists():
                logger.info(f"Audio file already exists: {audio_path}, skipping download")
                return audio_path, episode_id
        else:
            logger.warning("Could not extract episode ID, using timestamp")
            filename = f"episode_{int(time.time())}.mp3"
            audio_path = output_dir / filename
        
        audio_path = output_dir / filename
        
        logger.info(f"Downloading audio to: {audio_path}")
        logger.info("This may take several minutes for large audio files...")
        # Use print for progress indicator since logger.info doesn't support end/flush
        import sys
        print("Progress: [", end="", flush=True, file=sys.stderr)
        logger.info("Progress: [")
        start_time = time.time()
        audio_response = requests.get(audio_url, headers=headers, timeout=300, stream=True)
        audio_response.raise_for_status()
        
        total_size = 0
        chunk_count = 0
        with open(audio_path, 'wb') as f:
            for chunk in audio_response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    total_size += len(chunk)
                    chunk_count += 1
                    # Print progress every 100 chunks (~800KB)
                    if chunk_count % 100 == 0:
                        print(".", end="", flush=True, file=sys.stderr)
        
        print("]", file=sys.stderr)  # End progress line
        logger.info("]")  # End progress line
        elapsed_time = time.time() - start_time
        file_size_mb = audio_path.stat().st_size / (1024 * 1024)
        logger.info(f"✓ Audio downloaded successfully: {file_size_mb:.1f}MB (took {elapsed_time:.1f}s)")
        
        return audio_path, episode_id
        
    except Exception as e:
        logger.error(f"Error downloading audio: {e}", exc_info=True)
        return None, None


def transcribe_audio_with_gemini(audio_file: Path, transcript_file: Optional[Path] = None, gemini_api_key: Optional[str] = None) -> Optional[str]:
    """Transcribe audio file using Gemini-3-flash-preview model.
    
    Args:
        audio_file: Path to audio file
        transcript_file: Optional path to save transcript as txt file
        gemini_api_key: Gemini API key (if None, uses GEMINI_API_KEY env var)
        
    Returns:
        Transcription text, or None if transcription failed
    """
    if not GEMINI_AVAILABLE:
        logger.error("google-generativeai not installed. Install with: pip install google-generativeai")
        return None
    
    api_key = gemini_api_key or os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY not set")
        return None
    
    try:
        genai.configure(api_key=api_key)
        
        logger.info(f"Uploading audio file: {audio_file.name}")
        logger.info("File size: {:.1f}MB".format(audio_file.stat().st_size / (1024 * 1024)))
        logger.info("Uploading to Gemini... (this may take a moment)")
        uploaded_file = genai.upload_file(
            path=str(audio_file),
            display_name=audio_file.name
        )
        logger.info(f"✓ File uploaded: {uploaded_file.name}")
        
        # Wait for file processing
        logger.info("Waiting for Gemini to process the audio file...")
        max_wait = 300  # 5 minutes
        wait_time = 0
        while uploaded_file.state.name == "PROCESSING":
            if wait_time >= max_wait:
                logger.warning("✗ File processing timeout after 5 minutes")
                break
            logger.info(f"  Processing... ({wait_time}s / {max_wait}s)")
            time.sleep(10)
            wait_time += 10
            uploaded_file = genai.get_file(uploaded_file.name)
        
        if uploaded_file.state.name == "ACTIVE":
            logger.info("✓ File processing completed")
        
        if uploaded_file.state.name == "FAILED":
            logger.error("File processing failed")
            try:
                genai.delete_file(uploaded_file.name)
            except:
                pass
            return None
        
        if uploaded_file.state.name != "ACTIVE":
            logger.warning(f"File state abnormal: {uploaded_file.state.name}")
        
        # Transcribe using Gemini-3-flash-preview
        logger.info("Starting transcription with gemini-3-flash-preview...")
        try:
            model = genai.GenerativeModel("models/gemini-3-flash-preview")
            logger.info("Using model: gemini-3-flash-preview")
        except Exception as e:
            logger.warning(f"Could not use gemini-3-flash-preview: {e}")
            # Fallback to other models
            try:
                model = genai.GenerativeModel("models/gemini-2.5-flash")
                logger.info("Using fallback model: gemini-2.5-flash")
            except:
                model = genai.GenerativeModel("gemini-pro")
                logger.info("Using default model: gemini-pro")
        
        prompt = """请将这段中文播客音频完整转录为文字。重要要求：

**关键要求**：
- 必须明确区分"主播/主持人"和"节目嘉宾"的发言
- 主播是播客的主持人/制作者，通常是提问者和讨论引导者
- 节目嘉宾是播客邀请的访谈对象
- 在转录时，请清晰标注说话人身份，例如：[主播]、[嘉宾]

**转录要求**：
1. 保持对话的原始顺序和时间顺序
2. 明确区分并标注说话人：使用[主播]、[嘉宾]、[其他]等标签
3. 主播的发言要特别标记清楚（这些是Panel嘉宾的观点）
4. 保留重要的语气词和停顿标记
5. 使用中文标点符号
6. 如果内容较长，请分段输出，每段标明大致时间点
7. 保持原意，不要添加或删减内容
8. 转录格式示例：
   [主播]：今天我们要聊的话题是...
   [嘉宾]：我认为这个问题...
   [主播]：那你觉得...
"""
        
        logger.info("Sending transcription request to Gemini...")
        logger.info("This may take several minutes depending on audio length...")
        logger.info("Please wait...")
        response = model.generate_content([uploaded_file, prompt])
        
        transcription = response.text
        logger.info("✓ Transcription completed")
        
        # Save transcript to file if transcript_file is provided
        if transcript_file and transcription:
            try:
                transcript_file.parent.mkdir(parents=True, exist_ok=True)
                with open(transcript_file, 'w', encoding='utf-8') as f:
                    f.write(transcription)
                logger.info(f"Transcript saved to: {transcript_file}")
            except Exception as e:
                logger.warning(f"Error saving transcript to file: {e}")
        
        # Clean up uploaded file
        try:
            genai.delete_file(uploaded_file.name)
            logger.info("Cleaned up uploaded file")
        except Exception as e:
            logger.warning(f"Error cleaning up file: {e}")
        
        logger.info(f"Transcription completed: {len(transcription)} characters")
        return transcription
        
    except Exception as e:
        logger.error(f"Transcription failed: {e}", exc_info=True)
        # Try to clean up
        try:
            if 'uploaded_file' in locals():
                genai.delete_file(uploaded_file.name)
        except:
            pass
        return None


def load_transcript_from_file(transcript_file: Path) -> Optional[str]:
    """Load transcript from txt file.
    
    Args:
        transcript_file: Path to transcript txt file
        
    Returns:
        Transcript text, or None if file doesn't exist, is empty, or read failed.
        Returns None for empty files to force re-download and transcription.
    """
    try:
        if transcript_file.exists():
            with open(transcript_file, 'r', encoding='utf-8') as f:
                transcript = f.read()
            # Return None if file is empty or only whitespace
            if not transcript or not transcript.strip():
                logger.warning(f"Transcript file exists but is empty: {transcript_file}")
                return None
            logger.info(f"Loaded transcript from file: {transcript_file} ({len(transcript)} characters)")
            return transcript
        else:
            logger.info(f"Transcript file does not exist: {transcript_file}")
            return None
    except Exception as e:
        logger.error(f"Error loading transcript from file: {e}", exc_info=True)
        return None


def generate_podcast_summary(shownotes: str, transcript: str, gemini_api_key: Optional[str] = None) -> Optional[str]:
    """Generate blog-style summary from shownotes and transcript using Gemini.
    
    Args:
        shownotes: Episode shownotes text
        transcript: Full transcript text
        gemini_api_key: Gemini API key (if None, uses GEMINI_API_KEY env var)
        
    Returns:
        Generated summary text, or None if generation failed
    """
    if not GEMINI_AVAILABLE:
        logger.error("google-generativeai not installed")
        return None
    
    api_key = gemini_api_key or os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY not set")
        return None
    
    try:
        genai.configure(api_key=api_key)
        
        # Use gemini-3-flash-preview or fallback
        try:
            model = genai.GenerativeModel("models/gemini-3-flash-preview")
        except:
            try:
                model = genai.GenerativeModel("models/gemini-2.5-flash")
            except:
                model = genai.GenerativeModel("gemini-pro")
        
        prompt = """# Role
你是一位资深的小宇宙播客深度听众和内容编辑，擅长将复杂的长对话转化为逻辑严密、富有感染力的"精编笔记"。

# Context
我将提供一段小宇宙播客的 [Show Notes] 和 [完整 Transcript]。请结合这两者，为我生成一份兼具深度与可读性的总结。

# Requirements for "Xiaoyuzhou" Style
1. **时间线锚点**：在总结核心议题时，请尽可能对应 Transcript 中的大概时间点（如 [15:20]），方便我回听。
2. **嘉宾画像与立场**：明确区分主持人和每位嘉宾的身份、核心观点。如果有人提出了独特的视角或产生了激烈的火花，请重点标出。
3. **内容重构**：严禁流水账。请根据内容深度，将播客拆解为 3-4 个"深度专题"，并以富有吸引力的标题命名。
4. **保留"体感"与细节**：不要只给枯燥的结论。保留嘉宾提到的有趣案例、生动比喻、或者某些动人的个人经历。
5. **语言风格**：专业但不说教，带有一点人文关怀和洞察感，适合发布在小宇宙评论区或即刻。

# Output Format
**重要：请直接输出HTML格式，不要使用markdown。** 使用以下HTML标签：
- 段落：`<p style="margin-bottom: 15px; line-height: 1.8;">内容</p>`
- 二级标题：`<h3 style="font-size: 18px; margin-top: 20px; margin-bottom: 10px; color: #667eea;"><strong>标题</strong></h3>`
- 三级标题：`<h4 style="font-size: 16px; margin-top: 15px; margin-bottom: 8px; color: #555;"><strong>标题</strong></h4>`
- 加粗：`<strong>文本</strong>`
- 斜体：`<em>文本</em>`
- 水平线：`<hr style="margin: 20px 0; border: none; border-top: 1px solid #ddd;"/>`
- 有序列表：`<ol style="margin-bottom: 15px; padding-left: 25px; line-height: 1.8;"><li style="margin-bottom: 10px;">项目</li></ol>`
- 无序列表：`<ul style="margin-bottom: 15px; padding-left: 25px; line-height: 1.8;"><li style="margin-bottom: 10px;">项目</li></ul>`

# Output Structure
1. **【一言以蔽之】**：用最犀利的一句话总结本期节目的灵魂。
2. **【核心议题深度复盘】**（按专题组织）：
   - **专题标题**（例：关于[话题]的认知迭代）
   - **关键洞察**：[时间戳] 嘉宾 A 与 B 的观点对比、核心论据。
   - **细节拾遗**：具体的案例或有趣的数据。
3. **【高光金句库】**：精选 5 句最能引发共鸣或震慑人心的原话（附上讲者），使用有序列表格式。
4. **【值得进一步思考的问题】**：基于本期内容，提炼出 1-2 个引发听众后续讨论的延伸思考，使用有序列表格式。

---
[Show Notes]:
{shownotes}

[Transcript]:
{transcript}
""".format(shownotes=shownotes, transcript=transcript)
        
        logger.info("Generating summary...")
        response = model.generate_content(prompt)
        
        summary = response.text
        logger.info(f"Summary generated: {len(summary)} characters")
        
        return summary
        
    except Exception as e:
        logger.error(f"Summary generation failed: {e}", exc_info=True)
        return None
