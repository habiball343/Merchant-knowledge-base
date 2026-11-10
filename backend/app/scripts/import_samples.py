"""把 samples 目录里的三份示例手册导入知识库（需要后端已启动）。

    uv run python -m app.scripts.import_samples
"""
import asyncio

import httpx

from app.config import get_settings
from app.scripts.verify_live import SAMPLES, import_samples


async def main() -> bool:
    settings = get_settings()
    async with httpx.AsyncClient(base_url=f"http://{settings.app_host}:{settings.app_port}",
                                 timeout=300, trust_env=False) as client:
        try:
            documents = await import_samples(client)
        except httpx.TransportError:
            print("连不上后端服务。请先启动后端，再导入示例资料。")
            return False
    return len(documents) == len(SAMPLES) and all(item["status"] == "completed" for item in documents)


if __name__ == "__main__":
    raise SystemExit(0 if asyncio.run(main()) else 1)
