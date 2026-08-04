#!/usr/bin/env python3
"""
epub2md.py — 将 EPUB 电子书解压并转换为 Markdown 文件

用法:
    python epub2md.py <input.epub> [-o output.md]

功能:
    1. 解压 EPUB（本质是 ZIP）
    2. 按 OPF spine 中的阅读顺序，将 XHTML 内容转换为 Markdown
    3. 提取所有图片到 images/ 目录
    4. 在 Markdown 中用相对路径引用图片
    5. 合并为单个 .md 文件输出
"""

import argparse
import os
import re
import sys
import zipfile
from pathlib import Path
from urllib.parse import unquote

from bs4 import BeautifulSoup
from markdownify import markdownify as md

import warnings
from bs4 import XMLParsedAsHTMLWarning
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)


# ── EPUB 解析 ──────────────────────────────────────────────────────────────

def find_opf_path(epub_zip: zipfile.ZipFile) -> str:
    """从 META-INF/container.xml 中找到 OPF 文件的路径"""
    try:
        container_xml = epub_zip.read("META-INF/container.xml").decode("utf-8")
    except KeyError:
        raise RuntimeError("不是合法的 EPUB：缺少 META-INF/container.xml")

    soup = BeautifulSoup(container_xml, "xml")
    rootfile = soup.find("rootfile")
    if not rootfile or not rootfile.get("full-path"):
        raise RuntimeError("container.xml 中未找到 OPF 路径")
    return rootfile["full-path"]


def parse_opf(epub_zip: zipfile.ZipFile, opf_path: str) -> dict:
    """
    解析 OPF 文件，返回:
      - manifest: {id: {href, media_type}}
      - spine: [id, id, ...]  按阅读顺序
    """
    opf_xml = epub_zip.read(opf_path).decode("utf-8")
    soup = BeautifulSoup(opf_xml, "xml")

    opf_dir = os.path.dirname(opf_path)

    # manifest
    manifest = {}
    for item in soup.find_all("item"):
        item_id = item.get("id")
        href = item.get("href", "")
        media_type = item.get("media-type", "")
        # href 是相对于 OPF 文件目录的路径
        full_href = os.path.normpath(os.path.join(opf_dir, href)) if opf_dir else href
        manifest[item_id] = {
            "href": full_href,
            "media_type": media_type,
        }

    # spine
    spine = []
    spine_tag = soup.find("spine")
    if spine_tag:
        for itemref in spine_tag.find_all("itemref"):
            idref = itemref.get("idref")
            if idref:
                spine.append(idref)

    return {"manifest": manifest, "spine": spine, "opf_dir": opf_dir}


def detect_code_classes(epub_zip: zipfile.ZipFile, opf_dir: str = "") -> set:
    """
    扫描 EPUB 中的 CSS 文件，找出使用等宽字体（Source Code Pro、monospace、Courier 等）
    的 class 名集合。用于把 styled span 识别为代码。
    """
    code_fonts = re.compile(
        r'font-family\s*:\s*["\']?.*?\b(Source Code Pro|monospace|Courier|Consolas|Menlo|"Courier New"|DejaVu Sans Mono|Ubuntu Mono|Fira Code|Inconsolata|Lucida Console)\b.*?["\']?\s*;',
        re.IGNORECASE,
    )

    code_classes = set()
    # 常见 CSS 文件路径
    css_paths = ["stylesheet.css", "page_styles.css", "css/style.css", "styles.css"]
    if opf_dir:
        css_paths = [os.path.join(opf_dir, p) for p in css_paths] + css_paths

    for css_path in css_paths:
        try:
            css_text = epub_zip.read(css_path).decode("utf-8", errors="ignore")
        except KeyError:
            continue

        # 简单解析：找到每个 class 规则块
        # 格式如 .calibre26 { ... }
        for match in re.finditer(r'\.([a-zA-Z0-9_-]+)\s*\{([^}]*)\}', css_text, re.DOTALL):
            class_name = match.group(1)
            rule_body = match.group(2)
            if code_fonts.search(rule_body):
                code_classes.add(class_name)

    return code_classes


# ── XHTML → Markdown ───────────────────────────────────────────────────────

def extract_image_extension(media_type: str, filename: str) -> str:
    """根据 media-type 或文件名获取图片扩展名"""
    ext_map = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/svg+xml": ".svg",
        "image/webp": ".webp",
        "image/tiff": ".tiff",
        "image/bmp": ".bmp",
    }
    if media_type and media_type in ext_map:
        return ext_map[media_type]
    # 从文件名推断
    ext = os.path.splitext(filename)[1]
    return ext if ext else ".img"


