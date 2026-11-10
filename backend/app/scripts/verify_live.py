"""端到端验收：导入示例资料，再用一组问题检查问答链路。

    uv run python -m app.scripts.verify_live

需要后端和全部依赖服务已启动，会调用真实的大模型。
检查的是"有没有找对商品、有没有检索到包含答案的资料"，而不是回答的措辞——
前者是可以确定地判断对错的，后者不是。报告写入项目根目录的 .local/verification.json。
"""
import asyncio
import json
import time
from datetime import datetime
from pathlib import Path

import httpx

from app.config import PROJECT_ROOT, get_settings

SAMPLES = ["ZG-12 数字万用表使用手册.md", "ZG-20 钳形万用表使用手册.md", "ZG-3000 空气炸锅使用手册.pdf"]

# (会话, 问题, 期望确认的商品, 期望出现在资料中的文字)；期望商品为 None 表示应当请用户澄清
CASES = [
    ("a", "ZG-12 怎么更换电池？", "ZG-12 数字万用表", "6F22"),
    ("b", "钳形表怎么测量交流电流", "ZG-20 钳形万用表", "钳口"),
    ("c", "ZG-3000 烤红薯要多长时间", "ZG-3000 空气炸锅", "40 分钟"),
    ("c", "它显示 E2 是什么意思", "ZG-3000 空气炸锅", "过热保护"),
    ("d", "万用表的保修期是多久", None, ""),
    ("e", "ZG-13 数字万用表怎么测电压", None, ""),
]


async def import_samples(client: httpx.AsyncClient) -> list[dict]:
    files = [("files", (name, (PROJECT_ROOT / "samples" / name).read_bytes())) for name in SAMPLES]
    response = await client.post("/api/documents", files=files)
    response.raise_for_status()
    pending = {item["doc_id"] for item in response.json()["accepted"]}
    documents: dict[str, dict] = {}
    deadline = time.monotonic() + 1800
    while pending and time.monotonic() < deadline:
        await asyncio.sleep(2)
        for doc_id in list(pending):
            document = (await client.get(f"/api/documents/{doc_id}")).json()
            if document["status"] in ("completed", "failed"):
                documents[doc_id] = document
                pending.discard(doc_id)
                print(f"导入 {document['file_name']}: {document['status']}，商品「{document['product']}」，"
                      f"{document['chunk_count']} 个片段，{document['image_count']} 张图片 {document['error']}", flush=True)
    return list(documents.values())


async def ask(client: httpx.AsyncClient, session_id: str, question: str) -> dict:
    events = []
    async with client.stream("POST", "/api/chat/stream", json={"query": question, "session_id": session_id}) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))
    final = next((event for event in events if event["type"] == "final"), None)
    error = next((event["message"] for event in events if event["type"] == "error"), "")
    return {"final": final, "error": error,
            "stages": [event["node"] for event in events if event["type"] == "stage" and event["status"] == "done"]}


async def verify() -> bool:
    settings = get_settings()
    run = datetime.now().strftime("%H%M%S")
    results = []
    async with httpx.AsyncClient(base_url=f"http://{settings.app_host}:{settings.app_port}",
                                 timeout=300, trust_env=False) as client:
        documents = await import_samples(client)
        imported = len(documents) == len(SAMPLES) and all(item["status"] == "completed" for item in documents)

        for session, question, product, evidence in CASES if imported else []:
            started = time.perf_counter()
            outcome = await ask(client, f"verify-{run}-{session}", question)
            final = outcome["final"] or {}
            if product is None:
                passed = bool(final.get("needs_clarification")) and not final.get("sources")
            else:
                texts = "\n".join(source["content"] for source in final.get("sources", []))
                passed = final.get("products") == [product] and evidence in texts and bool(final.get("answer"))
            item = {
                "question": question, "passed": passed, "elapsed_seconds": round(time.perf_counter() - started, 2),
                "products": final.get("products"), "options": final.get("options"),
                "sources": [f"{source['file_title']}｜{source['title']}（{source['score']}）" for source in final.get("sources", [])],
                "answer": final.get("answer", ""), "error": outcome["error"],
            }
            results.append(item)
            print(json.dumps({key: item[key] for key in ("question", "passed", "products", "options", "sources", "error")},
                             ensure_ascii=False), flush=True)
            if outcome["error"]:
                break  # 密钥或额度问题：不再继续消耗模型请求

    report = {
        "time": datetime.now().astimezone().isoformat(),
        "all_passed": imported and len(results) == len(CASES) and all(item["passed"] for item in results),
        "documents": [{key: document[key] for key in ("file_name", "status", "product", "chunk_count", "image_count", "error")}
                      for document in documents],
        "cases": results,
    }
    path = PROJECT_ROOT / ".local" / "verification.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("全部通过" if report["all_passed"] else "存在未通过的检查", flush=True)
    return report["all_passed"]


if __name__ == "__main__":
    raise SystemExit(0 if asyncio.run(verify()) else 1)
