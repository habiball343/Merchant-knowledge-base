"""PDF 解析器：内置解析器真实解析一份现做的 PDF；MinerU 适配器用一个替身命令验证调用约定。"""
import os
import stat
import sys

import pytest

from app.ingest.parsers import MinerUParser, PdfParseError, PyMuPdfParser, select_pdf_parser
from app.ingest.parsers.pymupdf_parser import clean_cell_breaks, join_pages, place_images, reflow_paragraphs
from tests.pdf_factory import make_manual_pdf


def test_builtin_parser_recovers_headings_text_and_images(tmp_path):
    pdf = make_manual_pdf(tmp_path / "ZG-12使用手册.pdf")

    parsed = PyMuPdfParser().parse(pdf, tmp_path / "work")

    assert "# ZG-12 数字万用表" in parsed.markdown
    assert "## 测量直流电压" in parsed.markdown and "## 更换电池" in parsed.markdown
    assert "读取屏幕上的数值" in parsed.markdown
    images = list((tmp_path / "work" / "images").glob("*.png"))
    assert len(images) == 1 and images[0].stat().st_size > 0
    assert str(images[0]) in parsed.markdown


def test_builtin_parser_rejects_a_pdf_without_text(tmp_path):
    import pymupdf
    path = tmp_path / "blank.pdf"
    document = pymupdf.open()
    document.new_page()
    document.save(path)

    with pytest.raises(PdfParseError, match="没有从 PDF 中提取到文字"):
        PyMuPdfParser().parse(path, tmp_path / "work")


def test_builtin_parser_reports_unreadable_files(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"this is not a pdf")

    with pytest.raises(PdfParseError):
        PyMuPdfParser().parse(path, tmp_path / "work")


def test_reflow_joins_wrapped_lines_but_leaves_structure_alone():
    markdown = "# 标题\n\n第一行没写完\n接着写完了。\n\nThe first line\ncontinues here.\n\n- 列表一\n- 列表二\n\n| a | b |\n| --- | --- |\n\n```\nline1\nline2\n```"

    result = reflow_paragraphs(markdown)

    assert "第一行没写完接着写完了。" in result
    assert "The first line continues here." in result
    assert "- 列表一\n- 列表二" in result
    assert "| a | b |\n| --- | --- |" in result
    assert "line1\nline2" in result


def test_reflow_rejoins_sentences_that_were_split_into_separate_paragraphs():
    markdown = ("机器工作时出风口温度很高，背面和上方至少留出 10 厘米的空间，不要靠墙或放在橱柜内使\n\n\n用。\n\n\n"
                "不要把机身、电源线和插头浸入水中。\n\n"
                "4. 空烧时可能有少量白烟和气味，属于正常现象，请保持厨房通\n\n风。\n\n"
                "短标题\n\n另起一段的正文。")

    result = reflow_paragraphs(markdown)

    assert "不要靠墙或放在橱柜内使用。\n\n不要把机身、电源线和插头浸入水中。" in result
    assert "4. 空烧时可能有少量白烟和气味，属于正常现象，请保持厨房通风。" in result
    assert "短标题\n\n另起一段的正文。" in result, "没有句号的短行多半是小标题，不应与下一段合并"


def test_images_are_moved_next_to_the_text_above_them_on_the_page():
    text = "## 结构说明\n\n各部分的名称见下图。\n\n炸篮可以整体抽出清洗。\n\n## 控制面板\n\n按键位置见下图。\n\n![](a.png)\n![](b.png)"
    blocks = [(100.0, "结构说明\n"), (130.0, "各部分的名称见下图。\n"), (400.0, "炸篮可以整体抽出清洗。\n"),
              (430.0, "控制面板\n"), (460.0, "按键位置见\n下图。\n")]

    result = place_images(text, [(60, 470, 400, 600), (60, 140, 400, 380)], blocks)

    assert "各部分的名称见下图。\n\n![](a.png)\n\n炸篮可以整体抽出清洗。" in result
    assert result.rstrip().endswith("按键位置见下图。\n\n![](b.png)")


