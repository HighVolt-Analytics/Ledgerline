"""Document AI provider abstraction — Azure DI vs vision LLM providers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Sequence

from app.config import get_settings
from app.schemas.document_type import DocumentTypeDefinition
from app.schemas.llm_document import LlmDocumentResult
from app.schemas.ocr_artifact import OcrArtifact
from app.services.extraction.azure_foundry_vision_client import (
    classify_only_azure_foundry,
    extract_fields_azure_foundry,
    is_azure_foundry_vision_available,
    read_for_classification_azure_foundry,
)
from app.services.extraction.di_extract_service import (
    enrich_ocr_with_invoice_model,
    read_layout_for_classification,
)
from app.services.extraction.document_intelligence import is_di_enabled
from app.services.extraction.gemini_vision_client import (
    classify_only_gemini,
    extract_fields_gemini,
    is_gemini_vision_available,
    read_for_classification_gemini,
)
from app.services.extraction.llm_document_service import classify_document_only, extract_document_fields
from app.services.tenant.tenant_org_context import OrgContext


@dataclass(frozen=True)
class ExtractFieldsResult:
    llm: LlmDocumentResult | None
    ocr: OcrArtifact


class DocumentAiProvider(str, Enum):
    AZURE_DI = "azure_di"
    GEMINI_VISION = "gemini_vision"
    AZURE_FOUNDRY_VISION = "azure_foundry_vision"

    @classmethod
    def from_config(cls, token: str | None) -> DocumentAiProvider:
        normalized = (token or "").strip().lower()
        if normalized in {cls.GEMINI_VISION.value, "gemini"}:
            return cls.GEMINI_VISION
        if normalized in {cls.AZURE_FOUNDRY_VISION.value, "azure_foundry"}:
            return cls.AZURE_FOUNDRY_VISION
        return cls.AZURE_DI


def provider_available(provider: DocumentAiProvider) -> bool:
    if provider == DocumentAiProvider.GEMINI_VISION:
        return is_gemini_vision_available()
    if provider == DocumentAiProvider.AZURE_FOUNDRY_VISION:
        return is_azure_foundry_vision_available()
    return is_di_enabled() and get_settings().runtime_llm_available


def provider_unavailable_reason(provider: DocumentAiProvider) -> str:
    if provider == DocumentAiProvider.GEMINI_VISION:
        if not get_settings().gemini_configured:
            return "GEMINI_API_KEY not configured"
        return "Gemini vision unavailable"
    if provider == DocumentAiProvider.AZURE_FOUNDRY_VISION:
        if not get_settings().azure_foundry_vision_configured:
            return "Azure AI Foundry vision not configured"
        return "Azure AI Foundry vision unavailable"
    if not is_di_enabled():
        return "Azure Document Intelligence not configured"
    if not get_settings().runtime_llm_available:
        return "Azure OpenAI runtime LLM not configured"
    return "Azure DI provider unavailable"


async def read_for_classification(
    file_path: str | Path,
    *,
    provider: DocumentAiProvider,
    org: OrgContext,
    document_types: Sequence[DocumentTypeDefinition],
) -> OcrArtifact:
    path = Path(file_path)
    if provider == DocumentAiProvider.GEMINI_VISION:
        return await read_for_classification_gemini(
            path,
            org=org,
            document_types=document_types,
        )
    if provider == DocumentAiProvider.AZURE_FOUNDRY_VISION:
        return await read_for_classification_azure_foundry(
            path,
            org=org,
            document_types=document_types,
        )
    return await asyncio.to_thread(read_layout_for_classification, path)


async def classify_only(
    ocr: OcrArtifact,
    *,
    file_path: str | Path | None = None,
    org: OrgContext,
    document_types: Sequence[DocumentTypeDefinition],
    few_shots: Sequence[dict[str, str]] | None,
    provider: DocumentAiProvider,
) -> LlmDocumentResult | None:
    if provider in (DocumentAiProvider.GEMINI_VISION, DocumentAiProvider.AZURE_FOUNDRY_VISION):
        if not file_path:
            return None
        if provider == DocumentAiProvider.GEMINI_VISION:
            return await classify_only_gemini(
                file_path,
                ocr,
                org=org,
                document_types=document_types,
                few_shots=few_shots,
            )
        return await classify_only_azure_foundry(
            file_path,
            ocr,
            org=org,
            document_types=document_types,
            few_shots=few_shots,
        )
    return await classify_document_only(
        ocr,
        org=org,
        document_types=document_types,
        few_shots=few_shots,
    )


async def extract_fields(
    ocr: OcrArtifact,
    *,
    file_path: str | Path,
    org: OrgContext,
    document_types: Sequence[DocumentTypeDefinition],
    confirmed_dt: str,
    few_shots: Sequence[dict[str, str]] | None,
    provider: DocumentAiProvider,
) -> ExtractFieldsResult:
    path = Path(file_path)
    dt_token = confirmed_dt.strip().upper()
    dt_definition = next(
        (d for d in document_types if (d.code or "").strip().upper() == dt_token),
        None,
    )
    if provider == DocumentAiProvider.GEMINI_VISION:
        llm = await extract_fields_gemini(
            ocr,
            path,
            org=org,
            document_types=document_types,
            confirmed_dt=confirmed_dt,
            few_shots=few_shots,
        )
        return ExtractFieldsResult(llm=llm, ocr=ocr)
    if provider == DocumentAiProvider.AZURE_FOUNDRY_VISION:
        llm = await extract_fields_azure_foundry(
            ocr,
            path,
            org=org,
            document_types=document_types,
            confirmed_dt=confirmed_dt,
            few_shots=few_shots,
        )
        return ExtractFieldsResult(llm=llm, ocr=ocr)
    enriched = await asyncio.to_thread(
        enrich_ocr_with_invoice_model,
        ocr,
        path,
        confirmed_dt=dt_token,
        dt_definition=dt_definition,
    )
    llm = await extract_document_fields(
        enriched,
        org=org,
        document_types=document_types,
        confirmed_dt=confirmed_dt,
        few_shots=few_shots,
    )
    return ExtractFieldsResult(llm=llm, ocr=enriched)
