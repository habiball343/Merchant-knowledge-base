"""MongoDB 访问层：文档台账与对话历史。"""
import time
from typing import Any

from pymongo import ASCENDING, DESCENDING, AsyncMongoClient


class DocumentRegistry:
    """文档台账：记录每份资料的导入状态。台账是持久化的，服务重启后文档列表仍在。"""

    def __init__(self, client: AsyncMongoClient, db_name: str):
        self._documents = client[db_name]["documents"]

    async def create(self, document: dict[str, Any]) -> None:
        now = time.time()
        await self._documents.insert_one({**document, "_id": document["doc_id"], "created_at": now, "updated_at": now})

    async def update(self, doc_id: str, **fields: Any) -> None:
        await self._documents.update_one({"_id": doc_id}, {"$set": {**fields, "updated_at": time.time()}})

    async def push_step(self, doc_id: str, step: dict[str, Any]) -> None:
        """追加一条已完成的处理步骤，页面上据此展示导入过程。"""
        await self._documents.update_one(
            {"_id": doc_id}, {"$push": {"steps": step}, "$set": {"updated_at": time.time()}})

    async def get(self, doc_id: str) -> dict[str, Any] | None:
        return _public(await self._documents.find_one({"_id": doc_id}))

    async def list_documents(self) -> list[dict[str, Any]]:
        cursor = self._documents.find().sort("created_at", DESCENDING)
        return [_public(document) async for document in cursor]

    async def delete(self, doc_id: str) -> None:
        await self._documents.delete_one({"_id": doc_id})

    async def find_completed_by_file_name(self, file_name: str, exclude_doc_id: str) -> list[dict[str, Any]]:
        cursor = self._documents.find({"file_name": file_name, "status": "completed", "_id": {"$ne": exclude_doc_id}})
        return [_public(document) async for document in cursor]

    async def count_by_product(self, product: str) -> int:
        return await self._documents.count_documents({"product": product, "status": "completed"})

    async def fail_interrupted(self) -> int:
        """服务启动时调用：上次运行中途被打断的导入任务不会自己恢复，标记为失败并说明原因。"""
        result = await self._documents.update_many(
            {"status": {"$in": ["pending", "processing"]}},
            {"$set": {"status": "failed", "error": "服务重启，导入被中断。请重新上传。", "updated_at": time.time()}})
        return result.modified_count


class ChatHistory:
    """对话历史：按会话保存问答，供指代消解和多轮追问使用。"""

    def __init__(self, client: AsyncMongoClient, db_name: str):
        self._messages = client[db_name]["messages"]

    async def ensure_indexes(self) -> None:
        await self._messages.create_index([("session_id", ASCENDING), ("ts", ASCENDING)])

    async def append(self, session_id: str, role: str, text: str, **extra: Any) -> None:
        await self._messages.insert_one({"session_id": session_id, "role": role, "text": text, "ts": time.time(), **extra})

    async def recent(self, session_id: str, limit: int = 8) -> list[dict[str, Any]]:
        """最近的 limit 条消息，按时间正序返回。"""
        cursor = self._messages.find({"session_id": session_id}).sort("ts", DESCENDING).limit(limit)
        messages = [_public(message) async for message in cursor]
        return list(reversed(messages))

    async def clear(self, session_id: str) -> int:
        return (await self._messages.delete_many({"session_id": session_id})).deleted_count


def _public(document: dict[str, Any] | None) -> dict[str, Any] | None:
    if document is None:
        return None
    document = dict(document)
    document["_id"] = str(document["_id"])
    return document
