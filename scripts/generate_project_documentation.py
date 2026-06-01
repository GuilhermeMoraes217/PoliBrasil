from __future__ import annotations

import re
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "Poli-English-Duel-Documentacao-Oficial.md"
OUTPUT = ROOT / "docs" / "Poli-English-Duel-Documentacao-Oficial.docx"
NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def run(text: str, bold: bool = False, italic: bool = False, color: str | None = None, size: int | None = None) -> str:
    props = []
    if bold:
        props.append("<w:b/>")
    if italic:
        props.append("<w:i/>")
    if color:
        props.append(f'<w:color w:val="{color}"/>')
    if size:
        props.append(f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>')
    prop_xml = f"<w:rPr>{''.join(props)}</w:rPr>" if props else ""
    return f'<w:r>{prop_xml}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def styled_runs(text: str) -> str:
    parts = re.split(r"(`[^`]+`|\*\*[^*]+\*\*)", text)
    rendered = []
    for part in parts:
        if part.startswith("`") and part.endswith("`"):
            rendered.append(run(part[1:-1], color="1E6B4F"))
        elif part.startswith("**") and part.endswith("**"):
            rendered.append(run(part[2:-2], bold=True))
        else:
            rendered.append(run(part))
    return "".join(rendered)


def paragraph(text: str = "", style: str | None = None, before: int = 0, after: int = 100, indent: int | None = None) -> str:
    style_xml = f'<w:pStyle w:val="{style}"/>' if style else ""
    indent_xml = f'<w:ind w:left="{indent}"/>' if indent is not None else ""
    props = f"<w:pPr>{style_xml}<w:spacing w:before=\"{before}\" w:after=\"{after}\"/>{indent_xml}</w:pPr>"
    return f"<w:p>{props}{styled_runs(text)}</w:p>"


def field_paragraph(instruction: str, label: str) -> str:
    return (
        "<w:p><w:pPr><w:spacing w:after=\"120\"/></w:pPr>"
        "<w:r><w:fldChar w:fldCharType=\"begin\"/></w:r>"
        f"<w:r><w:instrText xml:space=\"preserve\"> {escape(instruction)} </w:instrText></w:r>"
        "<w:r><w:fldChar w:fldCharType=\"separate\"/></w:r>"
        f"{run(label, italic=True, color='667085')}"
        "<w:r><w:fldChar w:fldCharType=\"end\"/></w:r></w:p>"
    )


def table(rows: list[list[str]]) -> str:
    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]
    grid = "".join('<w:gridCol w:w="2200"/>' for _ in range(width))
    body = []
    for row_index, row in enumerate(normalized):
        cells = []
        for cell in row:
            fill = '<w:shd w:fill="DFF5E7"/>' if row_index == 0 else ""
            cell_text = styled_runs(cell)
            cells.append(
                "<w:tc><w:tcPr>"
                f"{fill}<w:tcMar><w:top w:w=\"80\" w:type=\"dxa\"/><w:left w:w=\"100\" w:type=\"dxa\"/>"
                "<w:bottom w:w=\"80\" w:type=\"dxa\"/><w:right w:w=\"100\" w:type=\"dxa\"/></w:tcMar></w:tcPr>"
                f"<w:p><w:pPr><w:spacing w:after=\"0\"/></w:pPr>{cell_text}</w:p></w:tc>"
            )
        body.append(f"<w:tr>{''.join(cells)}</w:tr>")
    return (
        '<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/>'
        '<w:tblBorders><w:top w:val="single" w:sz="4" w:color="B7D8C3"/>'
        '<w:left w:val="single" w:sz="4" w:color="B7D8C3"/>'
        '<w:bottom w:val="single" w:sz="4" w:color="B7D8C3"/>'
        '<w:right w:val="single" w:sz="4" w:color="B7D8C3"/>'
        '<w:insideH w:val="single" w:sz="4" w:color="B7D8C3"/>'
        '<w:insideV w:val="single" w:sz="4" w:color="B7D8C3"/></w:tblBorders></w:tblPr>'
        f"<w:tblGrid>{grid}</w:tblGrid>{''.join(body)}</w:tbl>"
        "<w:p><w:pPr><w:spacing w:after=\"80\"/></w:pPr></w:p>"
    )


def render_markdown(markdown: str) -> str:
    lines = markdown.splitlines()
    body = []
    in_code = False
    code_lines: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("```"):
            if in_code:
                text = "\n".join(code_lines)
                body.append(
                    '<w:p><w:pPr><w:shd w:fill="F1F5F3"/><w:spacing w:before="60" w:after="100"/>'
                    '<w:ind w:left="180" w:right="180"/></w:pPr>'
                    f'{run(text, color="1D4736", size=18)}</w:p>'
                )
                code_lines = []
            in_code = not in_code
            index += 1
            continue
        if in_code:
            code_lines.append(line)
            index += 1
            continue
        if line == "[PAGEBREAK]":
            body.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
            index += 1
            continue
        if line.startswith("|") and index + 1 < len(lines) and re.match(r"^\|\s*:?-+", lines[index + 1]):
            rows = []
            index += 2
            header = [cell.strip() for cell in line.strip("|").split("|")]
            rows.append(header)
            while index < len(lines) and lines[index].startswith("|"):
                rows.append([cell.strip() for cell in lines[index].strip("|").split("|")])
                index += 1
            body.append(table(rows))
            continue
        heading = re.match(r"^(#{1,4})\s+(.+)$", line)
        if heading:
            level = len(heading.group(1))
            body.append(paragraph(heading.group(2), style=f"Heading{level}", before=180, after=100))
        elif line.startswith("- "):
            body.append(paragraph(f"• {line[2:]}", indent=360, after=40))
        elif re.match(r"^\d+\.\s", line):
            body.append(paragraph(line, indent=360, after=40))
        elif line == "---":
            body.append('<w:p><w:pPr><w:pBdr><w:bottom w:val="single" w:sz="4" w:space="1" w:color="76B88A"/></w:pBdr></w:pPr></w:p>')
        elif line.strip():
            body.append(paragraph(line, after=90))
        else:
            body.append("<w:p><w:pPr><w:spacing w:after=\"30\"/></w:pPr></w:p>")
        index += 1
    return "".join(body)


