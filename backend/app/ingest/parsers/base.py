from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class ParsedDocument:
    markdown: str
    base_dir: Path      # Markdown 中相对路径的图片以它为基准


class PdfParser(Protocol):
    name: str

    def parse(self, pdf_path: Path, work_dir: Path) -> ParsedDocument:
        """把 PDF 转成 Markdown，图片导出到 work_dir 下。同步执行，由调用方放到线程里。"""


class PdfParseError(RuntimeError):
    pass
