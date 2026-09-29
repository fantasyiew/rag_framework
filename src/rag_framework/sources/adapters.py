import csv
import hashlib
import io
import json
import re
import zipfile
from abc import ABC, abstractmethod
from html.parser import HTMLParser
from typing import ClassVar
from xml.etree import ElementTree as ET

from pydantic import BaseModel, Field

from rag_framework.core.models import Document


class AdapterOptions(BaseModel):
    content_fields: list[str] = Field(default_factory=list)


class SourceAdapter(ABC):
    kind: str

    @abstractmethod
    def inspect(self, data: bytes) -> dict: ...

    @abstractmethod
    def documents(self, data: bytes, options: AdapterOptions) -> list[Document]: ...


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def text(data: bytes) -> str:
    try:
        value = data.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n').strip()
    except UnicodeDecodeError as exc:
        raise ValueError('请提供 UTF-8 编码文本') from exc
    if not value:
        raise ValueError('内容不能为空')
    return value


class PlainTextAdapter(SourceAdapter):
    kind = 'text'

    def inspect(self, data: bytes) -> dict:
        return {'supported': True, 'characters': len(text(data))}

    def documents(self, data: bytes, options: AdapterOptions) -> list[Document]:
        return [Document(content=text(data), metadata={'source_type': self.kind})]


class JsonAdapter(SourceAdapter):
    kind = 'json'

    @staticmethod
    def is_supported_value(value: object) -> bool:
        """Accept JSON scalars and one-dimensional arrays containing only scalars."""
        if isinstance(value, dict):
            return False
        if isinstance(value, list):
            return all(not isinstance(item, (dict, list)) for item in value)
        return True

    @staticmethod
    def content_text(value: object) -> str:
        if isinstance(value, list):
            return ', '.join(
                item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
                for item in value
            )
        return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)

    def records(self, data: bytes) -> list[dict]:
        try:
            value = json.loads(text(data))
        except json.JSONDecodeError as exc:
            raise ValueError(f'JSON 格式错误，行 {exc.lineno}') from exc
        records = [value] if isinstance(value, dict) else value
        if not isinstance(records, list) or not records or not all(isinstance(r, dict) for r in records):
            raise ValueError('JSON 顶层必须是对象或非空对象数组')
        return records

    def inspect(self, data: bytes) -> dict:
        records = self.records(data)
        names = list(dict.fromkeys(key for record in records for key in record))
        nested = [
            key for key in names
            if any(key in record and not self.is_supported_value(record[key]) for record in records)
        ]
        return {'supported': not nested, 'record_count': len(records), 'nested_fields': nested,
                'reason': '当前版本暂不支持嵌套字段' if nested else None,
                'fields': [{'name': k, 'sample': next((r[k] for r in records if k in r), None)}
                           for k in names]}

    def documents(self, data: bytes, options: AdapterOptions) -> list[Document]:
        inspection = self.inspect(data)
        if not inspection['supported']:
            raise ValueError(inspection['reason'])
        fields = list(dict.fromkeys(options.content_fields))
        if not fields or not set(fields) <= {f['name'] for f in inspection['fields']}:
            raise ValueError('请选择有效的正文字段')
        documents = []
        for index, record in enumerate(self.records(data)):
            body = '\n'.join(
                f'{key}: {self.content_text(record[key])}'
                for key in fields
                if key in record
                and record[key] is not None
                and self.content_text(record[key]).strip()
            )
            if not body:
                raise ValueError(f'第 {index + 1} 条记录的所选字段没有正文')
            documents.append(Document(content=body, metadata={
                'source_type': self.kind, 'record_index': index,
                'raw_metadata': {k: v for k, v in record.items() if k not in fields}}))
        return documents


