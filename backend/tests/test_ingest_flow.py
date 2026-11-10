"""文档导入流程：用替身模型和内存存储驱动真实的 LangGraph 图与导入服务。"""
import pytest

from app.services.ingest_service import IngestService, UploadRejected
from tests.fakes import FakeCaptioner, FakeContainer, ScriptedLLM
from tests.pdf_factory import make_manual_pdf

MARKDOWN_MANUAL = """# ZG-12 数字万用表使用手册

## 测量直流电压

将旋钮转到直流电压档，红表笔接正极，黑表笔接负极，读取屏幕上的数值。若显示 OL，说明超出量程，请换用更高的量程后重新测量。测量高于 36V 的电压时，手指不要越过表笔的护指环，也不要在潮湿的环境中操作。测量结束后先取下红表笔，再取下黑表笔，并把旋钮转回 OFF 位置。

## 更换电池

屏幕出现电池符号时需要更换电池。拧开后盖的两颗螺丝，取出旧的 9V 电池，按正负极方向装入新电池后装回后盖。更换电池前必须先把表笔从被测电路上取下，并把旋钮转到 OFF 位置。长期不使用时请取出电池，以免电池漏液腐蚀电路板。
""".encode("utf-8")


async def ingest(container, file_name, data, product=""):
    service = IngestService(container)
    record = await service.submit(file_name, data, product)
    await service.wait_idle()
    return service, await container.registry.get(record["doc_id"])


async def test_markdown_is_split_tagged_embedded_and_stored(container):
    _, document = await ingest(container, "ZG-12使用手册.md", MARKDOWN_MANUAL)

    assert document["status"] == "completed" and document["progress"] == 100 and document["error"] == ""
    assert document["product"] == "ZG-12 数字万用表"
    chunks = list(container.vector_store.chunks.values())
    assert document["chunk_count"] == len(chunks) == 2
    assert {chunk["product"] for chunk in chunks} == {"ZG-12 数字万用表"}
    assert {chunk["doc_id"] for chunk in chunks} == {document["doc_id"]}
    assert sorted(chunk["chunk_id"] for chunk in chunks) == [f"{document['doc_id']}-0000", f"{document['doc_id']}-0001"]
    assert all(len(chunk["dense"]) == container.embeddings.dim for chunk in chunks)
    assert container.vector_store.products.keys() == {"ZG-12 数字万用表"}
    # 向量化的文本里带着商品名和上级标题
    embedded = [text for call in container.embeddings.calls for text in call if "测量直流电压" in text]
    assert embedded[0].startswith("ZG-12 数字万用表\nZG-12 数字万用表使用手册\n## 测量直流电压")
    # 导入过程逐步记录在台账里
    assert [step["label"] for step in document["steps"]] == [
        "检查文件", "读取 Markdown", "处理图片", "切分文档", "识别商品", "向量化", "写入知识库"]
    assert (container.settings.data_dir / "files" / document["doc_id"] / "document.md").is_file()
    assert not (container.settings.data_dir / "work" / document["doc_id"]).exists(), "工作目录应在导入后清理"


async def test_product_given_at_upload_skips_the_model(tmp_path):
    llm = ScriptedLLM(product_name="模型不该被问到")
    container = FakeContainer(tmp_path, llm=llm)

    _, document = await ingest(container, "手册.md", MARKDOWN_MANUAL, product=" ZG-12 数字万用表 ")

    assert document["product"] == "ZG-12 数字万用表"
    assert "product_name" not in llm.prompts


@pytest.mark.parametrize("reply", ["UNKNOWN", "", "这份资料讲的是一款用于测量电压电流电阻的手持式数字仪表，具体的品牌和型号在文中没有出现，所以我无法给出准确的商品名称"])
async def test_unrecognizable_product_falls_back_to_the_file_title(tmp_path, reply):
    container = FakeContainer(tmp_path, llm=ScriptedLLM(product_name=reply))

    _, document = await ingest(container, "ZG-12使用手册.md", MARKDOWN_MANUAL)

    assert document["product"] == "ZG-12使用手册"


async def test_model_failure_during_recognition_does_not_fail_the_import(tmp_path):
    container = FakeContainer(tmp_path, llm=ScriptedLLM(error=RuntimeError("模型服务不可用")))

    _, document = await ingest(container, "ZG-12使用手册.md", MARKDOWN_MANUAL)

    assert document["status"] == "completed" and document["product"] == "ZG-12使用手册"


async def test_second_manual_of_the_same_product_joins_the_existing_name(tmp_path):
    container = FakeContainer(tmp_path, llm=ScriptedLLM(product_name="ZG-12 数字万用表"))
    await ingest(container, "使用手册.md", MARKDOWN_MANUAL)
    container.llm.product_name = "ZG-12数字万用表"          # 第二份资料里模型给了略有不同的写法

    _, document = await ingest(container, "快速指南.md", MARKDOWN_MANUAL)

    assert document["product"] == "ZG-12 数字万用表"
    assert list(container.vector_store.products) == ["ZG-12 数字万用表"]


