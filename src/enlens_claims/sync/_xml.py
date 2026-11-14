"""XML from an online service, read without a DOCTYPE (14 November 2026, the WebDAV audit, DAV-6).

A storage service's answers (a WebDAV drive's PROPFIND, an S3 listing or error) never need a DOCTYPE. One that has one
could declare entities that grow a few hundred bytes into megabytes of text as they are read. So the parser itself
refuses a DOCTYPE: its target's `doctype` hook raises before any declaration in it is read, however the answer is
encoded (UTF-8, or UTF-16 with or without a byte order mark: expat finds the encoding, and calls the hook either way).
The same guard as the `.qdc` import's (`qdc_import._Reader.doctype`), kept here so `sync/` needs nothing of the
codebook's modules.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET


class _NoDoctype(ET.TreeBuilder):
    def doctype(self, *_a):
        raise ET.ParseError("a DOCTYPE, which no answer of a storage service has")


def parse(body: bytes) -> ET.Element:
    """The answer's root element. Raises ET.ParseError for XML that is not well-formed or that declares a DOCTYPE."""
    parser = ET.XMLParser(target=_NoDoctype())
    try:
        parser.feed(body)
        return parser.close()
    except ET.ParseError:
        raise
    except Exception as e:  # noqa: BLE001 - whatever the hook raised, through expat, is a refusal
        raise ET.ParseError(str(e)) from None
