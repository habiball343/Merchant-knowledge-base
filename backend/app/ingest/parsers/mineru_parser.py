"""MinerU 解析器：调用 MinerU 命令行把 PDF 转成 Markdown。

MinerU 基于版面分析模型，能处理多栏排版、公式、复杂表格和扫描件，但需要单独安装并下载模型。
"""
import shlex
import subprocess
from pathlib import Path

from app.ingest.parsers.base import ParsedDocument, PdfParseError
from app.logging import logger


class MinerUParser:
    name = "mineru"

    def __init__(self, command: str = "mineru", timeout: int = 3600):
        self.command = shlex.split(command)
        self.timeout = timeout

    def parse(self, pdf_path: Path, work_dir: Path) -> ParsedDocument:
        output_dir = work_dir / "mineru"
        output_dir.mkdir(parents=True, exist_ok=True)
        command = [*self.command, "-p", str(pdf_path), "-o", str(output_dir)]
        logger.info("调用 MinerU：{}", " ".join(command))
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=self.timeout)
        except FileNotFoundError as exc:
            raise PdfParseError(f"找不到 MinerU 命令：{self.command[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            raise PdfParseError(f"MinerU 解析超时（{self.timeout} 秒）") from exc
        if completed.returncode != 0:
            tail = (completed.stderr or completed.stdout or "").strip().splitlines()[-3:]
            raise PdfParseError(f"MinerU 解析失败（退出码 {completed.returncode}）：{' | '.join(tail)}")

        markdown_path = self._find_markdown(output_dir, pdf_path.stem)
        return ParsedDocument(markdown=markdown_path.read_text(encoding="utf-8"), base_dir=markdown_path.parent)

    @staticmethod
    def _find_markdown(output_dir: Path, stem: str) -> Path:
        """MinerU 的输出目录是 <输出目录>/<文件名>/<解析方式>/<文件名>.md，解析方式随版本和参数变化。"""
        candidates = sorted(output_dir.rglob(f"{stem}.md")) or sorted(output_dir.rglob("*.md"))
        if not candidates:
            raise PdfParseError("MinerU 执行成功，但没有找到输出的 Markdown 文件")
        return candidates[0]