async def test_pdf_images_are_captioned_stored_and_linked(tmp_path):
    captioner = FakeCaptioner("表笔接线示意图")
    container = FakeContainer(tmp_path, captioner=captioner)
    pdf = make_manual_pdf(tmp_path / "ZG-12使用手册.pdf")

    _, document = await ingest(container, pdf.name, pdf.read_bytes())

    assert document["status"] == "completed" and document["parser"] == "pymupdf" and document["image_count"] == 1
    stored = list((container.settings.data_dir / "files" / document["doc_id"] / "images").iterdir())
    assert len(stored) == 1
    url = f"/api/files/{document['doc_id']}/images/{stored[0].name}"
    contents = "\n".join(chunk["content"] for chunk in container.vector_store.chunks.values())
    assert f"![表笔接线示意图]({url})" in contents
    assert str(tmp_path) not in contents, "片段里不应残留服务器上的本地路径"
    assert captioner.calls[0]["title"] == "ZG-12使用手册" and captioner.calls[0]["mime_type"] == "image/png"


async def test_images_are_still_stored_when_captioning_fails_or_is_disabled(tmp_path):
    pdf = make_manual_pdf(tmp_path / "ZG-12使用手册.pdf")
    for captioner in (None, FakeCaptioner(error=RuntimeError("视觉模型限流"))):
        container = FakeContainer(tmp_path / str(id(captioner)), captioner=captioner)

        _, document = await ingest(container, pdf.name, pdf.read_bytes())

        assert document["status"] == "completed" and document["image_count"] == 1
        contents = "\n".join(chunk["content"] for chunk in container.vector_store.chunks.values())
        assert f"](/api/files/{document['doc_id']}/images/" in contents


async def test_markdown_cannot_pull_in_files_outside_its_own_directory(tmp_path, container):
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"\x89PNG secret")
    markdown = f"# 手册\n\n正文内容足够长。{'补充说明。' * 10}\n\n![偷看]({secret})\n\n![远程图](https://example.com/a.png)\n"

    _, document = await ingest(container, "手册.md", markdown.encode("utf-8"))

    contents = "\n".join(chunk["content"] for chunk in container.vector_store.chunks.values())
    assert document["image_count"] == 0
    assert str(secret) not in contents and "偷看" in contents
    assert "![远程图](https://example.com/a.png)" in contents
    assert not (container.settings.data_dir / "files" / document["doc_id"] / "images").exists()


async def test_reuploading_the_same_file_replaces_the_previous_version(container):
    service, first = await ingest(container, "ZG-12使用手册.md", MARKDOWN_MANUAL)
    updated = MARKDOWN_MANUAL + "\n## 保修\n\n整机保修一年，电池和表笔属于耗材不在保修范围内。保修需提供购买凭证。\n".encode("utf-8")

    record = await service.submit("ZG-12使用手册.md", updated)
    await service.wait_idle()

    documents = await container.registry.list_documents()
    assert [item["doc_id"] for item in documents] == [record["doc_id"]]
    assert {chunk["doc_id"] for chunk in container.vector_store.chunks.values()} == {record["doc_id"]}
    assert any("保修" in chunk["content"] for chunk in container.vector_store.chunks.values())
    assert not (container.settings.data_dir / "files" / first["doc_id"]).exists()


async def test_deleting_the_last_document_of_a_product_removes_the_product(container):
    service, first = await ingest(container, "使用手册.md", MARKDOWN_MANUAL)
    _, second = await ingest(container, "快速指南.md", MARKDOWN_MANUAL)

    assert await service.delete(first["doc_id"]) is True
    assert "ZG-12 数字万用表" in container.vector_store.products
    assert await service.delete(second["doc_id"]) is True

    assert container.vector_store.products == {} and container.vector_store.chunks == {}
    assert await container.registry.list_documents() == []
    assert await service.delete("no-such-doc") is False


@pytest.mark.parametrize("file_name,data,reason", [
    ("报价单.xlsx", b"data", "不支持的文件类型"),
    ("空文件.md", b"", "空文件"),
    ("", b"data", "不支持的文件类型"),
])
async def test_unacceptable_uploads_are_rejected_before_anything_is_stored(container, file_name, data, reason):
    with pytest.raises(UploadRejected, match=reason):
        await IngestService(container).submit(file_name, data)

    assert await container.registry.list_documents() == []


async def test_oversized_upload_is_rejected(tmp_path):
    container = FakeContainer(tmp_path, max_upload_mb=1)
    with pytest.raises(UploadRejected, match="超过了 1 MB"):
        await IngestService(container).submit("大文件.md", b"x" * (1024 * 1024 + 1))


async def test_failed_import_reports_the_reason_and_leaves_no_partial_data(container):
    _, document = await ingest(container, "损坏.pdf", b"this is not a pdf")

    assert document["status"] == "failed"
    assert "PDF 解析失败" in document["error"]
    assert container.vector_store.chunks == {} and container.vector_store.products == {}


async def test_unexpected_errors_do_not_leak_internal_details(container, monkeypatch):
    async def explode(rows):
        raise ConnectionError("milvus://10.0.0.8:19530 refused, token=abc123")
    monkeypatch.setattr(container.vector_store, "upsert_chunks", explode)

    _, document = await ingest(container, "手册.md", MARKDOWN_MANUAL)

    assert document["status"] == "failed"
    assert "ConnectionError" in document["error"] and "10.0.0.8" not in document["error"]


async def test_file_name_cannot_escape_the_storage_directory(container):
    service = IngestService(container)
    record = await service.submit("../../etc/手册.md", MARKDOWN_MANUAL)
    await service.wait_idle()

    assert record["file_name"] == "手册.md"
    stored = list((container.settings.data_dir / "files" / record["doc_id"] / "source").iterdir())
    assert [path.name for path in stored] == ["手册.md"]
