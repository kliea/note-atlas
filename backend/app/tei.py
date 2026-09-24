"""Parse GROBID TEI XML into a Paper's metadata, body sections, and References."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

_NS = {"t": "http://www.tei-c.org/ns/1.0"}
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
# Back matter that is not part of the argument a Paper makes.
_SKIP_SECTIONS = re.compile(
    r"acknowledg|reference|bibliograph|appendix|funding|author contrib|conflict",
    re.IGNORECASE,
)
_MAX_CONTEXTS = 3
_MAX_CONTEXT_CHARS = 300


@dataclass
class ParsedReference:
    key: str
    title: str
    authors: list[str]
    year: int | None
    venue: str | None
    doi: str | None
    arxiv_id: str | None
    raw: str
    mention_count: int = 0
    contexts: list[dict[str, str]] = field(default_factory=list)


@dataclass
class ParsedSection:
    head: str
    text: str


@dataclass
class ParsedPaper:
    title: str
    authors: list[str]
    year: int | None
    doi: str | None
    abstract: str
    sections: list[ParsedSection]
    references: list[ParsedReference]


def _text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return re.sub(r"\s+", " ", "".join(element.itertext())).strip()


def _person_name(pers: ET.Element) -> str:
    parts = [_text(part) for part in pers if part.tag.endswith(("forename", "surname"))]
    return " ".join(part for part in parts if part)


def _year(element: ET.Element | None) -> int | None:
    if element is None:
        return None
    match = re.match(r"(\d{4})", element.get("when") or _text(element))
    return int(match.group(1)) if match else None


def _idno(parent: ET.Element, kind: str) -> str | None:
    value = _text(parent.find(f".//t:idno[@type='{kind}']", _NS))
    return value or None


def _parse_reference(bibl: ET.Element) -> ParsedReference:
    analytic = bibl.find("t:analytic", _NS)
    monogr = bibl.find("t:monogr", _NS)
    title = _text(analytic.find("t:title", _NS)) if analytic is not None else ""
    venue = _text(monogr.find("t:title", _NS)) if monogr is not None else ""
    if not title:
        # Books and reports carry their title on the monograph only.
        title, venue = venue, ""
    authors = [_person_name(p) for p in bibl.findall(".//t:author/t:persName", _NS)]
    return ParsedReference(
        key=bibl.get(_XML_ID) or "",
        title=title,
        authors=[a for a in authors if a],
        year=_year(bibl.find(".//t:imprint/t:date", _NS)),
        venue=venue or None,
        doi=_idno(bibl, "DOI"),
        arxiv_id=_idno(bibl, "arXiv"),
        raw=_text(bibl.find("t:note[@type='raw_reference']", _NS)),
    )


def parse_tei(tei: str) -> ParsedPaper:
    root = ET.fromstring(tei)
    header = root.find(".//t:teiHeader", _NS)
    source = header.find(".//t:sourceDesc", _NS) if header is not None else None
    title = _text(header.find(".//t:titleStmt/t:title", _NS)) if header is not None else ""
    authors = (
        [_person_name(p) for p in source.findall(".//t:author/t:persName", _NS)]
        if source is not None
        else []
    )

    references = [
        _parse_reference(bibl)
        for bibl in root.findall(".//t:back//t:listBibl/t:biblStruct", _NS)
    ]
    by_key = {ref.key: ref for ref in references if ref.key}

    sections: list[ParsedSection] = []
    for div in root.findall(".//t:text/t:body/t:div", _NS):
        head = _text(div.find("t:head", _NS))
        if head and _SKIP_SECTIONS.search(head):
            continue
        paragraphs: list[str] = []
        for paragraph in div.findall("t:p", _NS):
            paragraphs.append(_text(paragraph))
            for sentence in paragraph.findall("t:s", _NS) or [paragraph]:
                for ref in sentence.findall(".//t:ref[@type='bibr']", _NS):
                    for target in (ref.get("target") or "").split():
                        cited = by_key.get(target.lstrip("#"))
                        if cited is None:
                            continue
                        cited.mention_count += 1
                        if len(cited.contexts) < _MAX_CONTEXTS:
                            cited.contexts.append(
                                {"section": head, "sentence": _text(sentence)[:_MAX_CONTEXT_CHARS]}
                            )
        sections.append(ParsedSection(head=head, text="\n".join(paragraphs)))

    return ParsedPaper(
        title=title,
        authors=[a for a in authors if a],
        year=_year(source.find(".//t:date", _NS)) if source is not None else None,
        doi=_idno(source, "DOI") if source is not None else None,
        abstract=_text(header.find(".//t:abstract", _NS)) if header is not None else "",
        sections=sections,
        references=references,
    )


def body_text(parsed: ParsedPaper) -> str:
    """The argument of the Paper: body sections as '## heading' blocks, back matter excluded."""
    return "\n\n".join(
        f"## {section.head}\n{section.text}" if section.head else section.text
        for section in parsed.sections
        if section.text.strip()
    )


def full_text(tei: str) -> str:
    """Everything the Paper says, including captions, notes, and back matter, but not the bibliography."""
    root = ET.fromstring(tei)
    text = root.find(".//t:text", _NS)
    if text is None:
        return ""
    for parent in text.iter():
        for child in list(parent):
            if child.tag.endswith("listBibl"):
                parent.remove(child)
    return re.sub(r"\s+", " ", " ".join(text.itertext())).strip()
