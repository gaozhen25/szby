"""Render the bundled host-client guides as HTML so the browser can show them."""

from __future__ import annotations

import html
from io import BytesIO
import posixpath
import zipfile
from importlib import resources
from xml.etree import ElementTree as ET

HOST_DOC_NAMES = {
    "wechat": "小主机启动个人微信.docx",
    "wecom": "小主机启动企业微信.docx",
}
HOST_DOC_TITLES = {
    "wechat": "微信接入",
    "wecom": "企业微信接入",
}
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_EMU_PER_INCH = 914400
_CSS_PX_PER_INCH = 96


def host_doc_bytes(platform: str) -> bytes:
    name = HOST_DOC_NAMES[platform]
    return resources.files("message_adapter.web").joinpath(name).read_bytes()


def host_doc_media(platform: str, name: str) -> bytes | None:
    if "/" in name or name.startswith("."):
        return None
    with zipfile.ZipFile(BytesIO(host_doc_bytes(platform))) as archive:
        target = f"word/media/{name}"
        if target not in archive.namelist():
            return None
        return archive.read(target)


def render_host_doc(platform: str) -> str:
    title = HOST_DOC_TITLES[platform]
    body = _document_html(host_doc_bytes(platform), f"/docs/{platform}/media/")
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    body {{
      margin: 0;
      background: #d6d9de;
      color: #000;
      font: 10.5pt/1.5 "Songti SC", "SimSun", "PingFang SC", serif;
    }}
    main {{
      box-sizing: border-box;
      width: 8.27in;
      max-width: calc(100% - 24px);
      margin: 16px auto 32px;
      padding: 1in 1.25in;
      background: #fff;
    }}
    p {{
      margin: 0 0 8px;
    }}
    img {{
      display: block;
      max-width: 100%;
      height: auto;
      margin: 6px 0 10px;
    }}
  </style>
</head>
<body>
  <main>
    {body}
  </main>
</body>
</html>
"""


def _document_html(blob: bytes, media_prefix: str) -> str:
    with zipfile.ZipFile(BytesIO(blob)) as archive:
        document = ET.fromstring(archive.read("word/document.xml"))
        relationships = _image_relationships(archive.read("word/_rels/document.xml.rels"))
    parts: list[str] = []
    body = document.find(f"{_W}body")
    if body is None:
        return ""
    for child in body:
        if child.tag != f"{_W}p":
            continue
        parts.extend(_paragraph_html(child, relationships, media_prefix))
    return "\n".join(parts)


def _image_relationships(blob: bytes) -> dict[str, str]:
    root = ET.fromstring(blob)
    images: dict[str, str] = {}
    for item in root:
        if item.tag != f"{_REL_NS}Relationship":
            continue
        if not str(item.attrib.get("Type") or "").endswith("/image"):
            continue
        target = str(item.attrib.get("Target") or "")
        relation_id = str(item.attrib.get("Id") or "")
        if relation_id and target:
            images[relation_id] = posixpath.basename(target.replace("\\", "/"))
    return images


def _emu_px(value: str) -> int:
    return max(1, round(int(value) / _EMU_PER_INCH * _CSS_PX_PER_INCH))


def _image_html(drawing: ET.Element, images: dict[str, str], media_prefix: str) -> str:
    blip = next(drawing.iter(f"{_A}blip"), None)
    if blip is None:
        return ""
    name = images.get(str(blip.attrib.get(f"{_R}embed") or ""))
    if not name:
        return ""
    extent = drawing.find(f"{_WP}extent")
    width = ""
    if extent is not None and extent.attrib.get("cx"):
        width = f' width="{_emu_px(extent.attrib["cx"])}"'
    src = html.escape(media_prefix + name, quote=True)
    return f'<img src="{src}"{width} alt="">'


def _paragraph_html(paragraph: ET.Element, images: dict[str, str], media_prefix: str) -> list[str]:
    parts: list[str] = []
    text: list[str] = []

    def flush() -> None:
        value = "".join(text).strip()
        text.clear()
        if value:
            parts.append(f"<p>{html.escape(value).replace(chr(10), '<br>')}</p>")

    for node in paragraph.iter():
        if node.tag == f"{_W}t" and node.text:
            text.append(node.text)
        elif node.tag == f"{_W}tab":
            text.append(" ")
        elif node.tag == f"{_W}br":
            text.append("\n")
        elif node.tag in {f"{_WP}inline", f"{_WP}anchor"}:
            flush()
            markup = _image_html(node, images, media_prefix)
            if markup:
                parts.append(markup)
    flush()
    return parts