def process_styled_code(soup: BeautifulSoup, code_classes: set) -> None:
    """
    根据 CSS 识别出的代码 class，把对应的 span 标记为 <code>。
    连续多个仅包含代码的 <p> 会被合并成 <pre><code> 代码块。
    """
    if not code_classes:
        return

    def is_code_span(tag) -> bool:
        if tag.name != "span":
            return False
        classes = tag.get("class", [])
        return any(c in code_classes for c in classes)

    def is_code_only_paragraph(p) -> bool:
        """段落里只有 <code> 或 <br> 或空白文本/span 包装器"""
        code_tags = p.find_all("code")
        if not code_tags:
            return False
        # 如果包含链接、图片等交互元素，肯定不是纯代码段
        if p.find(["a", "img", "div", "table", "ul", "ol"]):
            return False
        for child in p.contents:
            if isinstance(child, str):
                if child.strip():
                    return False
            elif child.name not in ("code", "br", "span"):
                return False
        return True

    # 1) 把样式类标记为等宽的 span 转成 <code>
    for span in soup.find_all("span"):
        if is_code_span(span):
            # 先 unwrap 内部同样性质的 span，避免嵌套 code
            for child in list(span.find_all("span")):
                if is_code_span(child):
                    child.unwrap()
            span.name = "code"

    # 2) 合并连续仅含 code 的 <p> 为 <pre><code>
    paragraphs = soup.find_all("p")
    i = 0
    while i < len(paragraphs):
        p = paragraphs[i]
        if is_code_only_paragraph(p):
            group = [p]
            j = i + 1
            while j < len(paragraphs):
                next_p = paragraphs[j]
                if is_code_only_paragraph(next_p):
                    group.append(next_p)
                    j += 1
                else:
                    break

            if len(group) >= 1:
                # 提取每行文本，保留缩进
                lines = []
                for cp in group:
                    text = cp.get_text()
                    # BeautifulSoup get_text 会把多个子 code 连起来；这里按 <br> 分行
                    br_texts = []
                    for content in cp.contents:
                        if getattr(content, "name", None) == "br":
                            br_texts.append("\n")
                        elif isinstance(content, str):
                            br_texts.append(content)
                        else:
                            br_texts.append(content.get_text())
                    line = "".join(br_texts).rstrip()
                    if line:
                        lines.append(line)

                merged = "\n".join(lines)
                new_pre = soup.new_tag("pre")
                new_code = soup.new_tag("code")
                new_code.string = merged
                new_pre.append(new_code)
                group[0].replace_with(new_pre)
                for extra in group[1:]:
                    extra.decompose()
                # 刷新列表，从当前位置继续
                paragraphs = soup.find_all("p")
                i = max(0, i - 1)
                continue
        i += 1


def clean_headings(soup: BeautifulSoup) -> None:
    """清理标题内部的加粗/斜体/span 标签，让标题文本保持干净"""
    for level in range(1, 7):
        for heading in soup.find_all(f"h{level}"):
            for tag in heading.find_all(["b", "strong", "i", "em", "span", "font"]):
                tag.unwrap()


