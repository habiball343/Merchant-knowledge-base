"""向量模型客户端：OpenAI 兼容的 /embeddings 接口。

本地的 Text Embeddings Inference、云端的各类向量服务都支持这套协议，换模型只需要改配置。
"""
import httpx


class EmbeddingError(RuntimeError):
    pass


class EmbeddingClient:
    def __init__(self, base_url: str, model: str, api_key: str = "", dim: int = 1024, batch_size: int = 16,
                 http: httpx.AsyncClient | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dim = dim
        self.batch_size = max(1, batch_size)
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        # 本地服务直连，不读取系统代理设置
        self._http = http or httpx.AsyncClient(timeout=120, trust_env=False, headers=headers)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """返回与输入一一对应的向量。"""
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            vectors.extend(await self._embed_batch(texts[start:start + self.batch_size]))
        return vectors

    async def embed_one(self, text: str) -> list[float]:
        return (await self.embed([text]))[0]

    async def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        try:
            response = await self._http.post(f"{self.base_url}/embeddings", json={"model": self.model, "input": batch})
            response.raise_for_status()
            data = sorted(response.json()["data"], key=lambda item: item["index"])
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise EmbeddingError(f"向量模型调用失败：{type(exc).__name__}: {exc}") from exc
        vectors = [item["embedding"] for item in data]
        if len(vectors) != len(batch):
            raise EmbeddingError(f"向量模型返回了 {len(vectors)} 个向量，期望 {len(batch)} 个")
        if vectors and len(vectors[0]) != self.dim:
            raise EmbeddingError(
                f"向量维度为 {len(vectors[0])}，与配置的 EMBEDDING_DIM={self.dim} 不一致")
        return vectors

    async def healthy(self) -> bool:
        try:
            await self.embed(["健康检查"])
            return True
        except EmbeddingError:
            return False

    async def close(self) -> None:
        await self._http.aclose()