class CsvAdapter(JsonAdapter):
    """Comma-separated UTF-8 records; preserve every cell as a string."""

    kind = 'csv'

    def records(self, data: bytes) -> list[dict]:
        try:
            text(data)  # Validate encoding without trimming cell whitespace.
            reader = csv.reader(io.StringIO(data.decode('utf-8-sig'), newline=''), strict=True)
            headers = next(reader)
            if not headers or any(not h.strip() for h in headers):
                raise ValueError('CSV 表头不能为空')
            if len(set(headers)) != len(headers):
                raise ValueError('CSV 表头不能重复')
            records = []
            for row in reader:
                if not row:
                    continue
                if len(row) != len(headers):
                    raise ValueError(f'CSV 第 {reader.line_num} 行列数与表头不一致')
                records.append(dict(zip(headers, row, strict=True)))
            if not records:
                raise ValueError('CSV 必须包含数据行')
            return records
        except csv.Error as exc:
            raise ValueError('CSV 格式错误或字段过长') from exc


class MarkdownAdapter(SourceAdapter):
    """Section adapter supporting ATX/Setext headings and fenced code blocks."""

    kind = 'markdown'

    def documents(self, data: bytes, options: AdapterOptions) -> list[Document]:
        # Keep original line offsets, including leading blank lines.
        text(data)  # Shared encoding/empty-content validation.
        lines = data.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n').splitlines()
        documents, body, headings = [], [], []
        start, fence, index = 1, None, 0

        def flush(end):
            content = '\n'.join(body).strip()
            if content:
                documents.append(Document(content=content, metadata={
                    'source_type': self.kind,
                    'heading_path': [title for _, title in headings],
                    'heading': headings[-1][1] if headings else '',
                    'section_index': len(documents), 'line_start': start, 'line_end': end,
                }))
            body.clear()

        while index < len(lines):
            line = lines[index]
            marker = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
            if fence:
                body.append(line)
                if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                    fence = None
                index += 1
                continue
            if marker and (marker[1][0] != '`' or '`' not in marker[2]):
                fence = marker[1]
                body.append(line)
                index += 1
                continue
            heading = re.match(r'^ {0,3}(#{1,6})(?:[ \t]+(.*?)|[ \t]*)$', line)
            underline = (re.fullmatch(r' {0,3}(=+|-+)[ \t]*', lines[index + 1])
                         if index + 1 < len(lines) and line.strip() and not line.startswith(('    ', '\t')) else None)
            if heading or underline:
                flush(index)
                level = len(heading[1]) if heading else (1 if underline[1][0] == '=' else 2)
                title = re.sub(r'[ \t]+#+[ \t]*$', '', heading[2] or '').strip() if heading else line.strip()
                while headings and headings[-1][0] >= level:
                    headings.pop()
                headings.append((level, title))
                index += 1 if heading else 2
                start = index + 1
            else:
                body.append(line)
                index += 1
        flush(len(lines))
        if not documents:
            raise ValueError('Markdown 没有可索引正文')
        return documents

    def inspect(self, data: bytes) -> dict:
        documents = self.documents(data, AdapterOptions())
        return {'supported': True, 'sections': len(documents),
                'headings': [d.metadata['heading'] for d in documents]}


