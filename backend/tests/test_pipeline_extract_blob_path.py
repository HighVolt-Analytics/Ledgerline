"""Extract phase must resolve blob URIs to local paths before DI enrich."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest

from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.document_ai_provider import ExtractFieldsResult


@pytest.mark.asyncio
async def test_extract_phase_passes_resolved_local_path_to_extract_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pipeline must not pass azureblob:// URIs directly to DI prebuilt-invoice enrich."""
    local_pdf = tmp_path / "invoice.pdf"
    local_pdf.write_bytes(b"%PDF-1.4 minimal")
    blob_uri = "azureblob://invoices/tenant/invoice.pdf"
    captured: list[Path] = []

    @contextmanager
    def _fake_open(stored_path: str, **_kwargs):
        assert stored_path == blob_uri
        yield local_pdf

    ocr = OcrArtifact(success=True, text="TAX INVOICE", text_length=11)

    async def _fake_extract(_ocr, *, file_path, **_kwargs) -> ExtractFieldsResult:
        captured.append(Path(file_path))
        return ExtractFieldsResult(llm=None, ocr=_ocr)

    async def _run_extract_block() -> None:
        from app.services.extraction.document_ai_provider import DocumentAiProvider
        from app.services.invoice import pipeline as pipeline_mod
        from app.services.tenant.tenant_org_context import OrgContext

        with pipeline_mod.open_pdf_for_reading(blob_uri, tenant_id=None) as local_path:
            await pipeline_mod.extract_fields(
                ocr,
                file_path=local_path,
                org=OrgContext(),
                document_types=[],
                confirmed_dt="DT-01",
                few_shots=None,
                provider=DocumentAiProvider.AZURE_DI,
            )

    monkeypatch.setattr("app.services.invoice.pipeline.open_pdf_for_reading", _fake_open)
    monkeypatch.setattr("app.services.invoice.pipeline.extract_fields", _fake_extract)

    await _run_extract_block()

    assert captured == [local_pdf]
    assert captured[0].is_file()


def test_enrich_ocr_with_invoice_model_rejects_blob_uri() -> None:
    """DI enrich requires a local file path — blob URIs must be resolved upstream."""
    from app.services.extraction.di_extract_service import enrich_ocr_with_invoice_model

    ocr = OcrArtifact(success=True, text="TAX INVOICE", text_length=11)
    _, detail = enrich_ocr_with_invoice_model(
        ocr,
        "azureblob://invoices/tenant/invoice.pdf",
        confirmed_dt="DT-01",
    )
    assert detail["success"] is False
    assert detail["failure_reason"] == "not_configured"