def test_image_at_the_top_of_a_page_goes_first_and_unmatched_cases_are_left_alone():
    assert place_images("正文。\n\n![](a.png)", [(60, 20, 400, 200)], [(300.0, "正文。")]).startswith("![](a.png)")
    untouched = "正文。\n\n![](a.png)\n![](b.png)"
    assert place_images(untouched, [(60, 20, 400, 200)], [(300.0, "正文。")]) == untouched   # 数量对不上
    assert place_images("正文。\n\n![](a.png)", [(60, 320, 400, 500)], [(300.0, "页面上另一段找不到的文字")]) == "正文。\n\n![](a.png)"


def test_table_continued_on_the_next_page_is_joined_back():
    first = "## 参数\n\n|食材|温度|\n|---|---|\n|薯条|200℃|"
    second = "|红薯|200℃|\n|---|---|\n|牛排|200℃|\n\n## 清洁"

    assert join_pages([first, "", second]) == "## 参数\n\n|食材|温度|\n|---|---|\n|薯条|200℃|\n|红薯|200℃|\n|牛排|200℃|\n\n## 清洁"
    # 列数不同的表格、中间隔着正文的表格不合并
    assert "|---|---|---|" in join_pages([first, "|a|b|c|\n|---|---|---|\n|1|2|3|"])
    assert join_pages(["正文。", second]).count("|---|---|") == 1 and "正文。\n\n|红薯" in join_pages(["正文。", second])


def test_line_breaks_inside_table_cells_are_removed():
    row = "|机器不工作|炸篮没有推到位，或没有设置时<br>间|press<br>start|"
    assert clean_cell_breaks(row) == "|机器不工作|炸篮没有推到位，或没有设置时间|press start|"
    assert clean_cell_breaks("正文里的 <br> 不动") == "正文里的 <br> 不动"


def _fake_mineru(tmp_path, body: str):
    """做一个假的 mineru 命令：按约定的目录结构写出结果。"""
    script = tmp_path / "fake_mineru.py"
    script.write_text(body, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return f"{sys.executable} {script}"


def test_mineru_adapter_runs_the_command_and_finds_its_output(tmp_path):
    command = _fake_mineru(tmp_path, """
import sys, pathlib
args = sys.argv[1:]
pdf = pathlib.Path(args[args.index("-p") + 1])
out = pathlib.Path(args[args.index("-o") + 1]) / pdf.stem / "hybrid_auto"
(out / "images").mkdir(parents=True)
(out / "images" / "fig1.jpg").write_bytes(b"jpg")
(out / f"{pdf.stem}.md").write_text("# 手册\\n\\n![](images/fig1.jpg)\\n", encoding="utf-8")
""")
    pdf = tmp_path / "手册.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    parsed = MinerUParser(command).parse(pdf, tmp_path / "work")

    assert parsed.markdown.startswith("# 手册")
    assert (parsed.base_dir / "images" / "fig1.jpg").is_file()


def test_mineru_failure_surfaces_the_tool_output(tmp_path):
    command = _fake_mineru(tmp_path, "import sys\nprint('model weights not found', file=sys.stderr)\nsys.exit(3)\n")
    pdf = tmp_path / "手册.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    with pytest.raises(PdfParseError, match="退出码 3.*model weights not found"):
        MinerUParser(command).parse(pdf, tmp_path / "work")


def test_mineru_success_without_markdown_is_an_error(tmp_path):
    command = _fake_mineru(tmp_path, "pass\n")
    pdf = tmp_path / "手册.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    with pytest.raises(PdfParseError, match="没有找到输出的 Markdown"):
        MinerUParser(command).parse(pdf, tmp_path / "work")


def test_missing_mineru_command_is_reported(tmp_path):
    pdf = tmp_path / "手册.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    with pytest.raises(PdfParseError, match="找不到 MinerU 命令"):
        MinerUParser("definitely-not-installed-mineru").parse(pdf, tmp_path / "work")


def test_parser_selection(monkeypatch):
    assert isinstance(select_pdf_parser("pymupdf"), PyMuPdfParser)
    assert isinstance(select_pdf_parser("mineru"), MinerUParser)
    monkeypatch.setenv("PATH", os.devnull)
    assert isinstance(select_pdf_parser("auto", "mineru"), PyMuPdfParser)
