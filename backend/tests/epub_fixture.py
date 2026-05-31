"""Minimal, valid EPUB built with stdlib zipfile — no extra dependency.

Nested NCX navPoints (chapter ▸ section) so `fitz.open(epub).get_toc()`
emits a 2-level layout that survives `builder._parse_toc_layout` (the
deterministic, non-LLM skeleton path). 4 sections → 4 reflowed pages,
one section per page, deterministic across opens (no `doc.layout()`).
"""

from __future__ import annotations

import zipfile
from pathlib import Path

_CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf"
   media-type="application/oebps-package+xml"/></rootfiles>
</container>"""

_OPF = """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">urn:uuid:fixture-1</dc:identifier>
    <dc:title>Fixture Book</dc:title><dc:language>zh</dc:language>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="s11" href="s11.xhtml" media-type="application/xhtml+xml"/>
    <item id="s12" href="s12.xhtml" media-type="application/xhtml+xml"/>
    <item id="s21" href="s21.xhtml" media-type="application/xhtml+xml"/>
    <item id="s22" href="s22.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine toc="ncx">
    <itemref idref="s11"/><itemref idref="s12"/>
    <itemref idref="s21"/><itemref idref="s22"/>
  </spine>
</package>"""

_NCX = """<?xml version="1.0"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head><meta name="dtb:uid" content="urn:uuid:fixture-1"/></head>
  <docTitle><text>Fixture Book</text></docTitle>
  <navMap>
    <navPoint id="c1" playOrder="1"><navLabel><text>第一章 力学</text></navLabel>
      <content src="s11.xhtml"/>
      <navPoint id="c1s1" playOrder="2"><navLabel><text>1.1 牛顿定律</text></navLabel>
        <content src="s11.xhtml"/></navPoint>
      <navPoint id="c1s2" playOrder="3"><navLabel><text>1.2 惯性参考系</text></navLabel>
        <content src="s12.xhtml"/></navPoint>
    </navPoint>
    <navPoint id="c2" playOrder="4"><navLabel><text>第二章 测量</text></navLabel>
      <content src="s21.xhtml"/>
      <navPoint id="c2s1" playOrder="5"><navLabel><text>2.1 误差分析</text></navLabel>
        <content src="s21.xhtml"/></navPoint>
      <navPoint id="c2s2" playOrder="6"><navLabel><text>2.2 有效数字</text></navLabel>
        <content src="s22.xhtml"/></navPoint>
    </navPoint>
  </navMap>
</ncx>"""

_NAV = """<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<body><nav epub:type="toc"><ol>
  <li><a href="s11.xhtml">第一章 力学</a><ol>
    <li><a href="s11.xhtml">1.1 牛顿定律</a></li>
    <li><a href="s12.xhtml">1.2 惯性参考系</a></li></ol></li>
  <li><a href="s21.xhtml">第二章 测量</a><ol>
    <li><a href="s21.xhtml">2.1 误差分析</a></li>
    <li><a href="s22.xhtml">2.2 有效数字</a></li></ol></li>
</ol></nav></body></html>"""

# Each section's body carries a unique marker so tests can assert that
# extract_kp_text returns the right page (not a raw-file char slice).
_SECTIONS = {
    "s11.xhtml": ("1.1 牛顿定律", "牛顿第一定律：物体不受外力时保持静止或匀速直线运动。MARK_S11"),
    "s12.xhtml": ("1.2 惯性参考系", "惯性参考系是牛顿定律成立的参考系。MARK_S12"),
    "s21.xhtml": ("2.1 误差分析", "测量误差分为系统误差与随机误差。MARK_S21"),
    "s22.xhtml": ("2.2 有效数字", "有效数字反映测量的精度与可信位数。MARK_S22"),
}


def _xhtml(title: str, body: str) -> str:
    return (
        '<?xml version="1.0"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
        f"<h1>{title}</h1><p>{body}</p></body></html>"
    )


def make_epub(path: str | Path) -> None:
    """Write a minimal valid EPUB to `path`."""
    with zipfile.ZipFile(path, "w") as z:
        # mimetype must be the first entry and stored (uncompressed).
        z.writestr(
            zipfile.ZipInfo("mimetype"),
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        z.writestr("META-INF/container.xml", _CONTAINER)
        z.writestr("OEBPS/content.opf", _OPF)
        z.writestr("OEBPS/toc.ncx", _NCX)
        z.writestr("OEBPS/nav.xhtml", _NAV)
        for name, (title, body) in _SECTIONS.items():
            z.writestr(f"OEBPS/{name}", _xhtml(title, body))


def epub_bytes() -> bytes:
    """The same minimal EPUB as an in-memory bytes blob (for UploadFile)."""
    import io

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(
            zipfile.ZipInfo("mimetype"),
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        z.writestr("META-INF/container.xml", _CONTAINER)
        z.writestr("OEBPS/content.opf", _OPF)
        z.writestr("OEBPS/toc.ncx", _NCX)
        z.writestr("OEBPS/nav.xhtml", _NAV)
        for name, (title, body) in _SECTIONS.items():
            z.writestr(f"OEBPS/{name}", _xhtml(title, body))
    return buf.getvalue()
