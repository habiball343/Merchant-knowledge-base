import shutil
import shlex

from app.ingest.parsers.base import ParsedDocument, PdfParseError, PdfParser
from app.ingest.parsers.mineru_parser import MinerUParser
from app.ingest.parsers.pymupdf_parser import PyMuPdfParser


def select_pdf_parser(choice: str = "auto", mineru_command: str = "mineru") -> PdfParser:
    """auto：装了 MinerU 就用 MinerU，否则用内置解析器。"""
    executable = shlex.split(mineru_command)[0] if mineru_command.strip() else "mineru"
    if choice == "mineru" or (choice == "auto" and shutil.which(executable)):
        return MinerUParser(mineru_command)
    return PyMuPdfParser()


__all__ = ["ParsedDocument", "PdfParseError", "PdfParser", "MinerUParser", "PyMuPdfParser", "select_pdf_parser"]
