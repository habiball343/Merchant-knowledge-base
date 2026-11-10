import asyncio
from pathlib import Path

from langgraph.runtime import Runtime

from app.ingest.parsers import select_pdf_parser
from app.ingest.state import IngestContext, IngestState
from app.pipeline import stage

SUPPORTED_SUFFIXES = {".pdf": "pdf", ".md": "markdown", ".markdown": "markdown"}
_PARSER_LABELS = {"pymupdf": "内置解析器", "mineru": "MinerU"}


@stage("check_file", "检查文件")
async def check_file(state: IngestState, runtime: Runtime[IngestContext]) -> dict:
    path = Path(state["source_path"])
    if not path.is_file():
        raise FileNotFoundError("上传的文件不存在")
    kind = SUPPORTED_SUFFIXES.get(path.suffix.lower())
    if kind is None:
        raise ValueError(f"不支持的文件类型 {path.suffix or '（无扩展名）'}，目前支持 PDF 和 Markdown")
    if path.stat().st_size == 0:
        raise ValueError("文件是空的")
    return {"kind": kind, "file_title": state.get("file_title") or path.stem}


@stage("parse_pdf", "解析 PDF")
async def parse_pdf(state: IngestState, runtime: Runtime[IngestContext]) -> dict:
    """PDF 转 Markdown。解析是 CPU 密集的同步操作，放到线程里执行。"""
    settings = runtime.context["settings"]
    parser = select_pdf_parser(settings.pdf_parser, settings.mineru_command)
    parsed = await asyncio.to_thread(parser.parse, Path(state["source_path"]), Path(state["work_dir"]))
    return {
        "markdown": parsed.markdown,
        "base_dir": str(parsed.base_dir),
        "parser": parser.name,
        "_detail": f"{_PARSER_LABELS.get(parser.name, parser.name)}，{len(parsed.markdown)} 字",
    }


@stage("read_markdown", "读取 Markdown")
async def read_markdown(state: IngestState, runtime: Runtime[IngestContext]) -> dict:
    path = Path(state["source_path"])
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            markdown = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("无法识别文件编码，请将文件另存为 UTF-8")
    if not markdown.strip():
        raise ValueError("文件里没有内容")
    return {"markdown": markdown, "base_dir": str(path.parent), "parser": "markdown", "_detail": f"{len(markdown)} 字"}
