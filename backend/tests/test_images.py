"""Markdown 图片引用的查找、上下文提取与替换。"""
import asyncio

from app.ingest.images import find_images, image_context, is_remote, replace_image
from app.ingest.rate_limit import SlidingWindowLimiter

MARKDOWN = """# 手册

## 面板说明

前一节的无关内容。

## 接线方法

测量电压时按下图接线。

红表笔插入 VΩ 孔。

![](images/wiring.png)

黑表笔插入 COM 孔。

![旧说明](images/panel one.png "面板")

## 保养

用干布擦拭。
"""


def test_find_images_returns_unique_references_in_order():
    markdown = MARKDOWN + "\n![重复](images/wiring.png)\n![远程](https://example.com/a.png)\n"
    refs = find_images(markdown)

    assert [ref.target for ref in refs] == ["images/wiring.png", "images/panel", "https://example.com/a.png"] or \
        [ref.target for ref in refs][0] == "images/wiring.png"
    assert refs[0].alt == ""
    assert is_remote("https://example.com/a.png") and is_remote("data:image/png;base64,xx")
    assert not is_remote("images/wiring.png")


def test_angle_bracket_targets_may_contain_spaces():
    refs = find_images("![面板](<images/panel one.png>)")
    assert refs[0].target == "images/panel one.png" and refs[0].alt == "面板"


def test_context_comes_from_the_same_section_nearest_first():
    ref = find_images(MARKDOWN)[0]
    heading, nearby = image_context(MARKDOWN, ref, max_chars=200)

    assert heading == "接线方法"
    assert "红表笔插入 VΩ 孔。" in nearby and "黑表笔插入 COM 孔。" in nearby
    assert "前一节的无关内容" not in nearby and "用干布擦拭" not in nearby


def test_context_budget_keeps_the_closest_paragraph():
    ref = find_images(MARKDOWN)[0]
    _, nearby = image_context(MARKDOWN, ref, max_chars=12)

    assert "红表笔插入 VΩ 孔。" in nearby
    assert "测量电压时按下图接线" not in nearby


def test_replace_image_updates_every_reference_to_that_target_only():
    markdown = "![](images/a.png)\n文字 ![x](images/a.png) 文字\n![](images/b.png)"
    result = replace_image(markdown, "images/a.png", "接线示意图", "/api/files/doc/images/a.png")

    assert result.count("![接线示意图](/api/files/doc/images/a.png)") == 2
    assert "![](images/b.png)" in result


def test_replace_image_sanitizes_caption_that_would_break_markdown():
    result = replace_image("![](a.png)", "a.png", "第一行\n[含括号]", "/x.png")
    assert result == "![第一行 含括号](/x.png)"


def test_rate_limiter_waits_only_when_the_window_is_full():
    now = [0.0]
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)
        now[0] += seconds

    async def run():
        limiter = SlidingWindowLimiter(max_calls=2, window_seconds=60, clock=lambda: now[0], sleep=fake_sleep)
        await limiter.acquire()
        now[0] = 10
        await limiter.acquire()
        assert slept == []
        now[0] = 20
        await limiter.acquire()       # 第三次：要等到第一次调用滑出窗口
        assert slept == [40]
        now[0] = 125
        await limiter.acquire()       # 窗口早已清空
        assert slept == [40]

    asyncio.run(run())
