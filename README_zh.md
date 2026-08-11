# epub2md

[English](README.md) | [中文](README_zh.md)

> 将 EPUB 电子书解压并转换为 Markdown 文件，自动提取图片、识别代码块、清理标题层级。

## 简介

EPUB 本质上是一个 ZIP 压缩包，里面包含 XHTML、图片、CSS 等资源。`epub2md` 脚本做的事情：

1. **解压 EPUB** — 读取 ZIP 结构，解析 OPF 文件获取章节阅读顺序
2. **逐章转换** — 按 spine 顺序，将每个 XHTML 文件转换为 Markdown
3. **提取图片** — 扫描 `<img>` 标签，基于 XHTML 位置解析相对路径，提取到 `images/` 目录
4. **识别代码** — 自动扫描 CSS 找出等宽字体 class，把对应内容识别为代码块
5. **清理标题** — 去掉标题内的加粗标记，合并章节编号与标题文本
6. **合并输出** — 所有章节合并为单个 `.md` 文件

## 环境要求

- **Python 3.8+**（推荐 3.10+）
- **无需安装依赖** — 所有第三方库已内置在 `libs/` 目录中，脚本运行时自动加载。克隆即用。

<details>
<summary>libs/ 内置依赖列表</summary>

| 包名 | 用途 |
|------|------|
| `beautifulsoup4` | HTML/XHTML 解析 |
| `markdownify` | HTML → Markdown 转换 |
| `lxml` | XML/HTML 解析引擎 |
| `soupsieve` | bs4 的 CSS 选择器支持 |
| `typing_extensions` | 类型注解向后兼容 |
| `six` | Python 2/3 兼容层（bs4 依赖） |

</details>

## 快速开始

```bash
# 克隆即用，无需 pip install
git clone git@github.com:stevenlii/epub2md.git
cd epub2md

# 转换 EPUB
python3 epub2md.py book.epub
```

## 用法

```bash
# 默认：自动创建以书名命名的文件夹，包含 md、images 和原始 epub
python3 epub2md.py book.epub

# 指定输出路径（不创建文件夹、不复制 epub）
python3 epub2md.py book.epub -o output/book.md
```

### 输出结构

默认行为（`python3 epub2md.py book.epub`）：

```
book/                    # 以 EPUB 文件名命名的文件夹
├── book.epub            # 原始 EPUB 副本
├── book.md              # 转换后的 Markdown 文件
└── images/              # 所有提取的图片
    ├── image_0001.jpg
    ├── image_0002.png
    └── ...
```

### 命令行参数

| 参数 | 说明 |
|------|------|
| `epub` | EPUB 文件路径（必填） |
| `-o, --output` | 输出 Markdown 文件路径（可选，默认自动创建同名文件夹） |

## 功能特性

### 图片提取

- 自动解析 XHTML 中的 `<img>` 标签
- 基于 XHTML 文件位置正确解析相对路径（如 `../images/xxx.jpg`）
- 去重：同一张图片只提取一次
- 在 Markdown 中用相对路径 `![](images/image_0001.jpg)` 引用

### 代码块识别

- 自动扫描 EPUB 内的 CSS 文件，找出使用等宽字体的 class
- 识别 `Source Code Pro`、`monospace`、`Courier`、`Consolas`、`Menlo` 等常见等宽字体
- 把连续的代码段落合并为标准 fenced code block（` ``` ` 围栏格式）
- 注释行（如 `# 加载数据`）也能正确放入同一代码块

### 标题清理

- 去掉标题内部的 `<b>`、`<span>` 等标签，避免 Obsidian 里出现 `第**4**章`
- 合并章节编号与标题文本：`## 第4章` + `## 文本分类` → `## 第4章 文本分类`
- 合并相邻的加粗标记：`**训****练****集**` → `**训练集**`
- 删除没有内容的空标题，避免大纲出现空白条目
- 识别并降级 EPUB 中为了视觉样式而误用为标题的短标记：
  - 代码输出词元：`an`、`for`、`m`、`.`
  - 参数名：`r`
  - 标签文字：`输出：`、`结果：`、`RAG`、`指令`
- 修复标题层级不一致的问题（例如原书把同级小节一个标成 `h3`、一个标成 `h1`，脚本会把 `h1` 降级到 `h3`）

### 目录标题提取

- 当章节标题是图片（部分 EPUB 的常见做法）时，脚本会从 EPUB 的目录文件中提取文字标题（EPUB2 读 `toc.ncx`，EPUB3 读 `nav.xhtml`）
- 提取的标题作为 `h2` 插入到章节内容前面，保证 Obsidian 大纲中能看到章节名
- 仅在章节没有任何 `h1`–`h6` 标签时触发，已有文字标题的章节不受影响

## 示例

仓库包含一个完整示例，位于 `examples/llm2Graph/`：

```
examples/llm2Graph/
├── llm2Graph.epub        # 原始 EPUB 文件
├── llm2Graph.md          # 转换后的 Markdown
└── images/               # 提取的 384 张图片
    ├── image_0001.jpg
    ├── image_0002.jpg
    └── ... (共 384 张)
```

这个示例展示了一个典型的技术书籍转换结果：
- 31 章全部转换
- 384 张图片全部提取，0 缺失
- 代码块、标题层级、图片引用均正确

## 技术细节

### 工作流程

```
EPUB 文件
  │
  ├─ 1. 读取 META-INF/container.xml → 找到 OPF 路径
  ├─ 2. 解析 OPF → 获取 manifest（资源清单）和 spine（阅读顺序）
  ├─ 3. 扫描 CSS → 检测等宽字体 class（用于代码识别）
  │
  ├─ 4. 按 spine 顺序逐章处理：
  │      ├─ 清理标题内部标签
  │      ├─ 识别并合并代码块
  │      ├─ 提取图片到 images/ 目录
  │      ├─ HTML → Markdown 转换
  │      └─ 后处理（合并加粗标记、章节标题等）
  │
  └─ 5. 合并所有章节 → 输出单个 .md 文件
```

### 为什么不用现成的工具？

- **pandoc**：功能强大但对 EPUB 内 CSS 样式驱动的代码识别不足
- **calibre**：输出格式不够干净，代码块和标题常有格式问题
- 本脚本针对常见 EPUB 排版做了专门处理（标题内嵌加粗、CSS 样式标记代码等）

## License

[MIT License](LICENSE) — 可自由使用、修改、分发。