def process_xhtml(
    xhtml_content: str,
    xhtml_path: str,
    epub_zip: zipfile.ZipFile,
    image_counter: list,
    images_dir: Path,
    image_manifest: dict,
    manifest: dict,
    code_classes: set = None,
) -> str:
    """
    将单个 XHTML 转换为 Markdown，同时提取图片。
    xhtml_path: 该 XHTML 在 epub zip 内的路径（用于解析图片相对路径）。
    image_counter 是 [int] 列表，用于生成唯一图片名。
    image_manifest: {epub内部路径: 本地文件名} 避免重复提取。
    """
    soup = BeautifulSoup(xhtml_content, "lxml")

    # 当前 XHTML 所在目录（用于解析相对路径）
    xhtml_dir = os.path.dirname(xhtml_path)

    # 1) 预处理标题：去掉标题里的 <b>/<span>，避免 "第**4**章"
    clean_headings(soup)

    # 2) 预处理代码块（从 CSS 样式类识别）
    process_styled_code(soup, code_classes or set())

    # 3) 处理图片：提取到 images/ 目录，改写 src
    for img_tag in soup.find_all("img"):
        src = img_tag.get("src") or img_tag.get("xlink:href") or ""
        if not src:
            continue

        src = unquote(src)
        src_clean = src.split("#")[0]  # 去掉 fragment

        # 将图片相对路径解析为 epub 内部的完整路径
        # 例如 xhtml_path="EPUB/xhtml/chapter10.xhtml", src="../images/img.jpg"
        # → resolved="EPUB/images/img.jpg"
        resolved_path = os.path.normpath(os.path.join(xhtml_dir, src_clean)) if xhtml_dir else src_clean

        # 检查 zip 中是否有该文件
        extracted = False
        try_paths = [resolved_path, src_clean, os.path.basename(src_clean)]
        # 也在 manifest 中查找
        for item_id, item_info in manifest.items():
            if item_info["href"] == resolved_path or item_info["href"] == src_clean:
                try_paths.insert(0, item_info["href"])
                break

        for try_path in try_paths:
            try:
                img_data = epub_zip.read(try_path)
                # 用实际成功读取的路径作为缓存 key
                if try_path not in image_manifest:
                    image_counter[0] += 1
                    ext = os.path.splitext(src_clean)[1] or ".jpg"
                    local_name = f"image_{image_counter[0]:04d}{ext}"
                    image_manifest[try_path] = local_name
                    (images_dir / local_name).write_bytes(img_data)
                local_name = image_manifest[try_path]
                img_tag["src"] = f"images/{local_name}"
                extracted = True
                break
            except KeyError:
                continue

        if not extracted:
            # 无法提取，跳过该图片
            image_counter[0] += 1
            ext = os.path.splitext(src_clean)[1] or ".jpg"
            local_name = f"image_{image_counter[0]:04d}{ext}"
            img_tag["src"] = f"images/{local_name}"

    # 移除 script 和 style 标签
    for tag in soup.find_all(["script", "style"]):
        tag.decompose()

    # 获取 body 内容
    body = soup.find("body")
    if body:
        html_str = str(body)
    else:
        html_str = str(soup)

    # 转换为 Markdown
    markdown_text = md(
        html_str,
        heading_style="ATX",
        bullets="-",
        strip=["meta", "link", "head"],
        code_language="",
    )

    # 后处理：确保标题里没有残留的 **、__、*、_ 标记
    def clean_heading_line(match: re.Match) -> str:
        line = match.group(0)
        # 去掉行内加粗/斜体标记，保留文字
        line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
        line = re.sub(r"__(.+?)__", r"\1", line)
        line = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", line)
        line = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"\1", line)
        return line

    markdown_text = re.sub(r"^#{1,6} .*$", clean_heading_line, markdown_text, flags=re.MULTILINE)

    # 清理 fenced code block 里被转义的反引号（markdownify 有时会加 \\）
    markdown_text = re.sub(r"^\\?```", "```", markdown_text, flags=re.MULTILINE)

    # 清理多余空行
    markdown_text = re.sub(r"\n{4,}", "\n\n\n", markdown_text)
    # 去掉 body 标签残留
    markdown_text = re.sub(r"</?body[^>]*>", "", markdown_text)

    # 合并相邻的加粗/斜体标记，例如 **训****练****集** → **训练集**
    def merge_adjacent_markers(text: str, marker: str) -> str:
        escaped = re.escape(marker)
        pattern = escaped + r"(.+?)" + escaped + escaped + r"(.+?)" + escaped
        prev = None
        while prev != text:
            prev = text
            text = re.sub(pattern, marker + r"\1\2" + marker, text)
        return text

    markdown_text = merge_adjacent_markers(markdown_text, "**")
    markdown_text = merge_adjacent_markers(markdown_text, "*")
    markdown_text = merge_adjacent_markers(markdown_text, "__")
    markdown_text = merge_adjacent_markers(markdown_text, "_")

    # 合并 "第X章" 与下一行标题，例如：
    #   ## 第4章
    #   ## 文本分类     或   ### 文本分类
    # → ## 第4章 文本分类
    def merge_chapter_heading(match: re.Match) -> str:
        level = len(match.group(1))
        chapter_num = match.group(2).strip()
        next_level = len(match.group(3))
        title = match.group(4).strip()
        # 允许同级或深一级
        if next_level == level or next_level == level + 1:
            return "#" * level + f" {chapter_num} {title}"
        return match.group(0)

    markdown_text = re.sub(
        r"^(#{1,6})\s+(第\s*[0-9一二三四五六七八九十]+\s*章)\s*\n\n(#{1,6})\s+(.+)$",
        merge_chapter_heading,
        markdown_text,
        flags=re.MULTILINE,
    )

    # 清理转义的下划线（在非代码区域）
    markdown_text = re.sub(r"(?<!\\)\\_(?!\\)", "_", markdown_text)

    return markdown_text.strip()


