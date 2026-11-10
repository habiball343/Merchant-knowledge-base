"""把 Markdown 资料切成适合检索的片段。

切分遵循文档自身的结构，而不是按固定长度硬切：

1. 按标题把文档拆成章节（代码块里的 ``#`` 不算标题）；
2. 超长的章节再按"段落 → 行 → 句子"的顺序逐级细分，表格和代码块尽量保持完整；
3. 过短的相邻片段在同一个上级标题下合并，避免出现只有一两句话的碎片。

每个片段都带着自己的标题和上级标题，检索命中后能看出它在原文中的位置。
"""
import re
from dataclasses import dataclass
from html.parser import HTMLParser

_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
# 细分时依次尝试的切分点：先保住行，再保住句子，最后才在词语之间断开
_SEPARATORS = ["\n", "。", "！", "？", "；", ". ", "! ", "? ", "; ", "，", ", ", " "]
_TITLE_MAX_CHARS = 120


@dataclass
class Chunk:
    title: str          # 片段所属的标题（纯文本，不含 #）
    parent_title: str   # 上一级标题，顶层章节为空
    content: str        # 片段正文，包含标题行
    seq: int = 0        # 在文档中的顺序


@dataclass
class _Piece:
    titles: list[str]   # 片段包含的各个章节标题（合并后会有多个）
    parent: str         # 第一个章节的上级标题
    text: str

    @property
    def own(self) -> str:
        return _base(self.titles[0])

    @property
    def title(self) -> str:
        return "、".join(self.titles)[:_TITLE_MAX_CHARS]


def split_markdown(markdown: str, file_title: str, max_chars: int = 480, min_chars: int = 120) -> list[Chunk]:
    if max_chars <= min_chars or min_chars <= 0:
        raise ValueError("切片长度参数无效：需要 0 < min_chars < max_chars")
    text = html_tables_to_markdown((markdown or "").replace("\r\n", "\n").replace("\r", "\n"))

    pieces: list[_Piece] = []
    for heading_line, title, parent, body in _split_by_headings(text, file_title):
        body = body.strip("\n")
        if not body.strip():
            continue  # 只有标题没有正文：它的标题会作为下级片段的 parent_title 保留下来
        prefix = f"{heading_line}\n\n" if heading_line else ""
        if len(prefix) + len(body) <= max_chars:
            pieces.append(_Piece([title], parent, prefix + body))
            continue
        parts = split_text(body, max(max_chars - len(prefix), min_chars))
        for index, part in enumerate(parts, 1):
            part_title = f"{title}（{index}/{len(parts)}）" if len(parts) > 1 else title
            pieces.append(_Piece([part_title], parent, prefix + part))

    merged = _merge_short(pieces, max_chars, min_chars)
    return [Chunk(piece.title, piece.parent, piece.text, seq) for seq, piece in enumerate(merged)]


# ---------------------------------------------------------------------- 按标题拆章节

def _split_by_headings(text: str, file_title: str) -> list[tuple[str, str, str, str]]:
    """返回 [(标题行, 标题文本, 上级标题文本, 正文)]。第一个标题之前的内容归到文件名下。"""
    sections: list[tuple[str, str, str, str]] = []
    hierarchy = [""] * 7                     # hierarchy[n] 是当前所处的 n 级标题
    heading_line, title, level = "", file_title, 0
    body: list[str] = []
    in_fence = False

    def flush() -> None:
        parent = next((hierarchy[i] for i in range(level - 1, 0, -1) if hierarchy[i]), "")
        sections.append((heading_line, title, parent, "\n".join(body)))

    for line in text.split("\n"):
        if _FENCE.match(line):
            in_fence = not in_fence
        match = None if in_fence else _HEADING.match(line)
        if not match:
            body.append(line)
            continue
        flush()
        level = len(match.group(1))
        title = _plain(match.group(2))[:_TITLE_MAX_CHARS]
        heading_line = f"{'#' * level} {title}"
        hierarchy[level] = title
        for deeper in range(level + 1, 7):
            hierarchy[deeper] = ""
        body = []
    flush()
    return sections


def _plain(heading: str) -> str:
    """去掉标题里的加粗、行内代码等标记，只留文字。"""
    return re.sub(r"[*_`]+", "", heading).strip()


# ---------------------------------------------------------------------- 超长正文细分

def split_text(text: str, limit: int) -> list[str]:
    """把一段正文切成若干不超过 limit 个字符的部分，切分点尽量落在自然边界上。"""
    atoms: list[str] = []
    for block in _blocks(text):
        if len(block) <= limit:
            atoms.append(block + "\n\n")
        elif _is_table(block):
            atoms.extend(part + "\n\n" for part in _split_table(block, limit))
        else:
            parts = _atomize(block, limit, _SEPARATORS)
            parts[-1] += "\n\n"
            atoms.extend(parts)

    parts: list[str] = []
    buffer = ""
    for atom in atoms:
        if buffer and len((buffer + atom).strip()) > limit:
            parts.append(buffer.strip())
            buffer = ""
        buffer += atom
    if buffer.strip():
        parts.append(buffer.strip())
    return parts


