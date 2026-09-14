"""Dictionary adoption lineage detection tests."""

from __future__ import annotations

from app.services.rule_book.document_type_adoption_lineage_service import (
    detect_new_dictionary_adoptions,
)


def test_detect_new_dictionary_adoptions_finds_first_save_only() -> None:
    before = {
        "document_types": [
            {"code": "DT-01", "sourceDictionaryCode": "LIB-001", "createdFromDictionaryVersion": 1},
        ]
    }
    after = {
        "document_types": [
            {"code": "DT-01", "sourceDictionaryCode": "LIB-001", "createdFromDictionaryVersion": 1},
            {"code": "DT-02", "sourceDictionaryCode": "LIB-014", "createdFromDictionaryVersion": 1},
        ]
    }
    rows = detect_new_dictionary_adoptions(before, after)
    assert rows == [
        {
            "org_doc_type_code": "DT-02",
            "source_dictionary_code": "LIB-014",
            "source_dictionary_version": 1,
        }
    ]


def test_detect_new_dictionary_adoptions_ignores_rows_without_provenance() -> None:
    after = {
        "document_types": [
            {"code": "DT-01", "title": "Legacy type"},
        ]
    }
    assert detect_new_dictionary_adoptions(None, after) == []
