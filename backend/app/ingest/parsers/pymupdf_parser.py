"""内置的 PDF 解析器：基于 PyMuPDF，无需额外的模型和服务。

能还原标题层级、列表和表格，并导出页面中的图片；适合文字版的说明书和手册。
版面复杂（多栏、公式、扫描件）的资料建议改用 MinerU。

在 pymupdf4llm 输出的基础上做两处修正：
1. 把图片放回它在页面上的位置（原始输出把图片统一放在每页末尾，图和说明它的文字会错位）；
2. 把排版造成的硬换行接回去（一段话在 PDF 里按版心宽度折行，提取出来会断成几截）。
"""
import re
from pathlib import Path

from app.ingest.parsers.base import ParsedDocument, PdfParseError

_IMAGE_LINE = re.compile(r"^\s*!\[[^\]]*\]\([^)]+\)\s*$")
# 这些行开启一个新的 Markdown 结构，不会被接到上一行后面
_STARTS_BLOCK = re.compile(r"^\s*(#{1,6}\s|[-*+]\s|\d+[.)]\s|\||>|```|~~~|!\[|-{3,}\s*$)")
# 这些行后面不能再接正文：标题、表格行、引用、代码围栏、图片、分隔线
_CLOSED = re.compile(r"^\s*(#{1,6}\s|\||>|```|~~~|!\[|-{3,}\s*$)")
_CJK = re.compile(r"[　-〿一-鿿＀-￯]")
_SENTENCE_END = "。！？；：…．.!?;:）)」』”\"》】"
_MIN_WRAPPED_LINE = 20


class PyMuPdfParser:
    name = "pymupdf"

    def parse(self, pdf_path: Path, work_dir: Path) -> ParsedDocument:
        import pymupdf
        import pymupdf4llm

        image_dir = work_dir / "images"
        image_dir.mkdir(parents=True, exist_ok=True)
        try:
            pages = pymupdf4llm.to_markdown(
                str(pdf_path),
                page_chunks=True,
                write_images=True,
                image_path=str(image_dir),
                image_format="png",
                dpi=150,
                show_progress=False,
            )
            with pymupdf.open(pdf_path) as document:
                texts = [
                    place_images(page["text"], [image["bbox"] for image in page.get("images") or []],
                                 _text_blocks(document[index]))
                    for index, page in enumerate(pages)
                ]
        except Exception as exc:
            raise PdfParseError(f"PDF 解析失败：{type(exc).__name__}: {exc}") from exc

        markdown = reflow_paragraphs(clean_cell_breaks(join_pages(texts)))
        if not re.sub(r"!\[[^\]]*\]\([^)]+\)", "", markdown).strip():
            raise PdfParseError("没有从 PDF 中提取到文字。扫描件需要改用带 OCR 的解析器（MinerU）。")
        return ParsedDocument(markdown=markdown, base_dir=work_dir)


def _is_table_row(line: str) -> bool:
    return line.lstrip().startswith("|")


def join_pages(texts: list[str]) -> str:
    """拼接各页。跨页的表格在下一页会被当成一张新表（第一行数据被误当作表头），这里把它接回去。"""
    merged = ""
    for text in texts:
        text = text.strip("\n")
        if not text:
            continue
        previous_lines = merged.rstrip("\n").split("\n") if merged else []
        lines = text.split("\n")
        continues_table = (
            previous_lines and _is_table_row(previous_lines[-1])
            and len(lines) >= 2 and _is_table_row(lines[0])
            and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[1])
            and lines[0].count("|") == previous_lines[-1].count("|")
        )
        if continues_table:
            merged = merged.rstrip("\n") + "\n" + "\n".join([lines[0], *lines[2:]])
        else:
            merged = f"{merged}\n\n{text}" if merged else text
    return merged


def clean_cell_breaks(markdown: str) -> str:
    """表格单元格里的折行（<br>）接回去：中文之间直接相连，其余补一个空格。"""
    def join(match: re.Match) -> str:
        left, right = match.group(1), match.group(2)
        return left + ("" if _CJK.match(left) or _CJK.match(right) else " ") + right

    return "\n".join(
        re.sub(r"(\S)\s*<br\s*/?>\s*(\S)", join, line) if _is_table_row(line) else line
        for line in markdown.split("\n"))


def _text_blocks(page) -> list[tuple[float, str]]:
    """页面上的文字块：[(下边缘的纵坐标, 文字)]。"""
    return [(block[3], block[4]) for block in page.get_text("blocks") if block[6] == 0 and block[4].strip()]


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def place_images(text: str, image_boxes: list[tuple[float, float, float, float]],
                 text_blocks: list[tuple[float, str]]) -> str:
    """把一页中的图片引用移到它上方那段文字的后面。

    图片与引用按纵向顺序一一对应；找不到可靠的落点时保持原样，不做猜测。
    """
    lines = text.split("\n")
    references = [line for line in lines if _IMAGE_LINE.match(line)]
    if not references or len(references) != len(image_boxes):
        return text

    for reference, box in zip(references, sorted(image_boxes, key=lambda item: (item[1], item[0]))):
        above = [block for block in text_blocks if block[0] <= box[1] + 3]
        remaining = [line for line in lines if line != reference]
        if not above:
            lines = [reference, "", *remaining]            # 图片上方没有文字：放在这一页的开头
            continue
        anchor = _squash(max(above, key=lambda block: block[0])[1])
        position = _find_line(remaining, anchor)
        if position is None:
            continue
        lines = [*remaining[:position + 1], "", reference, "", *remaining[position + 1:]]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines))


def _find_line(lines: list[str], anchor: str) -> int | None:
    """找到以 anchor 的结尾收尾的那一行（先用较长的结尾匹配，逐步放宽）。"""
    for size in (16, 10, 6):
        tail = anchor[-size:]
        if len(tail) < 4:
            break
        matches = [index for index, line in enumerate(lines) if tail in _squash(line)]
        if matches:
            return matches[-1]
    return None


def reflow_paragraphs(markdown: str) -> str:
    """把 PDF 排版造成的硬换行接回去。

    - 段内折行：相邻的两行正文直接相连；
    - 被空行隔开的折行：上一行足够长、又没有以句末标点结束，说明这句话没写完，同样接上。
    中文之间直接相连，西文之间补一个空格。标题、表格、代码块、图片保持原样。
    """
    lines: list[str] = []
    in_fence = False
    for line in markdown.split("\n"):
        if re.match(r"^\s*(```|~~~)", line):
            in_fence = not in_fence
            lines.append(line)
            continue
        if in_fence or not line.strip() or _STARTS_BLOCK.match(line):
            lines.append(line)
            continue

        last = len(lines) - 1
        while last >= 0 and not lines[last].strip():
            last -= 1
        previous = lines[last] if last >= 0 else ""
        adjacent = last == len(lines) - 1
        unfinished = len(previous.strip()) >= _MIN_WRAPPED_LINE and previous.rstrip()[-1:] not in _SENTENCE_END
        if previous.strip() and not _CLOSED.match(previous) and (adjacent or unfinished):
            left, right = previous.rstrip(), line.strip()
            joiner = "" if _CJK.match(left[-1]) or _CJK.match(right[0]) else " "
            del lines[last + 1:]
            lines[last] = left + joiner + right
        else:
            lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
