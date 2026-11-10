import mimetypes
import re
from pathlib import Path
from urllib.parse import unquote

from langgraph.runtime import Runtime

from app.ingest.images import find_images, image_context, is_remote, replace_image
from app.ingest.rate_limit import SlidingWindowLimiter
from app.ingest.state import IngestContext, IngestState
from app.logging import logger
from app.pipeline import stage

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
_FALLBACK_CAPTION = "插图"


@stage("process_images", "处理图片")
async def process_images(state: IngestState, runtime: Runtime[IngestContext]) -> dict:
    """把资料里的本地图片转存到文件存储，并用视觉模型给每张图写一句说明。

    说明文字写入图片的 alt 文本，之后随正文一起被切片和检索；
    回答问题时，模型可以直接引用图片地址，把图放进答案里。
    """
    context = runtime.context
    markdown = state["markdown"]
    base_dir = Path(state["base_dir"])
    doc_id = state["doc_id"]
    captioner = context["captioner"]
    limiter = SlidingWindowLimiter(context["settings"].vision_requests_per_minute)

    stored = 0
    for ref in find_images(markdown):
        if is_remote(ref.target):
            continue
        path = _resolve(base_dir, ref.target)
        if path is None:
            # 引用了不存在的图片：去掉失效的链接，保留原有的说明文字
            markdown = _drop_image(markdown, ref.target, ref.alt)
            continue

        heading, nearby = image_context(markdown, ref)
        caption = ref.alt or heading or _FALLBACK_CAPTION
        if captioner is not None:
            try:
                await limiter.acquire()
                mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
                text = await captioner.caption(
                    path.read_bytes(), mime_type, state["file_title"], "\n".join(filter(None, [heading, nearby])))
                caption = _clean_caption(text) or caption
            except Exception as exc:
                logger.warning("图片 {} 的说明生成失败，使用默认说明：{}", path.name, exc)

        url = context["object_store"].save_file(f"{doc_id}/images/{_safe_name(path.name)}", path)
        markdown = replace_image(markdown, ref.target, caption, url)
        stored += 1

    # 保存处理后的 Markdown，便于在页面上核对解析结果
    context["object_store"].save_bytes(f"{doc_id}/document.md", markdown.encode("utf-8"))
    detail = f"{stored} 张图片" + ("" if captioner or not stored else "，未配置视觉模型，沿用原有说明")
    return {"markdown": markdown, "image_count": stored, "_detail": detail}


def _resolve(base_dir: Path, target: str) -> Path | None:
    """把 Markdown 里的相对路径解析为工作目录内的图片文件；越界或不存在时返回 None。"""
    candidate = Path(unquote(target))
    path = candidate if candidate.is_absolute() else base_dir / candidate
    try:
        path = path.resolve()
    except OSError:
        return None
    # 只接受工作目录内的图片：上传的 Markdown 不能借图片引用读取服务器上的其他文件
    if not path.is_relative_to(base_dir.resolve()):
        return None
    if not path.is_file() or path.suffix.lower() not in _IMAGE_SUFFIXES:
        return None
    return path


def _safe_name(name: str) -> str:
    return re.sub(r"[^\w.\-]+", "_", name, flags=re.UNICODE)


def _clean_caption(text: str) -> str:
    line = next((item.strip() for item in (text or "").splitlines() if item.strip()), "")
    return line.strip("\"'“”「」。 ")[:80]


def _drop_image(markdown: str, target: str, alt: str) -> str:
    pattern = re.compile(r"!\[[^\]]*\]\(<?" + re.escape(target) + r">?(?:\s+\"[^\"]*\")?\)")
    return pattern.sub(alt, markdown)
