import hashlib
import io
import json
import zipfile
from abc import ABC, abstractmethod
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
for adapter in (PlainTextAdapter(), JsonAdapter(), DocxAdapter()):
    registry.register(adapter)
