"""日志：控制台 + 滚动文件。"""
import sys

from loguru import logger

from app.config import BACKEND_ROOT

_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <7}</level> | "
    "<cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)

logger.remove()
logger.add(sys.stdout, level="INFO", format=_FORMAT)


def enable_file_logging() -> None:
    log_dir = BACKEND_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    logger.add(log_dir / "app.log", level="INFO", format=_FORMAT, rotation="10 MB", retention="7 days",
               encoding="utf-8")


__all__ = ["logger", "enable_file_logging"]
