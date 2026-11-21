"""Parsowanie typowych plików od instytucji: PDF, XML, CSV/XLSX, TXT, obrazy (OCR)."""
from io import BytesIO, StringIO
from pathlib import Path

import pandas as pd


def parse_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(data))
    text = "\n\n".join((p.extract_text() or "") for p in reader.pages)
    if len(text.strip()) < 20:  # pewnie skan -> spróbuj OCR
        try:
            return ocr_pdf(data)
        except Exception as e:
            return f"[PDF bez warstwy tekstowej, OCR niedostępny: {e}]"
    return text


def ocr_pdf(data: bytes) -> str:
    import pytesseract
    from pdf2image import convert_from_bytes

    return "\n\n".join(pytesseract.image_to_string(img, lang="pol") for img in convert_from_bytes(data))


def ocr_image(data: bytes) -> str:
    import pytesseract
    from PIL import Image

    return pytesseract.image_to_string(Image.open(BytesIO(data)), lang="pol")


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1]


def xml_to_dict(elem):
    """XML -> dict bez namespace'ów; powtarzające się tagi -> lista."""
    children = list(elem)
    if not children:
        return (elem.text or "").strip()
    out = {}
    for ch in children:
        key, val = _strip_ns(ch.tag), xml_to_dict(ch)
        if key in out:
            out[key] = out[key] if isinstance(out[key], list) else [out[key]]
            out[key].append(val)
        else:
            out[key] = val
    return out


def parse_xml(data: bytes) -> dict:
    from lxml import etree

    root = etree.fromstring(data, parser=etree.XMLParser(recover=True, huge_tree=True))
    return {_strip_ns(root.tag): xml_to_dict(root)}


def parse_table(data: bytes, filename: str) -> pd.DataFrame:
    if filename.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(BytesIO(data))
    text = data.decode("utf-8-sig", errors="replace")
    sep = ";" if text.count(";") > text.count(",") else ","  # polskie CSV często mają średnik
    return pd.read_csv(StringIO(text), sep=sep)


def parse_file(data: bytes, filename: str):
    """Zwraca (typ, treść). treść: str | dict | DataFrame."""
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return "text", parse_pdf(data)
    if ext == ".xml":
        return "xml", parse_xml(data)
    if ext in (".csv", ".xlsx", ".xls"):
        return "table", parse_table(data, filename)
    if ext in (".png", ".jpg", ".jpeg", ".tif", ".tiff"):
        return "text", ocr_image(data)
    return "text", data.decode("utf-8", errors="replace")


def to_llm_text(kind: str, content, limit: int = 15000) -> str:
    """Zamiana wyniku parsowania na tekst do promptu (z obcięciem)."""
    import json

    if kind == "table":
        text = content.head(200).to_csv(index=False)
    elif kind == "xml":
        text = json.dumps(content, ensure_ascii=False, indent=1)
    else:
        text = str(content)
    return text[:limit]
