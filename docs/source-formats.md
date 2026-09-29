# 扩展数据源：CSV、Markdown、PDF 与 HTML

## HTML

- 上传选择 HTML，API 使用 `kind=html`；支持 UTF-8（含 BOM）的 `.html` / `.htm` 文件及 HTML 片段，最多 10 MB。使用标准库 HTMLParser，无新增依赖。
- 提取纯文本，按 h1–h6 分节；元数据保留页面 title（最多 1000 字符）、heading_path、heading、section_index。标题只作为元数据，正文交由当前 Chunker 分块。
- 解码 HTML 字符实体，保留常见块级元素的换行，压缩空白。链接只保留显示文字，表格只提取文字，不恢复结构或保留代码缩进。
- 排除 script、style、template、noscript、iframe、object、svg 内容和 head 非标题内容；不执行脚本，不渲染 HTML，不访问链接、图片、样式、附件或外部实体。正文预览沿用纯文本显示。
- 不是浏览器 DOM / CSS 布局解析器：不会执行 JS、判断 CSS 隐藏状态或自动去除导航广告；不保证严重损坏标签的浏览器级恢复。只有标题或动态脚本、没有正文时拒绝入库。
- 本阶段没有 URL 抓取。后续 Connector 需独立实现 SSRF、重定向、大小和超时限制。

## PDF

- 上传选择 PDF，API 使用 `kind=pdf`。使用 pypdf 文本层解析，每个有文本的页面生成一个 Document，再由当前 Chunker 分块。
- Document 元数据保存 `page_number`（从 1 开始）、`page_count`、`title`（PDF 属性标题，最多 1000 字符）。不推断标题层级、段落或表格结构。
- 空白页及无可提取文本的页面跳过；解析响应 `empty_pages` 与 `warnings` 提供页码，UI 展示提示。全部页面无文本时拒绝上传，提示可能需要 OCR。
- 拒绝加密文件（包括空密码加密）、损坏文件。PDF 必须以 `%PDF-` 开头，最多 10 MB、500 页、单页解压内容流 5 MB、总提取正文 200 万字符；超限整体失败，不部分入库。
- 不执行脚本，不下载链接或附件，不做 OCR。多栏、阅读顺序、乱码与表格效果取决于原 PDF，入库前请检查预览。
- 内容流限额在解压后检查，不能提供硬内存/时间隔离；当前仅适合本地可信文件。公开部署前需要独立受限解析进程和超时，不应把上传大小限制当作防压缩炸弹保证。
- 新增依赖 `pypdf>=6.18.1,<7.0.0`，更新项目依赖后重启服务。本批测试版本为 6.19.0。
- 解析方式与局限参考 [pypdf 官方文档](https://pypdf.readthedocs.io/en/6.18.1/user/extract-text.html)。

## CSV

- 上传选择 CSV，API 使用 `kind=csv`；UTF-8（允许 BOM）、逗号分隔、首行为表头。
- 支持双引号内的逗号、换行和转义双引号；跳过空行。空表头、重复表头、列数不一致、没有数据行会拒绝解析。
- 预览中勾选正文字段，按字段顺序组合正文，再使用当前 Chunker 分块。未选字段保存在 `Document.metadata.raw_metadata`。
- 所有单元格保留字符串类型，不自动推断数字/日期，避免丢失前导零。每条记录包含从 0 开始的 `record_index`；所选字段均为空时拒绝入库。
- 当前不支持分号/制表符分隔、Excel 文件或自动编码识别。字段大小受 Python CSV 解析器限制，超限返回可读错误。

## Markdown

- 上传选择 Markdown，API 使用 `kind=markdown`；UTF-8（允许 BOM）。
- 支持行首最多三个空格的 ATX（1–6 个 #）及 Setext（=== / ---）标题；按节生成 Document，标题作为元数据，不重复拼入正文。
- 保存 `heading_path`、`heading`、从 0 开始的 `section_index`，以及从 1 开始、两端包含的 `line_start` / `line_end`。行号表示原始正文区间，可包含首尾空行。
- 反引号和波浪号围栏代码块内不识别标题；未闭合围栏延伸至文件末尾。列表、表格、链接、代码等正文保留 Markdown 原文，不执行 HTML 或访问链接。
- 这是轻量节解析器，不是完整 CommonMark AST：不提取 YAML front matter，不解析容器内标题、内联格式或图片。复杂结构可选择纯文本模式保留整体正文。
- 只有标题而没有正文的文件拒绝入库；空节不生成 Document。

## 兼容性

CSV/Markdown 不引入新依赖；PDF 新增 pypdf。不更改已有 text/json/docx 解析行为。不自动重新解析存量来源，也不清空知识库。
来源原件、字段选项和写入历史复用现有归档机制，支持重复写入去重及清空后重建。
同一内容按不同 `kind` 解析具有不同身份；把曾按 text 导入的 Markdown 再按 markdown 导入，会产生另一组 Document。