class DocxAdapter(SourceAdapter):
    kind = 'docx'
    ns: ClassVar[dict[str, str]] = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}

    def documents(self, data: bytes, options: AdapterOptions) -> list[Document]:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                info = archive.getinfo('word/document.xml')
                if info.file_size > 20_000_000:
                    raise ValueError('DOCX 正文解压后超过 20 MB')
                raw = archive.read(info)
                if b'<!DOCTYPE' in raw or b'<!ENTITY' in raw:
                    raise ValueError('不支持自定义 XML 实体')
                root = ET.fromstring(raw)
        except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
            raise ValueError('无法解析 DOCX；不支持旧版 DOC') from exc
        body = root.find('w:body', self.ns)
        if body is None:
            raise ValueError('文档没有正文')
        documents, lines, headings = [], [], []
        start = 0

        def flush(end):
            if lines:
                documents.append(Document(content='\n'.join(lines), metadata={
                    'source_type': self.kind, 'heading_path': list(headings),
                    'heading': headings[-1] if headings else '',
                    'section_index': len(documents), 'block_start': start, 'block_end': end}))
                lines.clear()

        for index, block in enumerate(body):
            value = ' '.join(n.text or '' for n in block.findall('.//w:t', self.ns)).strip()
            if block.tag == f'{{{self.ns["w"]}}}tbl':
                value = '\n'.join(
                    ' | '.join(''.join(n.text or '' for n in cell.findall('.//w:t', self.ns))
                               for cell in row.findall('w:tc', self.ns))
                    for row in block.findall('w:tr', self.ns)
                )
            style = block.find('w:pPr/w:pStyle', self.ns)
            name = style.get(f'{{{self.ns["w"]}}}val', '') if style is not None else ''
            if name.lower().startswith('heading') and name[-1:].isdigit():
                flush(index - 1)
                headings[:] = headings[:max(int(name[-1]) - 1, 0)] + [value]
                start = index + 1
            elif value:
                lines.append(value)
        flush(len(body) - 1)
        if not documents:
            raise ValueError('文档没有可索引正文')
        return documents

    def inspect(self, data: bytes) -> dict:
        documents = self.documents(data, AdapterOptions())
        return {'supported': True, 'sections': len(documents),
                'headings': [d.metadata['heading'] for d in documents]}


class PdfInputError(ValueError):
    """Safe, user-facing PDF validation message."""


class PdfAdapter(SourceAdapter):
    """Text-layer extraction only; one canonical document per nonempty page."""

    kind = 'pdf'
    max_pages = 500
    max_stream_bytes = 5_000_000
    max_characters = 2_000_000

    def parse(self, data: bytes) -> tuple[list[Document], dict]:
        from pypdf import PdfReader

        if len(data) > 10_000_000 or not data.startswith(b'%PDF-'):
            raise ValueError('请提供不超过 10 MB 的 PDF 文件')
        documents, empty_pages = [], []
        try:
            reader = PdfReader(io.BytesIO(data), strict=True)
            if reader.is_encrypted:
                raise PdfInputError('暂不支持加密 PDF，请先解密后上传')
            page_count = len(reader.pages)
            if not 0 < page_count <= self.max_pages:
                raise PdfInputError('PDF 页数必须为 1–500 页')
            title = str((reader.metadata or {}).get('/Title', ''))[:1000]
            characters = 0
            for number, page in enumerate(reader.pages, 1):
                stream = page.get_contents()
                if stream is not None and len(stream.get_data()) > self.max_stream_bytes:
                    raise PdfInputError('PDF 单页解压内容超过 5 MB，请拆分或简化文件')
                content = (page.extract_text() or '').strip()
                characters += len(content)
                if characters > self.max_characters:
                    raise PdfInputError('PDF 提取正文超过 200 万字符')
                if not content:
                    empty_pages.append(number)
                    continue
                documents.append(Document(content=content, metadata={
                    'source_type': self.kind, 'page_number': number,
                    'page_count': page_count, 'title': title,
                }))
        except PdfInputError:
            raise
        except Exception as exc:
            # Parser diagnostics can contain source data: return a stable public error.
            raise ValueError('无法解析 PDF，文件可能损坏或使用了不支持的结构') from exc
        if not documents:
            raise ValueError('PDF 没有可提取文本，可能是扫描件；当前不支持 OCR')
        return documents, {
            'supported': True, 'page_count': page_count, 'document_count': len(documents),
            'empty_pages': empty_pages,
            'warnings': ['部分页面未提取到文本，已跳过；扫描图片需要 OCR'] if empty_pages else [],
        }

    def inspect(self, data: bytes) -> dict:
        return self.parse(data)[1]

    def documents(self, data: bytes, options: AdapterOptions) -> list[Document]:
        return self.parse(data)[0]


