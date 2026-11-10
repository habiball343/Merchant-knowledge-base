"""HTTP 接口：上传与文档管理、问答（SSE 与非流式）、历史、文件与健康检查。"""
import json
import time

import pytest
from fastapi.testclient import TestClient

from main import create_app
from tests.fakes import FakeContainer, ScriptedLLM
from tests.pdf_factory import make_manual_pdf
from tests.test_query_flow import AIR_FRYER, MULTIMETER


@pytest.fixture
def client(tmp_path):
    llm = ScriptedLLM(extraction={"item_names": ["ZG-12"], "rewritten_query": "ZG-12 数字万用表怎么更换电池"})
    container = FakeContainer(tmp_path, llm=llm)
    with TestClient(create_app(container)) as test_client:
        test_client.container = container
        yield test_client


def upload(client, name, content, product=""):
    response = client.post("/api/documents", files=[("files", (name, content))], data={"product": product})
    return response


def wait_for(client, doc_id, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        document = client.get(f"/api/documents/{doc_id}").json()
        if document["status"] in ("completed", "failed"):
            return document
        time.sleep(0.05)
    raise AssertionError("导入没有在规定时间内结束")


def sse(response) -> list[dict]:
    assert response.headers["content-type"].startswith("text/event-stream")
    blocks = [block for block in response.text.split("\n\n") if block.strip()]
    assert all(block.startswith("data: ") for block in blocks)
    return [json.loads(block[len("data: "):]) for block in blocks]


def seed(client):
    first = upload(client, "ZG-12使用手册.md", MULTIMETER.encode("utf-8"), "ZG-12 数字万用表").json()["accepted"][0]
    second = upload(client, "ZG-3000使用手册.md", AIR_FRYER.encode("utf-8"), "ZG-3000 空气炸锅").json()["accepted"][0]
    return wait_for(client, first["doc_id"]), wait_for(client, second["doc_id"])


# ---------------------------------------------------------------- 文档

def test_upload_returns_immediately_and_progress_is_visible_until_completion(client):
    response = upload(client, "ZG-12使用手册.md", MULTIMETER.encode("utf-8"))

    assert response.status_code == 202
    accepted = response.json()["accepted"]
    assert accepted[0]["file_name"] == "ZG-12使用手册.md" and accepted[0]["status"] == "pending"
    document = wait_for(client, accepted[0]["doc_id"])
    assert document["status"] == "completed" and document["progress"] == 100
    assert document["product"] == "ZG-12 数字万用表" and document["chunk_count"] == 2
    assert [step["label"] for step in document["steps"]][-1] == "写入知识库"
    listing = client.get("/api/documents").json()["items"]
    assert [item["doc_id"] for item in listing] == [document["doc_id"]]
    assert client.get("/api/products").json() == {"items": [{"name": "ZG-12 数字万用表", "documents": 1}]}


def test_mixed_upload_reports_rejected_files_and_imports_the_rest(client):
    response = client.post("/api/documents", files=[
        ("files", ("手册.md", MULTIMETER.encode("utf-8"))),
        ("files", ("报价.xlsx", b"data")),
    ])

    body = response.json()
    assert response.status_code == 202
    assert [item["file_name"] for item in body["accepted"]] == ["手册.md"]
    assert body["rejected"][0]["file_name"] == "报价.xlsx" and "不支持" in body["rejected"][0]["reason"]


def test_upload_with_nothing_acceptable_is_a_400(client):
    response = upload(client, "报价.xlsx", b"data")

    assert response.status_code == 400
    assert response.json()["detail"]["rejected"][0]["file_name"] == "报价.xlsx"
    assert client.get("/api/documents").json() == {"items": []}


def test_pdf_images_are_served_back_through_the_files_endpoint(client, tmp_path):
    pdf = make_manual_pdf(tmp_path / "ZG-12使用手册.pdf")
    doc_id = upload(client, pdf.name, pdf.read_bytes(), "ZG-12 数字万用表").json()["accepted"][0]["doc_id"]
    document = wait_for(client, doc_id)

    assert document["status"] == "completed" and document["image_count"] == 1
    markdown = client.get(f"/api/files/{doc_id}/document.md")
    assert markdown.status_code == 200
    image_url = markdown.text.split("](")[1].split(")")[0]
    image = client.get(image_url)
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"
    assert client.get(f"/api/files/{doc_id}/source/{pdf.name}").status_code == 200


@pytest.mark.parametrize("key", ["no-such-doc/a.png", "..%2F..%2Fetc%2Fpasswd", "doc/..%2F..%2Fsecret"])
def test_files_endpoint_never_serves_anything_outside_the_store(client, key):
    assert client.get(f"/api/files/{key}").status_code == 404


def test_delete_removes_the_document_and_its_chunks(client):
    multimeter, _ = seed(client)

    assert client.delete(f"/api/documents/{multimeter['doc_id']}").json() == {"deleted": multimeter["doc_id"]}

    assert client.get(f"/api/documents/{multimeter['doc_id']}").status_code == 404
    assert client.delete(f"/api/documents/{multimeter['doc_id']}").status_code == 404
    assert [item["name"] for item in client.get("/api/products").json()["items"]] == ["ZG-3000 空气炸锅"]
    assert all(chunk["doc_id"] != multimeter["doc_id"] for chunk in client.container.vector_store.chunks.values())


# ---------------------------------------------------------------- 问答

def test_stream_reports_session_stages_sources_deltas_and_final(client):
    seed(client)

    events = sse(client.post("/api/chat/stream", json={"query": " ZG-12 怎么更换电池 "}))

    assert events[0]["type"] == "session" and len(events[0]["session_id"]) == 32
    types = [event["type"] for event in events]
    assert types[-1] == "final" and "error" not in types
    assert types.index("products") < types.index("sources") < types.index("delta")
    final = events[-1]
    assert final["session_id"] == events[0]["session_id"]
    assert final["answer"] == "".join(event["text"] for event in events if event["type"] == "delta")
    assert final["products"] == ["ZG-12 数字万用表"] and final["needs_clarification"] is False
    assert final["sources"][0]["title"] == "更换电池" and "取出旧的 9V 电池" in final["sources"][0]["content"]
    assert set(final["sources"][0]) >= {"index", "source", "product", "file_title", "title", "score", "snippet", "routes"}


def test_clarification_is_a_normal_final_event_with_options(client):
    seed(client)
    client.container.llm.extraction = {"item_names": [], "rewritten_query": "怎么清洁"}

    events = sse(client.post("/api/chat/stream", json={"query": "怎么清洁", "session_id": "abc"}))

    final = events[-1]
    assert final["needs_clarification"] is True and final["sources"] == []
    assert final["options"] == ["ZG-12 数字万用表", "ZG-3000 空气炸锅"]
    assert events[0] == {"type": "session", "session_id": "abc"}


def test_non_stream_chat_returns_the_final_result_and_history_is_kept(client):
    seed(client)

    body = client.post("/api/chat", json={"query": "ZG-12 怎么更换电池", "session_id": "s-9"}).json()

    assert body["session_id"] == "s-9" and body["answer"] == client.container.llm.answer
    assert body["sources"] and "type" not in body
    history = client.get("/api/chat/history/s-9").json()
    assert [(item["role"], item["text"]) for item in history["items"]] == [
        ("user", "ZG-12 怎么更换电池"), ("assistant", client.container.llm.answer)]
    assert history["items"][1]["sources"][0]["title"] == "更换电池"
    assert client.delete("/api/chat/history/s-9").json() == {"deleted": 2}
    assert client.get("/api/chat/history/s-9").json()["items"] == []


@pytest.mark.parametrize("body", [{"query": ""}, {"query": "   "}, {"query": "x" * 2001}, {}])
def test_invalid_questions_are_rejected(client, body):
    assert client.post("/api/chat/stream", json=body).status_code == 422
    assert client.post("/api/chat", json=body).status_code == 422


def test_missing_model_key_is_explained_without_running_the_pipeline(tmp_path):
    container = FakeContainer(tmp_path, llm_api_key="")
    with TestClient(create_app(container)) as client:
        events = sse(client.post("/api/chat/stream", json={"query": "怎么换电池"}))
        response = client.post("/api/chat", json={"query": "怎么换电池"})

    assert [event["type"] for event in events] == ["session", "error"]
    assert "LLM_API_KEY" in events[1]["message"]
    assert response.status_code == 502 and "LLM_API_KEY" in response.json()["detail"]
    assert container.llm.prompts == {}


@pytest.mark.parametrize("status,expected", [(401, "密钥无效"), (402, "余额不足"), (429, "限流"), (500, "问答失败")])
def test_model_errors_become_actionable_messages_without_leaking_details(client, status, expected):
    class ProviderError(Exception):
        status_code = status

    seed(client)
    client.container.llm.error = ProviderError("sk-secret-key at https://internal.example/v1")
    client.container.llm.fail_kinds = ("answer",)

    events = sse(client.post("/api/chat/stream", json={"query": "ZG-12 怎么更换电池"}))

    assert events[-1]["type"] == "error" and expected in events[-1]["message"]
    assert "sk-secret-key" not in json.dumps(events, ensure_ascii=False)
    assert not any(event["type"] == "final" for event in events)


def test_unreachable_model_service_is_reported_as_a_connection_problem(client):
    class APIConnectionError(Exception):
        pass

    class APITimeoutError(Exception):
        pass

    seed(client)
    client.container.llm.fail_kinds = ("answer",)
    for error, expected in ((APIConnectionError("http://10.0.0.8:9000 refused"), "连不上模型服务"),
                            (APITimeoutError("timed out"), "响应超时")):
        client.container.llm.error = error
        events = sse(client.post("/api/chat/stream", json={"query": "ZG-12 怎么更换电池"}))
        assert events[-1]["type"] == "error" and expected in events[-1]["message"]
        assert "10.0.0.8" not in json.dumps(events, ensure_ascii=False)


# ---------------------------------------------------------------- 健康检查

def test_health_reports_each_dependency(client):
    body = client.get("/api/health").json()

    assert body["app"] == "merchant-knowledge-base" and body["ready"] is True
    assert body["services"] == {name: {"ok": True} for name in ("milvus", "mongodb", "embedding", "reranker")}
    assert body["model_key_configured"] is True and body["web_search_enabled"] is False


def test_health_is_503_when_a_required_dependency_is_down_but_reranker_is_optional(client):
    client.container.reranker.available = False
    assert client.get("/api/health").status_code == 200

    async def down():
        return False
    client.container.vector_store.healthy = down
    response = client.get("/api/health")
    assert response.status_code == 503 and response.json()["services"]["milvus"] == {"ok": False}
