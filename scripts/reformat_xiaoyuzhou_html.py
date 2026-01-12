#!/usr/bin/env python3
"""Reformat existing Xiaoyuzhou HTML files with improved formatting."""
import sys
import re
import html
from pathlib import Path
from bs4 import BeautifulSoup

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

def format_shownotes(text):
    """Format shownotes text with proper paragraph breaks."""
    if not text:
        return ""
    # Escape HTML first
    text = html.escape(text)
    # Split by special section markers
    sections = re.split(r'(【[^】]+】)', text)
    formatted_parts = []
    for i, section in enumerate(sections):
        if re.match(r'【[^】]+】', section):
            # This is a section header
            formatted_parts.append(f'<h3 style="font-size: 18px; margin-top: 20px; margin-bottom: 10px; color: #667eea;">{section}</h3>')
        else:
            # Regular content - split by double newlines for paragraphs
            paragraphs = section.split('\n\n')
            for para in paragraphs:
                para = para.strip()
                if para:
                    # Check if it's a list item (starts with * or -)
                    if para.startswith('*') or para.startswith('-'):
                        # Format as list
                        lines = para.split('\n')
                        formatted_parts.append('<ul style="margin-bottom: 15px; padding-left: 20px;">')
                        for line in lines:
                            line = line.strip()
                            if line.startswith('*') or line.startswith('-'):
                                content = line[1:].strip()
                                if content:
                                    formatted_parts.append(f'<li style="margin-bottom: 8px;">{content}</li>')
                        formatted_parts.append('</ul>')
                    else:
                        # Regular paragraph
                        # Replace single newlines with <br> for line breaks within paragraphs
                        para = para.replace('\n', '<br>')
                        formatted_parts.append(f'<p style="margin-bottom: 15px; line-height: 1.8;">{para}</p>')
    return ''.join(formatted_parts)

def format_transcript(text):
    """Format transcript text with proper paragraph breaks."""
    if not text:
        return ""
    # Escape HTML first
    text = html.escape(text)
    
    # Split by double newlines first
    paragraphs = text.split('\n\n')
    formatted_parts = []
    
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        
        # Also split by time markers like [00:00 - 03:21] or [00:00]
        # This helps break up long transcripts
        time_markers = re.split(r'(\[[\d:]+\s*[-–]\s*[\d:]+\]|\[\d+:\d+\])', para)
        current_section = []
        
        for part in time_markers:
            part = part.strip()
            if not part:
                continue
            
            # Check if this is a time marker
            if re.match(r'\[[\d:]+\s*[-–]\s*[\d:]+\]|\[\d+:\d+\]', part):
                # End current section if any
                if current_section:
                    section_text = ' '.join(current_section).strip()
                    if section_text:
                        # Replace single newlines with <br>
                        section_text = section_text.replace('\n', '<br>')
                        formatted_parts.append(f'<p style="margin-bottom: 15px; line-height: 1.8;">{section_text}</p>')
                    current_section = []
                # Add time marker as a paragraph with special styling
                formatted_parts.append(f'<p style="margin-bottom: 10px; margin-top: 20px; font-weight: bold; color: #667eea;">{part}</p>')
            else:
                current_section.append(part)
        
        # Add remaining section
        if current_section:
            section_text = ' '.join(current_section).strip()
            if section_text:
                # Replace single newlines with <br>
                section_text = section_text.replace('\n', '<br>')
                formatted_parts.append(f'<p style="margin-bottom: 15px; line-height: 1.8;">{section_text}</p>')
    
    return ''.join(formatted_parts)