class _HtmlTextParser(HTMLParser):
    """Extract text, never render markup or resolve external resources."""

    ignored: ClassVar[set[str]] = {'script', 'style', 'template', 'noscript', 'iframe', 'object', 'svg'}
    blocks: ClassVar[set[str]] = {'p', 'div', 'section', 'article', 'li', 'ul', 'ol', 'table', 'tr',
              'blockquote', 'pre', 'main', 'header', 'footer', 'nav', 'br', 'hr'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.suppressed = []
        self.in_head = False
        self.in_title = False
        self.title = []
        self.heading = None
        self.heading_text = []
        self.path = []
        self.body = []
        self.sections = []

    def flush(self):
        content = '\n'.join(' '.join(line.split()) for line in ''.join(self.body).splitlines())
        content = '\n'.join(line for line in content.splitlines() if line)
        if content:
            self.sections.append((content, [name for _, name in self.path]))
        self.body.clear()

    def finish_heading(self):
        if self.heading is not None:
            title = ' '.join(''.join(self.heading_text).split())
            while self.path and self.path[-1][0] >= self.heading:
                self.path.pop()
            if title:
                self.path.append((self.heading, title))
            self.heading = None
            self.heading_text.clear()

    def handle_starttag(self, tag, attrs):
        if tag in self.ignored:
            self.suppressed.append(tag)
        if self.suppressed:
            return
        if tag == 'head':
            self.in_head = True
        if tag == 'title':
            self.in_title = True
        if self.in_head or self.in_title:
            return
        if re.fullmatch(r'h[1-6]', tag):
            self.finish_heading()
            self.flush()
            self.heading = int(tag[1])
        elif tag in self.blocks:
            self.finish_heading()
            self.body.append('\n')
        elif tag in {'td', 'th'}:
            self.body.append(' ')

    def handle_endtag(self, tag):
        if self.suppressed:
            if tag == self.suppressed[-1]:
                self.suppressed.pop()
            return
        if tag == 'title':
            self.in_title = False
        if tag == 'head':
            self.in_head = False
        if self.in_head:
            return
        if re.fullmatch(r'h[1-6]', tag):
            self.finish_heading()
        elif tag in self.blocks:
            self.body.append('\n')

    def handle_data(self, data):
        if self.suppressed:
            return
        if self.in_title:
            self.title.append(data)
        elif not self.in_head:
            (self.heading_text if self.heading is not None else self.body).append(data)


class HtmlAdapter(SourceAdapter):
    kind = 'html'

    def documents(self, data: bytes, options: AdapterOptions) -> list[Document]:
        if len(data) > 10_000_000:
            raise ValueError('HTML 文件不能超过 10 MB')
        parser = _HtmlTextParser()
        parser.feed(text(data))
        parser.close()
        parser.finish_heading()
        parser.flush()
        title = ' '.join(''.join(parser.title).split())[:1000]
        documents = [Document(content=content, metadata={
            'source_type': self.kind, 'title': title, 'heading_path': path,
            'heading': path[-1] if path else '', 'section_index': index,
        }) for index, (content, path) in enumerate(parser.sections)]
        if not documents:
            raise ValueError('HTML 没有可索引正文；不支持执行 JavaScript 生成内容')
        return documents

    def inspect(self, data: bytes) -> dict:
        documents = self.documents(data, AdapterOptions())
        return {'supported': True, 'sections': len(documents),
                'title': documents[0].metadata['title'],
                'headings': [d.metadata['heading'] for d in documents]}


class AdapterRegistry:
    def __init__(self):
        self.adapters: dict[str, SourceAdapter] = {}

    def register(self, adapter: SourceAdapter):
        self.adapters[adapter.kind] = adapter

    def get(self, kind: str) -> SourceAdapter:
        if kind not in self.adapters:
            raise ValueError('不支持的数据格式')
        return self.adapters[kind]


registry = AdapterRegistry()
for adapter in (PlainTextAdapter(), JsonAdapter(), CsvAdapter(), MarkdownAdapter(),
                DocxAdapter(), PdfAdapter(), HtmlAdapter()):
    registry.register(adapter)
