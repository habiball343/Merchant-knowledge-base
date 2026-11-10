"""重排序模型客户端：Text Embeddings Inference 的 /rerank 接口。

交叉编码器把"问题 + 资料"一起送进模型打分，比向量相似度准确得多，但也慢得多，
所以只用来给融合后的少量候选排序。返回的分数已归一化到 0~1。
"""
import httpx


class RerankError(RuntimeError):
    pass


class RerankClient:
    def __init__(self, base_url: str, batch_size: int = 16, http: httpx.AsyncClient | None = None):
        self.base_url = base_url.rstrip("/")
        self.batch_size = max(1, batch_size)
        self._http = http or httpx.AsyncClient(timeout=120, trust_env=False)

    async def score(self, query: str, texts: list[str]) -> list[float]:
        """返回与 texts 一一对应的相关性分数。"""
        scores: list[float] = [0.0] * len(texts)
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start:start + self.batch_size]
            try:
                response = await self._http.post(
                    f"{self.base_url}/rerank", json={"query": query, "texts": batch, "truncate": True})
                response.raise_for_status()
                for item in response.json():
                    scores[start + item["index"]] = float(item["score"])
            except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
                raise RerankError(f"重排序模型调用失败：{type(exc).__name__}: {exc}") from exc
        return scores

    async def healthy(self) -> bool:
        try:
            response = await self._http.get(f"{self.base_url}/health", timeout=5)
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def close(self) -> None:
        await self._http.aclose()