def format_summary_text(text):
    """Format summary text with proper HTML structure - handles both HTML and plain text."""
    if not text:
        return ""
    
    # Check if already HTML formatted
    # But always reformat to ensure proper structure (especially for quotes section)
    # So we'll process it anyway
    
    # Plain text - format it properly
    # Split by section markers 【...】 first (BEFORE HTML escape)
    sections = re.split(r'(【[^】]+】)', text)
    formatted_parts = []
    current_list = []
    in_ordered_list = False
    in_unordered_list = False
    
    in_quotes_section = False
    
    for i, section in enumerate(sections):
        section = section.strip()
        if not section:
            continue
        
        # Check if this is a section header 【...】
        if section.startswith('【') and section.endswith('】'):
            # End any current list
            if in_ordered_list and current_list:
                formatted_parts.append('<ol style="margin-bottom: 15px; padding-left: 25px; line-height: 1.8;">')
                for item in current_list:
                    formatted_parts.append(f'<li style="margin-bottom: 10px;">{item}</li>')
                formatted_parts.append('</ol>')
                current_list = []
                in_ordered_list = False
            elif in_unordered_list and current_list:
                formatted_parts.append('<ul style="margin-bottom: 15px; padding-left: 25px; line-height: 1.8;">')
                for item in current_list:
                    formatted_parts.append(f'<li style="margin-bottom: 10px;">{item}</li>')
                formatted_parts.append('</ul>')
                current_list = []
                in_unordered_list = False
            # Add header (escape HTML)
            section_escaped = html.escape(section)
            formatted_parts.append(f'<h3 style="font-size: 18px; margin-top: 20px; margin-bottom: 10px; color: #667eea;"><strong>{section_escaped}</strong></h3>')
            # Check if this is 高光金句库 header
            if '高光金句库' in section:
                in_quotes_section = True
            else:
                in_quotes_section = False
            continue
        
        # Special handling for "高光金句库" section - quotes should be list items
        if in_quotes_section:
            # Split by Chinese quotes and process as ordered list
            # Match pattern: "content"——author or "content"（note）
            # Each quote ends with —— or （, and next quote starts with "
            # Process BEFORE HTML escape to match Chinese quotes correctly
            quotes = re.findall(r'"[^"]+"[^"】]*?(?="|【|$)', section)
            if quotes:
                formatted_parts.append('<ol style="margin-bottom: 15px; padding-left: 25px; line-height: 1.8;">')
                for quote in quotes:
                    quote_escaped = html.escape(quote)
                    formatted_parts.append(f'<li style="margin-bottom: 10px;">{quote_escaped}</li>')
                formatted_parts.append('</ol>')
                in_quotes_section = False
                continue
            
            # If no quotes found, escape and format as paragraph
            section_escaped = html.escape(section)
            formatted_parts.append(f'<p style="margin-bottom: 15px; line-height: 1.8;">{section_escaped}</p>')
            in_quotes_section = False
            continue
        
        # Escape HTML for content sections
        section_escaped = html.escape(section)
        
        # Process content section - split by "专题" markers
        content_sections = re.split(r'(专题[^：]*：)', section_escaped)
        for content in content_sections:
            content = content.strip()
            if not content:
                continue
            
            # Check if this is a topic header (专题...：)
            if content.startswith('专题') and '：' in content:
                # End any current list
                if in_ordered_list and current_list:
                    formatted_parts.append('<ol style="margin-bottom: 15px; padding-left: 25px; line-height: 1.8;">')
                    for item in current_list:
                        formatted_parts.append(f'<li style="margin-bottom: 10px;">{item}</li>')
                    formatted_parts.append('</ol>')
                    current_list = []
                    in_ordered_list = False
                elif in_unordered_list and current_list:
                    formatted_parts.append('<ul style="margin-bottom: 15px; padding-left: 25px; line-height: 1.8;">')
                    for item in current_list:
                        formatted_parts.append(f'<li style="margin-bottom: 10px;">{item}</li>')
                    formatted_parts.append('</ul>')
                    current_list = []
                    in_unordered_list = False
                # Add h4 header (already escaped)
                formatted_parts.append(f'<h4 style="font-size: 16px; margin-top: 15px; margin-bottom: 8px; color: #555;"><strong>{content}</strong></h4>')
                continue
            
            # Process content - look for list items and regular text
            # Split by list markers (* or numbered)
            parts = re.split(r'(\*|\d+\.)', content)
            current_para = []
            
            i = 0
            while i < len(parts):
                part = parts[i].strip()
                if not part:
                    i += 1
                    continue
                
                # Check for list marker
                if part == '*' or (part and part[-1] == '.' and part[:-1].isdigit()):
                    # End current paragraph if any
                    if current_para:
                        para_text = ' '.join(current_para).strip()
                        if para_text:
                            formatted_parts.append(f'<p style="margin-bottom: 15px; line-height: 1.8;">{para_text}</p>')
                        current_para = []
                    
                    # Get list item content
                    if i + 1 < len(parts):
                        item_content = parts[i + 1].strip()
                        if item_content:
                            if part == '*':
                                # Unordered list
                                if not in_unordered_list:
                                    if in_ordered_list and current_list:
                                        formatted_parts.append('<ol style="margin-bottom: 15px; padding-left: 25px; line-height: 1.8;">')
                                        for item in current_list:
                                            formatted_parts.append(f'<li style="margin-bottom: 10px;">{item}</li>')
                                        formatted_parts.append('</ol>')
                                        current_list = []
                                        in_ordered_list = False
                                    in_unordered_list = True
                                current_list.append(item_content)
                            else:
                                # Ordered list
                                if not in_ordered_list:
                                    if in_unordered_list and current_list:
                                        formatted_parts.append('<ul style="margin-bottom: 15px; padding-left: 25px; line-height: 1.8;">')
                                        for item in current_list:
                                            formatted_parts.append(f'<li style="margin-bottom: 10px;">{item}</li>')
                                        formatted_parts.append('</ul>')
                                        current_list = []
                                        in_unordered_list = False
                                    in_ordered_list = True
                                current_list.append(item_content)
                        i += 2
                        continue
                
                # Regular text
                current_para.append(part)
                i += 1
            
            # End current paragraph
            if current_para:
                para_text = ' '.join(current_para).strip()
                if para_text:
                    formatted_parts.append(f'<p style="margin-bottom: 15px; line-height: 1.8;">{para_text}</p>')
    
    # Handle list at end
    if in_ordered_list and current_list:
        formatted_parts.append('<ol style="margin-bottom: 15px; padding-left: 25px; line-height: 1.8;">')
        for item in current_list:
            formatted_parts.append(f'<li style="margin-bottom: 10px;">{item}</li>')
        formatted_parts.append('</ol>')
    elif in_unordered_list and current_list:
        formatted_parts.append('<ul style="margin-bottom: 15px; padding-left: 25px; line-height: 1.8;">')
        for item in current_list:
            formatted_parts.append(f'<li style="margin-bottom: 10px;">{item}</li>')
        formatted_parts.append('</ul>')
    
    return ''.join(formatted_parts)

