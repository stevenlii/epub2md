# epub2md

[English](README.md) | [中文](README_zh.md)

> Convert EPUB ebooks to Markdown files with automatic image extraction, code block detection, and heading cleanup.

## Overview

EPUB is essentially a ZIP archive containing XHTML, images, CSS, and other resources. The `epub2md` script does the following:

1. **Unzip EPUB** — Reads the ZIP structure and parses the OPF file to determine chapter reading order
2. **Chapter-by-chapter conversion** — Converts each XHTML file to Markdown following the spine order
3. **Image extraction** — Scans `<img>` tags, resolves relative paths based on XHTML location, and extracts images to an `images/` directory
4. **Code detection** — Automatically scans CSS to find monospace font classes and identifies corresponding content as code blocks
5. **Heading cleanup** — Removes inline bold/italic tags from headings and merges chapter numbers with title text
6. **Merged output** — Combines all chapters into a single `.md` file

## Requirements

- **Python 3.8+** (3.10+ recommended)
- **No installation needed** — All dependencies are bundled in the `libs/` directory and automatically loaded at runtime. Just clone and run.

<details>
<summary>Dependencies included in <code>libs/</code></summary>

| Package | Purpose |
|---------|---------|
| `beautifulsoup4` | HTML/XHTML parsing |
| `markdownify` | HTML to Markdown conversion |
| `lxml` | XML/HTML parsing engine |
| `soupsieve` | CSS selector support for bs4 |
| `typing_extensions` | Type hint backports |
| `six` | Python 2/3 compatibility (used by bs4) |

</details>

## Quick Start

```bash
# Clone and run — no pip install required
git clone git@github.com:stevenlii/epub2md.git
cd epub2md

# Convert an EPUB
python3 epub2md.py book.epub
```

## Usage

```bash
# Default: creates a folder named after the book, containing md, images, and the original epub
python3 epub2md.py book.epub

# Specify a custom output path (no folder or epub copy is created)
python3 epub2md.py book.epub -o output/book.md
```

### Output Structure

Default behavior (`python3 epub2md.py book.epub`):

```
book/                    # Folder named after the EPUB file
├── book.epub            # Copy of the original EPUB
├── book.md              # Merged Markdown file
└── images/              # All extracted images
    ├── image_0001.jpg
    ├── image_0002.png
    └── ...
```

### Command-line Arguments

| Argument | Description |
|----------|-------------|
| `epub` | Path to the EPUB file (required) |
| `-o, --output` | Output Markdown file path (optional, defaults to creating a same-name folder) |

## Features

### Image Extraction

- Automatically parses `<img>` tags in XHTML
- Correctly resolves relative paths based on XHTML file location (e.g., `../images/xxx.jpg`)
- Deduplication: each image is extracted only once
- References images using relative paths like `![](images/image_0001.jpg)` in Markdown

### Code Block Detection

- Automatically scans CSS files within the EPUB to find classes using monospace fonts
- Recognizes common monospace fonts: `Source Code Pro`, `monospace`, `Courier`, `Consolas`, `Menlo`, etc.
- Merges consecutive code paragraphs into standard fenced code blocks (` ``` ` syntax)
- Comment lines (e.g., `# Load data`) are correctly included in the same code block

### Heading Cleanup

- Removes `<b>`, `<span>` and other inline tags from headings to prevent `第**4**章` in Obsidian
- Merges chapter numbers with title text: `## Chapter 4` + `## Text Classification` → `## Chapter 4 Text Classification`
- Merges adjacent bold markers: `**tra****in****ing**` → `**training**`
- Removes empty headings that appear as blank entries in the outline
- Detects and downgrades fake headings used for visual styling in some EPUBs:
  - Code output tokens: `an`, `for`, `m`, `.`
  - Parameter names: `r`
  - Labels: `输出：`, `结果：`, `RAG`, `指令`
- Normalizes inconsistent heading levels (e.g., an `h1` "微调" appearing after `h3` sections is demoted to `h3`)

### TOC Title Extraction

- When a chapter's heading is an image (common in some EPUBs), the script extracts the text title from the EPUB's table of contents (`toc.ncx` for EPUB2, `nav.xhtml` for EPUB3)
- The extracted title is inserted as an `h2` heading before the chapter content
- Only activates when no existing `h1`–`h6` tags are found in the chapter — chapters with text headings are left untouched

## Example

The repository includes a complete example in `examples/llm2Graph/`:

```
examples/llm2Graph/
├── llm2Graph.epub        # Original EPUB file
├── llm2Graph.md          # Converted Markdown
└── images/               # 384 extracted images
    ├── image_0001.jpg
    ├── image_0002.jpg
    └── ... (384 total)
```

This example demonstrates a typical technical book conversion:
- 31 chapters fully converted
- 384 images extracted, 0 missing
- Code blocks, heading hierarchy, and image references all correct

## Technical Details

### Workflow

```
EPUB File
  │
  ├─ 1. Read META-INF/container.xml → Find OPF path
  ├─ 2. Parse OPF → Get manifest (resource list) and spine (reading order)
  ├─ 3. Scan CSS → Detect monospace font classes (for code identification)
  │
  ├─ 4. Process chapters in spine order:
  │      ├─ Clean inline tags inside headings
  │      ├─ Detect and merge code blocks
  │      ├─ Extract images to images/ directory
  │      ├─ Convert HTML → Markdown
  │      └─ Post-processing (merge bold markers, chapter headings, etc.)
  │
  └─ 5. Merge all chapters → Output a single .md file
```

### Why not use existing tools?

- **pandoc**: Powerful but lacks CSS-driven code detection for EPUB content
- **calibre**: Output formatting is not clean; code blocks and headings often have formatting issues
- This script handles common EPUB formatting patterns specifically (inline bold in headings, CSS-styled code spans, etc.)

## License

[MIT License](LICENSE) — Free to use, modify, and distribute.
