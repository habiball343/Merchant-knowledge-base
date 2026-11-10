"""Markdown 中图片引用的查找、上下文提取与替换。"""
import re
from dataclasses import dataclass

# ![说明](路径 "可选标题")
_IMAGE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<target><[^>]+>|[^)\s]+)(?:\s+\"[^\"]*\")?\)")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")


@dataclass(frozen=True)
class ImageRef:
    alt: str
    target: str     # Markdown 里写的路径或 URL（去掉了尖括号）
    line: int       # 所在行号（从 0 开始）


def find_images(markdown: str) -> list[ImageRef]:
    """按出现顺序返回图片引用；同一张图片被多次引用时只返回第一次。"""
    seen: set[str] = set()
    refs: list[ImageRef] = []
    for number, line in enumerate(markdown.split("\n")):
        for match in _IMAGE.finditer(line):
            target = match.group("target").strip("<>")
            if target not in seen:
                seen.add(target)
                refs.append(ImageRef(match.group("alt").strip(), target, number))
    return refs


def is_remote(target: str) -> bool:
    return bool(re.match(r"^(https?:)?//|^data:", target, re.I))


def image_context(markdown: str, ref: ImageRef, max_chars: int = 200) -> tuple[str, str]:
    """返回（所在章节的标题, 图片前后的正文）。

    只在图片所在的章节内取上下文，并且优先取离图片最近的段落——
    图片说明要靠它旁边的文字来理解，隔了一个章节的内容帮不上忙。
    """
    lines = markdown.split("\n")
    start = 0
    heading = ""
    for index in range(ref.line - 1, -1, -1):
        match = _HEADING.match(lines[index])
        if match:
            heading, start = match.group(1), index + 1
            break
    end = len(lines)
    for index in range(ref.line + 1, len(lines)):
        if _HEADING.match(lines[index]):
            end = index
            break

    before = _nearest_paragraphs(lines[start:ref.line], max_chars, from_end=True)
    after = _nearest_paragraphs(lines[ref.line + 1:end], max_chars, from_end=False)
    return heading, "\n\n".join(part for part in (before, after) if part)


def _nearest_paragraphs(lines: list[str], max_chars: int, from_end: bool) -> str:
    paragraphs: list[str] = []
    current: list[str] = []
    for line in lines:
        text = line.strip()
        if not text or _IMAGE.fullmatch(text):
            if current:
                paragraphs.append("\n".join(current))
                current = []
        else:
            current.append(text)
    if current:
        paragraphs.append("\n".join(current))

    ordered = reversed(paragraphs) if from_end else paragraphs
    picked: list[str] = []
    total = 0
    for paragraph in ordered:
        if picked and total + len(paragraph) > max_chars:
            break
        picked.append(paragraph[:max_chars])
        total += len(paragraph)
    if from_end:
        picked.reverse()
    return "\n\n".join(picked)


def replace_image(markdown: str, target: str, alt: str, url: str) -> str:
    """把指向 target 的图片引用全部替换成新的说明文字和地址。"""
    clean_alt = re.sub(r"[\[\]\n\r]+", " ", alt).strip()

    def substitute(match: re.Match) -> str:
        if match.group("target").strip("<>") != target:
            return match.group(0)
        return f"![{clean_alt}]({url})"

    return _IMAGE.sub(substitute, markdown)