def reformat_xiaoyuzhou_html(html_file):
    """Reformat a Xiaoyuzhou HTML file with improved formatting."""
    with open(html_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    soup = BeautifulSoup(content, 'html.parser')
    
    # Find shownotes section
    shownotes_h2 = soup.find('h2', string=lambda x: x and '节目简介' in x)
    if shownotes_h2:
        shownotes_div = shownotes_h2.find_next_sibling('div', class_='shownotes')
        if shownotes_div:
            shownotes_text = shownotes_div.get_text()
            shownotes_formatted = format_shownotes(shownotes_text)
            shownotes_div.clear()
            shownotes_div.append(BeautifulSoup(shownotes_formatted, 'html.parser'))
    
    # Find summary section
    summary_h2 = soup.find('h2', string=lambda x: x and '内容总结' in x)
    if summary_h2:
        # Try to find div.summary-content first, then fall back to pre
        summary_div_existing = summary_h2.find_next_sibling('div', class_='summary-content')
        summary_pre = summary_h2.find_next_sibling('pre')
        
        if summary_div_existing:
            # Extract text and reformat using format_summary_text
            summary_text = summary_div_existing.get_text()
            summary_formatted = format_summary_text(summary_text)
            summary_div_existing.clear()
            summary_div_existing.append(BeautifulSoup(summary_formatted, 'html.parser'))
        elif summary_pre:
            # Has pre tag, convert to div
            summary_text = summary_pre.get_text()
            summary_formatted = format_summary_text(summary_text)
            summary_div = soup.new_tag('div')
            summary_div['class'] = 'summary-content'
            summary_div.append(BeautifulSoup(summary_formatted, 'html.parser'))
            summary_pre.replace_with(summary_div)
    
    # Find transcript section
    transcript_h2 = soup.find('h2', string=lambda x: x and '完整转录' in x)
    if transcript_h2:
        # Try to find div.transcript-content first, then fall back to pre
        transcript_div_existing = transcript_h2.find_next_sibling('div', class_='transcript-content')
        transcript_pre = transcript_h2.find_next_sibling('pre')
        
        if transcript_div_existing:
            # Already has div, extract text and reformat
            transcript_text = transcript_div_existing.get_text()
            transcript_formatted = format_transcript(transcript_text)
            transcript_div_existing.clear()
            transcript_div_existing.append(BeautifulSoup(transcript_formatted, 'html.parser'))
        elif transcript_pre:
            # Has pre tag, convert to div
            transcript_text = transcript_pre.get_text()
            transcript_formatted = format_transcript(transcript_text)
            transcript_div = soup.new_tag('div')
            transcript_div['class'] = 'transcript-content'
            transcript_div.append(BeautifulSoup(transcript_formatted, 'html.parser'))
            transcript_pre.replace_with(transcript_div)
    
    # Write back - use prettify to ensure proper formatting, but fix class_ issue
    html_output = str(soup)
    # Fix BeautifulSoup's class_ output to proper class attribute
    html_output = html_output.replace('class_=', 'class=')
    
    with open(html_file, 'w', encoding='utf-8') as f:
        f.write(html_output)
    
    print(f"Reformatted: {html_file.name}")

if __name__ == "__main__":
    from app.config import HTML_DIR_EN, HTML_DIR_ZH
    
    # Find all Xiaoyuzhou HTML files
    xiaoyuzhou_files = []
    for html_file in HTML_DIR_EN.glob("*xiaoyuzhou*.html"):
        xiaoyuzhou_files.append(html_file)
    
    if not xiaoyuzhou_files:
        print("No Xiaoyuzhou HTML files found")
        sys.exit(0)
    
    print(f"Found {len(xiaoyuzhou_files)} Xiaoyuzhou HTML files")
    
    for html_file in xiaoyuzhou_files:
        try:
            reformat_xiaoyuzhou_html(html_file)
            # Also reformat zh version if exists
            zh_file = HTML_DIR_ZH / html_file.name
            if zh_file.exists():
                reformat_xiaoyuzhou_html(zh_file)
        except Exception as e:
            print(f"Error reformatting {html_file.name}: {e}")
            import traceback
            traceback.print_exc()
    
    print(f"\nReformatted {len(xiaoyuzhou_files)} files")
