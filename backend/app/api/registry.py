"""Universal field registry API."""

from fastapi import APIRouter

from app.config import get_settings
from app.registry.adapter import use_field_registry
from app.registry.loader import get_field_registry
from app.schemas.common import ApiEnvelope
from app.schemas.registry import RegistryFieldResponse, RegistryFieldsResponse
from app.services.classification.document_type_field_keys import CANONICAL_EXTRACTION_FIELD_KEYS
from app.services.extraction.extraction_field_values import extraction_field_label

router = APIRouter(prefix="/registry", tags=["registry"])


@router.get("/fields", response_model=ApiEnvelope[RegistryFieldsResponse])
async def list_registry_fields() -> ApiEnvelope[RegistryFieldsResponse]:
    """Canonical extraction fields for Rule Book UI."""
    settings = get_settings()
    if use_field_registry():
        registry = get_field_registry()
        fields = [
            RegistryFieldResponse(
                key=row.key,
                label=row.label,
                data_type=row.data_type,
                category=row.category,
                posting_critical=row.posting_critical,
                grounding_required=row.grounding_required,
                synonyms=list(row.synonyms),
            )
            for row in sorted(registry.fields.values(), key=lambda item: item.key)
            if row.key in CANONICAL_EXTRACTION_FIELD_KEYS
        ]
        return ApiEnvelope(
            data=RegistryFieldsResponse(
                version=registry.version,
                use_field_registry=True,
                fields=fields,
            )
        )

    fields = [
        RegistryFieldResponse(
            key=key,
            label=extraction_field_label(key),
        )
        for key in sorted(CANONICAL_EXTRACTION_FIELD_KEYS)
    ]
    return ApiEnvelope(
        data=RegistryFieldsResponse(
            version="legacy",
            use_field_registry=False,
            fields=fields,
        )
    )
