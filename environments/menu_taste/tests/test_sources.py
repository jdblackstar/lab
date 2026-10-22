import io
import zipfile
from email.message import EmailMessage

import pytest
from menu_taste.ingest.sources import MAX_IMAGE_EDGE, load_bytes, sniff
from PIL import Image

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _docx(body_xml: str, media: dict[str, bytes] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr(
            "word/document.xml",
            f"<w:document {W}><w:body>{body_xml}</w:body></w:document>",
        )
        for name, blob in (media or {}).items():
            zf.writestr(f"word/media/{name}", blob)
    return buf.getvalue()


def _p(text: str) -> str:
    return f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"


def _png(size=(40, 20)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, format="PNG")
    return buf.getvalue()


def test_type_comes_from_content_not_extension():
    assert sniff(b"%PDF-1.7 ...", "menu.jpg") == "application/pdf"
    assert sniff(_png(), "menu.pdf") == "image/png"
    assert sniff(_docx(_p("x")), "menu.zip").endswith("wordprocessingml.document")


def test_docx_keeps_paragraph_and_table_order():
    body = (
        _p("Passed Hors d'Oeuvres")
        + _p("Gougères")
        + "<w:tbl><w:tr><w:tc>"
        + _p("Main")
        + "</w:tc><w:tc>"
        + _p("Halibut, morels")
        + "</w:tc></w:tr></w:tbl>"
        + _p("Dessert")
    )
    (doc,) = load_bytes(_docx(body), "menu.docx")
    assert doc.error is None
    assert doc.parts[0].data.splitlines() == [
        "Passed Hors d'Oeuvres",
        "Gougères",
        "Main | Halibut, morels",
        "Dessert",
    ]


def test_docx_that_is_just_a_pasted_picture_sends_the_picture():
    (doc,) = load_bytes(_docx(_p("Menu"), {"image1.png": _png()}), "menu.docx")
    assert [p.kind for p in doc.parts] == ["text", "image"]


def test_phone_photo_rotation_is_applied():
    img = Image.new("RGB", (60, 30), "white")
    exif = img.getexif()
    exif[0x0112] = 6  # stored sideways; display rotated 90°
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    (doc,) = load_bytes(buf.getvalue(), "IMG_0001.JPG")
    out = Image.open(io.BytesIO(doc.parts[0].data))
    assert out.size == (30, 60)


def test_large_images_are_downscaled_and_tiff_pages_split():
    big = io.BytesIO()
    pages = [Image.new("RGB", (MAX_IMAGE_EDGE * 2, 100), c) for c in ("white", "gray")]
    pages[0].save(big, format="TIFF", save_all=True, append_images=pages[1:])
    (doc,) = load_bytes(big.getvalue(), "scan.tif")
    assert len(doc.parts) == 2
    assert all(
        max(Image.open(io.BytesIO(p.data)).size) <= MAX_IMAGE_EDGE for p in doc.parts
    )


def test_spreadsheet_rows_become_tab_separated_text():
    from openpyxl import Workbook

    wb = Workbook()
    wb.active.title = "Dinner"
    wb.active.append(["Course", "Dish", None])
    wb.active.append(["Main", "Short rib", None])
    buf = io.BytesIO()
    wb.save(buf)
    (doc,) = load_bytes(buf.getvalue(), "beo.xlsx")
    assert doc.parts[0].data == "[sheet Dinner]\nCourse\tDish\nMain\tShort rib"


def test_html_drops_scripts_and_keeps_blocks():
    html = "<html><script>var x=1</script><h2>Dessert</h2><p>Plum tart</p></html>"
    (doc,) = load_bytes(html.encode(), "menu.html")
    assert doc.parts[0].data == "Dessert\nPlum tart"


def test_email_body_and_nested_zip_attachment_are_all_loaded():
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("menus/fall.txt", "Fall dinner: squash soup")
        zf.writestr("__MACOSX/menus/._fall.txt", "junk")
    msg = EmailMessage()
    msg["From"] = "chef@example.com"
    msg["Subject"] = "menus"
    msg.set_content("Here are the menus.")
    msg.add_attachment(_png(), maintype="image", subtype="png", filename="spring.png")
    msg.add_attachment(
        archive.getvalue(), maintype="application", subtype="zip", filename="more.zip"
    )
    docs = load_bytes(msg.as_bytes(), "thread.eml")
    assert [(d.path, [p.kind for p in d.parts]) for d in docs] == [
        ("thread.eml", ["text"]),
        ("thread.eml!spring.png", ["image"]),
        ("thread.eml!more.zip!menus/fall.txt", ["text"]),
    ]


def test_text_starting_with_bracket_is_not_mistaken_for_json():
    (doc,) = load_bytes(b"[Passed]\nGougeres", "menu.txt")
    assert doc.menus_json is None and doc.parts[0].data.startswith("[Passed]")


def test_unreadable_files_report_an_error_instead_of_raising():
    (doc,) = load_bytes(b"\xd0\xcf\x11\xe0" + b"\0" * 64, "old.msg")
    assert doc.error and ".eml" in doc.error


@pytest.mark.parametrize(
    "limit",
    ["MAX_ARCHIVE_MEMBER_BYTES", "MAX_ARCHIVE_TOTAL_BYTES", "MAX_ARCHIVE_DEPTH"],
)
def test_archives_that_expand_past_a_limit_are_skipped_not_read(monkeypatch, limit):
    from menu_taste.ingest import sources

    monkeypatch.setattr(
        sources, limit, 1 if limit == "MAX_ARCHIVE_DEPTH" else 1_000_000, raising=False
    )
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("bomb.txt", b"0" * 2_000_000)  # about 2 KB compressed
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("a-menu.txt", "Halibut, peas")
        zf.writestr("inner.zip", inner.getvalue())
    assert len(buf.getvalue()) < 10_000

    docs = load_bytes(buf.getvalue(), "menus.zip")
    assert docs[0].path == "menus.zip!a-menu.txt" and docs[0].error is None
    assert all(not p.data or len(p.data) < 1_000_000 for d in docs for p in d.parts)
    assert any(d.error for d in docs[1:])


def test_a_corrupt_zip_member_does_not_discard_the_readable_ones():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("a-menu.txt", "Halibut, peas")
        zf.writestr("b-menu.txt", "Duck, cherries")
    data = buf.getvalue().replace(b"Duck, cherries", b"Duck, cherriez")  # bad CRC

    docs = load_bytes(data, "menus.zip")
    assert [d.path for d in docs] == ["menus.zip!a-menu.txt", "menus.zip!b-menu.txt"]
    assert docs[0].error is None and docs[0].parts[0].data == "Halibut, peas"
    assert "CRC" in docs[1].error
