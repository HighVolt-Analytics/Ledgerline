"""Document type sample_analysis metadata on rule book config."""

from app.schemas.document_type import DocumentTypeDefinition, DocumentTypeSampleAnalysis


def test_document_type_sample_analysis_roundtrip() -> None:
    doc = DocumentTypeDefinition.model_validate(
        {
            "code": "DT-01",
            "title": "Invoice",
            "shortTitle": "Invoice",
            "klass": "Transactional",
            "posting": "Yes",
            "fraudRisk": "low",
            "oneLine": "Test",
            "routeTarget": "Vault",
            "sampleAnalysis": {
                "analyzedAt": "2026-06-20T10:00:00+00:00",
                "filenames": ["inv.pdf"],
                "fileCount": 1,
                "appliedAt": "2026-06-20T10:05:00+00:00",
                "recognitionSignals": ["text_tax_invoice"],
            },
        }
    )
    assert doc.sample_analysis is not None
    assert doc.sample_analysis.file_count == 1
    assert doc.sample_analysis.filenames == ["inv.pdf"]
    assert doc.sample_analysis.applied_at is not None

    dumped = doc.model_dump(by_alias=True)
    assert dumped["sampleAnalysis"]["recognitionSignals"] == ["text_tax_invoice"]

    restored = DocumentTypeDefinition.model_validate(dumped)
    assert isinstance(restored.sample_analysis, DocumentTypeSampleAnalysis)
    assert restored.sample_analysis.recognition_signals == ["text_tax_invoice"]
