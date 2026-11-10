"""在测试里现做一份带标题、正文和插图的 PDF。"""
from pathlib import Path

import pymupdf


def make_manual_pdf(path: Path, with_image: bool = True) -> Path:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 90), "ZG-12 数字万用表", fontname="china-s", fontsize=24)
    page.insert_text((72, 140), "测量直流电压", fontname="china-s", fontsize=17)
    page.insert_textbox(
        pymupdf.Rect(72, 155, 520, 230),
        "将旋钮转到直流电压档，红表笔接正极，黑表笔接负极，读取屏幕上的数值。若显示 OL，说明超出量程。",
        fontname="china-s", fontsize=11)
    if with_image:
        pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 320, 200), False)
        pixmap.clear_with(235)
        for x in range(40, 280):
            for y in (60, 61, 140, 141):
                pixmap.set_pixel(x, y, (30, 90, 160))
        page.insert_image(pymupdf.Rect(72, 250, 392, 450), pixmap=pixmap)
    page.insert_text((72, 500), "更换电池", fontname="china-s", fontsize=17)
    page.insert_textbox(
        pymupdf.Rect(72, 515, 520, 580),
        "拧开后盖的两颗螺丝，取出旧的 9V 电池，按正负极方向装入新电池后装回后盖。",
        fontname="china-s", fontsize=11)
    document.save(path)
    document.close()
    return path
