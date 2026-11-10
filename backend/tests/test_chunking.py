"""文档切分：按标题拆章节、超长细分、过短合并、表格与代码块的处理。"""
import pytest

from app.ingest.chunking import html_tables_to_markdown, split_markdown, split_text

MANUAL = """# ZG-12 数字万用表

## 安全须知

测量前请确认表笔绝缘层完好。""" + "不要在潮湿环境中使用仪表。" * 12 + """

## 测量直流电压

1. 将旋钮转到直流电压档。
2. 红表笔接正极，黑表笔接负极。
3. 读取屏幕上的数值。""" + "若显示 OL，说明超出量程，请换用更高的量程。" * 8 + """

## 保养

### 更换电池

拧开后盖螺丝，取出旧电池。

### 清洁

用干布擦拭外壳。
"""


def test_every_chunk_fits_the_limit_and_keeps_its_heading():
    chunks = split_markdown(MANUAL, "ZG-12 使用手册", max_chars=200, min_chars=60)

    assert all(len(chunk.content) <= 200 for chunk in chunks)
    assert [chunk.seq for chunk in chunks] == list(range(len(chunks)))
    voltage = [chunk for chunk in chunks if chunk.title.startswith("测量直流电压")]
    assert len(voltage) > 1, "超长章节应被细分"
    assert all(chunk.content.startswith("## 测量直流电压") for chunk in voltage)
    assert voltage[0].title == f"测量直流电压（1/{len(voltage)}）"
    assert all(chunk.parent_title == "ZG-12 数字万用表" for chunk in voltage)


def test_no_text_is_lost_when_splitting():
    chunks = split_markdown(MANUAL, "ZG-12 使用手册", max_chars=200, min_chars=60)
    joined = "".join(chunk.content for chunk in chunks)

    for sentence in ["测量前请确认表笔绝缘层完好", "红表笔接正极，黑表笔接负极", "拧开后盖螺丝", "用干布擦拭外壳"]:
        assert sentence in joined
    assert joined.count("若显示 OL") == 8


def test_heading_only_sections_are_not_emitted_but_remain_as_parent():
    chunks = split_markdown(MANUAL, "ZG-12 使用手册", max_chars=200, min_chars=60)

    assert not any(chunk.content.strip() == "# ZG-12 数字万用表" for chunk in chunks)
    assert not any(chunk.content.strip() == "## 保养" for chunk in chunks)
    assert {chunk.parent_title for chunk in chunks if "电池" in chunk.content} == {"保养"}


def test_short_siblings_are_merged_under_their_parent():
    chunks = split_markdown(MANUAL, "ZG-12 使用手册", max_chars=200, min_chars=60)
    care = [chunk for chunk in chunks if "更换电池" in chunk.content]

    assert len(care) == 1
    assert "### 更换电池" in care[0].content and "### 清洁" in care[0].content
    assert care[0].title == "更换电池、清洁" and care[0].parent_title == "保养"


def test_short_sections_under_different_parents_are_not_merged():
    markdown = "# 甲\n\n## 甲一\n\n短。\n\n# 乙\n\n## 乙一\n\n也短。\n"
    chunks = split_markdown(markdown, "文档", max_chars=200, min_chars=60)

    assert [chunk.parent_title for chunk in chunks] == ["甲", "乙"]


def test_merging_never_exceeds_the_limit():
    markdown = "# 总则\n\n## 一\n\n" + "短句。" * 10 + "\n\n## 二\n\n" + "这一节比较长。" * 25 + "\n"
    chunks = split_markdown(markdown, "文档", max_chars=200, min_chars=60)

    assert all(len(chunk.content) <= 200 for chunk in chunks)


def test_intro_of_a_chapter_is_merged_with_its_first_subsection():
    markdown = "# 保修\n\n本产品保修一年。\n\n## 保修范围\n\n非人为损坏均在保修范围内。\n\n## 不保修的情况\n\n" + "私自拆机。" * 30
    chunks = split_markdown(markdown, "文档", max_chars=200, min_chars=60)

    assert "本产品保修一年" in chunks[0].content and "## 保修范围" in chunks[0].content
    assert chunks[0].title == "保修、保修范围" and chunks[0].parent_title == ""


def test_document_without_headings_uses_the_file_title():
    chunks = split_markdown("第一段。\n\n第二段。", "产品简介", max_chars=200, min_chars=60)

    assert len(chunks) == 1
    assert chunks[0].title == "产品简介" and chunks[0].parent_title == ""
    assert chunks[0].content == "第一段。\n\n第二段。"


def test_hash_inside_code_fence_is_not_a_heading():
    markdown = "# 命令\n\n```bash\n# 这是注释，不是标题\necho ok\n```\n\n结束。"
    chunks = split_markdown(markdown, "文档", max_chars=200, min_chars=60)

    assert len(chunks) == 1
    assert "# 这是注释，不是标题" in chunks[0].content


def test_windows_line_endings_and_empty_input():
    assert split_markdown("", "空文档") == []
    chunks = split_markdown("# 标题\r\n\r\n正文。\r\n", "文档", max_chars=200, min_chars=60)
    assert chunks[0].content == "# 标题\n\n正文。"


def test_invalid_limits_are_rejected():
    with pytest.raises(ValueError):
        split_markdown("# a\n\nb", "文档", max_chars=100, min_chars=100)


def test_split_text_prefers_paragraph_then_sentence_boundaries():
    text = "第一段第一句。第一段第二句。\n\n第二段第一句。第二段第二句。"
    assert split_text(text, 20) == ["第一段第一句。第一段第二句。", "第二段第一句。第二段第二句。"]
    assert split_text(text, 10) == ["第一段第一句。", "第一段第二句。", "第二段第一句。", "第二段第二句。"]


def test_split_text_hard_cuts_text_without_any_boundary():
    parts = split_text("甲" * 25, 10)
    assert [len(part) for part in parts] == [10, 10, 5]


def test_long_table_is_split_by_rows_and_every_part_keeps_the_header():
    rows = "\n".join(f"| 量程{index} | ±0.{index}% | 说明文字说明文字 |" for index in range(1, 13))
    table = "| 量程 | 精度 | 备注 |\n| --- | --- | --- |\n" + rows
    parts = split_text(table, 160)

    assert len(parts) > 1
    assert all(part.startswith("| 量程 | 精度 | 备注 |\n| --- | --- | --- |") for part in parts)
    assert all(len(part) <= 160 for part in parts)
    assert sum(part.count("| 量程") - 1 for part in parts) == 12


def test_code_block_with_blank_lines_stays_together_when_it_fits():
    text = "说明。\n\n```python\na = 1\n\nb = 2\n```\n\n结束。"
    parts = split_text(text, 30)

    assert any("a = 1\n\nb = 2" in part for part in parts)


def test_html_table_is_converted_to_a_markdown_table():
    html = "前文\n<table><tr><th>档位</th><th>量程</th></tr><tr><td>直流电压</td><td>200mV<br>~1000V</td></tr></table>\n后文"
    converted = html_tables_to_markdown(html)

    assert "| 档位 | 量程 |\n| --- | --- |\n| 直流电压 | 200mV ~1000V |" in converted
    assert "<table>" not in converted and "前文" in converted and "后文" in converted