def _blocks(text: str) -> list[str]:
    """按空行分段；代码块内部的空行不算分段点。"""
    blocks: list[str] = []
    current: list[str] = []
    in_fence = False
    for line in text.split("\n"):
        if _FENCE.match(line):
            in_fence = not in_fence
        if not line.strip() and not in_fence:
            if current:
                blocks.append("\n".join(current))
                current = []
        else:
            current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


def _atomize(text: str, limit: int, separators: list[str]) -> list[str]:
    """递归地把文本拆成不超过 limit 的最小单元，分隔符保留在前一个单元的末尾。"""
    if len(text) <= limit:
        return [text]
    for index, separator in enumerate(separators):
        pieces = text.split(separator)
        if len(pieces) == 1:
            continue
        units = [piece + separator for piece in pieces[:-1]] + ([pieces[-1]] if pieces[-1] else [])
        atoms: list[str] = []
        for unit in units:
            atoms.extend(_atomize(unit, limit, separators[index + 1:]) if len(unit.strip()) > limit else [unit])
        return atoms
    return [text[start:start + limit] for start in range(0, len(text), limit)]


def _is_table(block: str) -> bool:
    lines = block.split("\n")
    return len(lines) >= 3 and all(line.lstrip().startswith("|") for line in lines) and bool(
        re.match(r"^\s*\|?\s*:?-{2,}", lines[1].replace(" ", "")))


def _split_table(block: str, limit: int) -> list[str]:
    """超长表格按行拆开，每一部分都带上表头，拆开后仍然读得懂每一列是什么。"""
    lines = block.split("\n")
    header = "\n".join(lines[:2])
    parts: list[str] = []
    rows: list[str] = []
    for row in lines[2:]:
        if rows and len(header) + sum(len(item) + 1 for item in rows) + len(row) + 1 > limit:
            parts.append(header + "\n" + "\n".join(rows))
            rows = []
        rows.append(row)
    if rows:
        parts.append(header + "\n" + "\n".join(rows))
    return parts


# ---------------------------------------------------------------------- 合并过短片段

def _merge_short(pieces: list[_Piece], max_chars: int, min_chars: int) -> list[_Piece]:
    """把过短的片段并入同一上级标题下的相邻片段（优先并入后一个，其次前一个）。"""
    merged: list[_Piece] = []
    index = 0
    while index < len(pieces):
        current = pieces[index]
        index += 1
        # 向后合并：当前片段太短时，持续吸收同一上级标题下的后续片段
        while (len(current.text) < min_chars and index < len(pieces)
               and _siblings(current, pieces[index])
               and len(current.text) + 2 + len(pieces[index].text) <= max_chars):
            current = _join(current, pieces[index])
            index += 1
        # 向前合并：最后一个孤立的短片段并入前一个
        if (len(current.text) < min_chars and merged and _siblings(merged[-1], current)
                and len(merged[-1].text) + 2 + len(current.text) <= max_chars):
            merged[-1] = _join(merged[-1], current)
        else:
            merged.append(current)
    return merged


def _siblings(first: _Piece, second: _Piece) -> bool:
    """哪些相邻片段可以合并：同一章节拆出的几部分、同一上级标题下的小节、章节导语和它的第一个小节。"""
    if second.parent == first.own:
        return True                                   # first 是 second 所在章节的导语
    if first.parent != second.parent:
        return False
    return bool(first.parent) or first.own == second.own   # 顶层章节之间不合并，除非是同一章节的几部分


def _base(title: str) -> str:
    return re.sub(r"（\d+/\d+）$", "", title)


def _join(first: _Piece, second: _Piece) -> _Piece:
    """合并后的标题列出所包含的各个小节；同一章节的几部分合回去后恢复原标题。"""
    titles = list(dict.fromkeys(_base(title) for title in [*first.titles, *second.titles]))
    return _Piece(titles, first.parent, f"{first.text}\n\n{second.text}")


# ---------------------------------------------------------------------- HTML 表格

class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.rows.append([])
        elif tag in ("td", "th"):
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None:
            text = re.sub(r"\s+", " ", "".join(self._cell)).strip().replace("|", "\\|")
            if self.rows:
                self.rows[-1].append(text)
            self._cell = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def html_tables_to_markdown(text: str) -> str:
    """把 PDF 解析器输出的 HTML 表格转成 Markdown 表格，便于按行切分和阅读。"""
    def convert(match: re.Match) -> str:
        parser = _TableParser()
        parser.feed(match.group(0))
        rows = [row for row in parser.rows if any(cell for cell in row)]
        if not rows:
            return ""
        width = max(len(row) for row in rows)
        rows = [row + [""] * (width - len(row)) for row in rows]
        lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width]
        lines += ["| " + " | ".join(row) + " |" for row in rows[1:]]
        return "\n\n" + "\n".join(lines) + "\n\n"

    return re.sub(r"<table\b.*?</table>", convert, text, flags=re.S | re.I)