# ── 主流程 ──────────────────────────────────────────────────────────────────

def convert_epub_to_markdown(epub_path: str, output_path: str = None):
    epub_path = Path(epub_path)
    if not epub_path.exists():
        print(f"错误：文件不存在: {epub_path}")
        sys.exit(1)

    # 输出路径
    if output_path:
        output_md = Path(output_path)
    else:
        output_md = epub_path.with_suffix(".md")

    output_dir = output_md.parent
    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    print(f"📖 正在处理: {epub_path.name}")
    print(f"📝 输出 Markdown: {output_md}")
    print(f"🖼️  图片目录: {images_dir}")

    with zipfile.ZipFile(epub_path, "r") as epub_zip:
        # 1. 找到 OPF 文件
        opf_path = find_opf_path(epub_zip)
        print(f"📋 OPF 路径: {opf_path}")

        # 2. 解析 OPF
        opf_data = parse_opf(epub_zip, opf_path)
        manifest = opf_data["manifest"]
        spine = opf_data["spine"]

        print(f"📚 Manifest 项目数: {len(manifest)}")
        print(f"📖 Spine 章节数: {len(spine)}")

        if not spine:
            print("⚠️  Spine 为空，尝试按 manifest 中 HTML 项的顺序处理")
            spine = [
                item_id
                for item_id, item in manifest.items()
                if item["media_type"] in ("application/xhtml+xml", "text/html")
            ]

        # 3) 逐章转换
        image_counter = [0]
        image_manifest = {}
        all_chapters = []

        # 自动从 CSS 检测代码样式类
        code_classes = detect_code_classes(epub_zip, opf_data.get("opf_dir", ""))
        if code_classes:
            print(f"🔤 检测到代码样式类: {', '.join(sorted(code_classes))}")

        for idx, item_id in enumerate(spine):
            if item_id not in manifest:
                print(f"  ⚠️  Spine 引用了不存在的 manifest id: {item_id}，跳过")
                continue

            item_info = manifest[item_id]
            href = item_info["href"]
            media_type = item_info["media_type"]

            # 只处理 HTML/XHTML 内容
            if media_type not in ("application/xhtml+xml", "text/html", ""):
                continue

            try:
                xhtml_content = epub_zip.read(href).decode("utf-8", errors="replace")
            except KeyError:
                print(f"  ⚠️  无法读取文件: {href}，跳过")
                continue

            print(f"  [{idx + 1}/{len(spine)}] 转换: {href}")

            # 转换内容
            markdown_text = process_xhtml(
                xhtml_content,
                href,
                epub_zip,
                image_counter,
                images_dir,
                image_manifest,
                manifest,
                code_classes,
            )

            if markdown_text:
                all_chapters.append(f"\n\n---\n\n{markdown_text}")

        # 4. 写入最终 Markdown
        # 尝试从 OPF 提取书名
        book_title = epub_path.stem
        try:
            opf_xml = epub_zip.read(opf_path).decode("utf-8")
            opf_soup = BeautifulSoup(opf_xml, "xml")
            title_tag = opf_soup.find("dc:title")
            if title_tag and title_tag.get_text(strip=True):
                book_title = title_tag.get_text(strip=True)
        except Exception:
            pass

        final_md = f"# {book_title}\n\n"
        final_md += "\n".join(all_chapters)

        output_md.write_text(final_md, encoding="utf-8")

        print(f"\n✅ 转换完成！")
        print(f"   📄 Markdown 文件: {output_md}")
        print(f"   🖼️  提取图片数: {len(image_manifest)}")
        print(f"   📏 Markdown 大小: {output_md.stat().st_size / 1024:.1f} KB")


# ── CLI ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="将 EPUB 转换为 Markdown，提取图片到 images/ 目录",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    python epub2md.py book.epub
    python epub2md.py book.epub -o output.md
    python epub2md.py book.epub -o ./mybook/book.md
        """,
    )
    parser.add_argument("epub", help="EPUB 文件路径")
    parser.add_argument("-o", "--output", default=None, help="输出 Markdown 文件路径（默认同名 .md）")

    args = parser.parse_args()
    convert_epub_to_markdown(args.epub, args.output)


if __name__ == "__main__":
    main()