def document_xml(body: str) -> str:
    section = (
        "<w:sectPr>"
        '<w:headerReference w:type="default" r:id="rId2"/>'
        '<w:footerReference w:type="default" r:id="rId3"/>'
        '<w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1000" w:right="1100" w:bottom="1000" w:left="1100" w:header="520" w:footer="520"/>'
        "</w:sectPr>"
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{NS}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<w:body>{body}{section}</w:body></w:document>"
    )


def styles_xml() -> str:
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{NS}">
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal">
    <w:name w:val="Normal"/><w:rPr><w:rFonts w:ascii="Aptos" w:hAnsi="Aptos"/><w:sz w:val="21"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/>
    <w:pPr><w:keepNext/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:color w:val="145A3A"/><w:sz w:val="32"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/>
    <w:pPr><w:keepNext/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:color w:val="1E6B4F"/><w:sz w:val="27"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/>
    <w:pPr><w:keepNext/><w:outlineLvl w:val="2"/></w:pPr><w:rPr><w:b/><w:color w:val="3B7A57"/><w:sz w:val="23"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading4"><w:name w:val="heading 4"/><w:basedOn w:val="Normal"/>
    <w:pPr><w:keepNext/><w:outlineLvl w:val="3"/></w:pPr><w:rPr><w:b/><w:color w:val="3B7A57"/><w:sz w:val="21"/></w:rPr></w:style>
</w:styles>'''


def header_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:hdr xmlns:w="{NS}"><w:p><w:pPr><w:pBdr><w:bottom w:val="single" w:sz="4" w:space="1" w:color="76B88A"/></w:pBdr></w:pPr>'
        f'{run("POLI ENGLISH DUEL  |  DOCUMENTAÇÃO OFICIAL", bold=True, color="145A3A", size=17)}</w:p></w:hdr>'
    )


def footer_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:ftr xmlns:w="{NS}"><w:p><w:pPr><w:jc w:val="center"/></w:pPr>'
        f'{run("Poli English Duel  •  Página ", color="667085", size=17)}'
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText> PAGE </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p></w:ftr>'
    )


def build_docx() -> None:
    markdown = SOURCE.read_text(encoding="utf-8")
    title_end = markdown.index("[PAGEBREAK]")
    cover_source = markdown[:title_end].splitlines()
    content_source = markdown[title_end + len("[PAGEBREAK]"):].lstrip()
    cover = [
        "<w:p><w:pPr><w:spacing w:before=\"1900\" w:after=\"180\"/><w:jc w:val=\"center\"/></w:pPr>"
        f'{run("POLI", bold=True, color="145A3A", size=68)}</w:p>',
        "<w:p><w:pPr><w:spacing w:after=\"130\"/><w:jc w:val=\"center\"/></w:pPr>"
        f'{run("ENGLISH DUEL", bold=True, color="1E6B4F", size=38)}</w:p>',
        "<w:p><w:pPr><w:spacing w:after=\"380\"/><w:jc w:val=\"center\"/></w:pPr>"
        f'{run("DOCUMENTAÇÃO OFICIAL DO PRODUTO E DA ARQUITETURA", bold=True, color="4E6B5D", size=22)}</w:p>',
    ]
    for line in cover_source[4:]:
        if line.strip():
            cover.append("<w:p><w:pPr><w:spacing w:after=\"70\"/><w:jc w:val=\"center\"/></w:pPr>" + styled_runs(line) + "</w:p>")
    cover.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
    cover.append(paragraph("Sumário", style="Heading1", before=100, after=160))
    cover.append(field_paragraph('TOC \\o "1-3" \\h \\z \\u', "Atualize este campo no Word para gerar o sumário."))
    cover.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
    xml = document_xml("".join(cover) + render_markdown(content_source))

    content_types = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>
  <Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>
  <Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>
</Types>'''
    package_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>'''
    document_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>
</Relationships>'''
    settings = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:settings xmlns:w="{NS}"><w:updateFields w:val="true"/></w:settings>'''
    with ZipFile(OUTPUT, "w", ZIP_DEFLATED) as document:
        document.writestr("[Content_Types].xml", content_types)
        document.writestr("_rels/.rels", package_rels)
        document.writestr("word/document.xml", xml)
        document.writestr("word/styles.xml", styles_xml())
        document.writestr("word/settings.xml", settings)
        document.writestr("word/header1.xml", header_xml())
        document.writestr("word/footer1.xml", footer_xml())
        document.writestr("word/_rels/document.xml.rels", document_rels)
    print(f"Documento gerado: {OUTPUT}")


if __name__ == "__main__":
    build_docx()
