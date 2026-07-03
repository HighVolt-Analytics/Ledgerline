"""Azure Document Intelligence and Foundry unit-cost estimation (USD)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.models.platform_credit_settings import PlatformCreditSettings
from app.services.document_ai_provider import DocumentAiProvider

# Vision: ~150 DPI PNG page averages ~1,500 input tokens per page (image + prompt overhead).
_FOUNDRY_INPUT_TOKENS_PER_PAGE = 1500
_FOUNDRY_OUTPUT_TOKENS_PER_CLASSIFY_CALL = 400
_FOUNDRY_OUTPUT_TOKENS_PER_EXTRACT_CALL = 1200
_FOUNDRY_OUTPUT_TOKENS_PER_READ_CALL = 200
_FOUNDRY_VISION_CALLS_PER_DOC = 3  # read, classify, extract

# Azure DI + gpt-4o-mini path: layout read + optional prebuilt-invoice + 2 text LLM calls.
_OPENAI_INPUT_TOKENS_PER_PAGE_TEXT = 250
_OPENAI_OUTPUT_TOKENS_CLASSIFY = 350
_OPENAI_OUTPUT_TOKENS_EXTRACT = 900
_OPENAI_PROMPT_OVERHEAD_TOKENS = 800


@dataclass(frozen=True)
class AzureUsageCost:
    total_usd: Decimal
    breakdown: dict[str, Any]


def _per_page_di_prebuilt(pages: int, rate_per_1000: Decimal) -> Decimal:
    if pages <= 0:
        return Decimal("0")
    return (Decimal(pages) / Decimal(1000)) * rate_per_1000


def _token_cost(tokens: int, rate_per_1m: Decimal) -> Decimal:
    if tokens <= 0:
        return Decimal("0")
    return (Decimal(tokens) / Decimal(1_000_000)) * rate_per_1m


def _line_item(
    *,
    service: str,
    model: str,
    operation: str,
    cost_usd: Decimal | float,
    pages: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    rate_description: str,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "service": service,
        "model": model,
        "operation": operation,
        "cost_usd": float(cost_usd),
        "rate_description": rate_description,
    }
    if pages is not None:
        item["pages"] = pages
    if input_tokens is not None:
        item["input_tokens"] = input_tokens
    if output_tokens is not None:
        item["output_tokens"] = output_tokens
    return item


def _setting_decimal(value: Decimal | None, fallback: str) -> Decimal:
    if value is None:
        return Decimal(fallback)
    return value


def _rates_snapshot(settings: PlatformCreditSettings) -> dict[str, float]:
    return {
        "di_prebuilt_per_1000_pages_usd": float(
            _setting_decimal(settings.azure_di_prebuilt_per_1000_pages_usd, "10.00")
        ),
        "di_read_per_1000_pages_usd": float(
            _setting_decimal(settings.azure_di_read_per_1000_pages_usd, "1.50")
        ),
        "foundry_input_per_1m_tokens_usd": float(
            _setting_decimal(settings.azure_foundry_input_per_1m_tokens_usd, "2.50")
        ),
        "foundry_output_per_1m_tokens_usd": float(
            _setting_decimal(settings.azure_foundry_output_per_1m_tokens_usd, "10.00")
        ),
        "openai_mini_input_per_1m_tokens_usd": float(
            _setting_decimal(settings.azure_openai_mini_input_per_1m_tokens_usd, "0.15")
        ),
        "openai_mini_output_per_1m_tokens_usd": float(
            _setting_decimal(settings.azure_openai_mini_output_per_1m_tokens_usd, "0.60")
        ),
    }


def estimate_upload_azure_cost(
    *,
    pages: int,
    provider: DocumentAiProvider | str,
    settings: PlatformCreditSettings,
) -> AzureUsageCost:
    """Estimate Azure spend for one document ingest + pipeline (USD)."""
    pages = max(pages, 0)
    provider_token = (
        provider.value if isinstance(provider, DocumentAiProvider) else str(provider)
    )
    rates = _rates_snapshot(settings)
    line_items: list[dict[str, Any]] = []

    if provider_token == DocumentAiProvider.AZURE_FOUNDRY_VISION.value:
        read_input = pages * _FOUNDRY_INPUT_TOKENS_PER_PAGE
        read_output = pages * _FOUNDRY_OUTPUT_TOKENS_PER_READ_CALL
        classify_input = pages * _FOUNDRY_INPUT_TOKENS_PER_PAGE
        classify_output = _FOUNDRY_OUTPUT_TOKENS_PER_CLASSIFY_CALL
        extract_input = pages * _FOUNDRY_INPUT_TOKENS_PER_PAGE
        extract_output = _FOUNDRY_OUTPUT_TOKENS_PER_EXTRACT_CALL

        input_tokens = read_input + classify_input + extract_input
        output_tokens = read_output + classify_output + extract_output

        read_in_usd = _token_cost(
            read_input,
            _setting_decimal(settings.azure_foundry_input_per_1m_tokens_usd, "2.50"),
        )
        read_out_usd = _token_cost(
            read_output,
            _setting_decimal(settings.azure_foundry_output_per_1m_tokens_usd, "10.00"),
        )
        classify_in_usd = _token_cost(
            classify_input,
            _setting_decimal(settings.azure_foundry_input_per_1m_tokens_usd, "2.50"),
        )
        classify_out_usd = _token_cost(
            classify_output,
            _setting_decimal(settings.azure_foundry_output_per_1m_tokens_usd, "10.00"),
        )
        extract_in_usd = _token_cost(
            extract_input,
            _setting_decimal(settings.azure_foundry_input_per_1m_tokens_usd, "2.50"),
        )
        extract_out_usd = _token_cost(
            extract_output,
            _setting_decimal(settings.azure_foundry_output_per_1m_tokens_usd, "10.00"),
        )

        in_rate = f"${rates['foundry_input_per_1m_tokens_usd']:.4f} per 1M input tokens"
        out_rate = f"${rates['foundry_output_per_1m_tokens_usd']:.4f} per 1M output tokens"

        line_items.extend(
            [
                _line_item(
                    service="Azure AI Foundry",
                    model="gpt-4o (vision)",
                    operation="ocr_read",
                    pages=pages,
                    input_tokens=read_input,
                    output_tokens=read_output,
                    rate_description=f"{in_rate}; {out_rate}",
                    cost_usd=read_in_usd + read_out_usd,
                ),
                _line_item(
                    service="Azure AI Foundry",
                    model="gpt-4o (vision)",
                    operation="classify_document",
                    pages=pages,
                    input_tokens=classify_input,
                    output_tokens=classify_output,
                    rate_description=f"{in_rate}; {out_rate}",
                    cost_usd=classify_in_usd + classify_out_usd,
                ),
                _line_item(
                    service="Azure AI Foundry",
                    model="gpt-4o (vision)",
                    operation="extract_fields",
                    pages=pages,
                    input_tokens=extract_input,
                    output_tokens=extract_output,
                    rate_description=f"{in_rate}; {out_rate}",
                    cost_usd=extract_in_usd + extract_out_usd,
                ),
            ]
        )

        llm_input_usd = read_in_usd + classify_in_usd + extract_in_usd
        llm_output_usd = read_out_usd + classify_out_usd + extract_out_usd
        breakdown = {
            "provider": provider_token,
            "pages": pages,
            "foundry_input_tokens": int(input_tokens),
            "foundry_output_tokens": int(output_tokens),
            "foundry_input_usd": float(llm_input_usd),
            "foundry_output_usd": float(llm_output_usd),
            "vision_calls": _FOUNDRY_VISION_CALLS_PER_DOC,
            "rates": rates,
            "line_items": line_items,
        }
        total = llm_input_usd + llm_output_usd
        breakdown["total_usd"] = float(total)
        return AzureUsageCost(total_usd=total, breakdown=breakdown)

    layout_usd = _per_page_di_prebuilt(
        pages, _setting_decimal(settings.azure_di_prebuilt_per_1000_pages_usd, "10.00")
    )
    invoice_usd = _per_page_di_prebuilt(
        pages, _setting_decimal(settings.azure_di_prebuilt_per_1000_pages_usd, "10.00")
    )
    di_rate = f"${rates['di_prebuilt_per_1000_pages_usd']:.4f} per 1,000 pages"

    classify_input_tokens = pages * _OPENAI_INPUT_TOKENS_PER_PAGE_TEXT + _OPENAI_PROMPT_OVERHEAD_TOKENS // 2
    extract_input_tokens = pages * _OPENAI_INPUT_TOKENS_PER_PAGE_TEXT + _OPENAI_PROMPT_OVERHEAD_TOKENS // 2
    classify_output_tokens = _OPENAI_OUTPUT_TOKENS_CLASSIFY
    extract_output_tokens = _OPENAI_OUTPUT_TOKENS_EXTRACT
    text_input_tokens = classify_input_tokens + extract_input_tokens
    text_output_tokens = classify_output_tokens + extract_output_tokens

    classify_in_usd = _token_cost(
        classify_input_tokens,
        _setting_decimal(settings.azure_openai_mini_input_per_1m_tokens_usd, "0.15"),
    )
    classify_out_usd = _token_cost(
        classify_output_tokens,
        _setting_decimal(settings.azure_openai_mini_output_per_1m_tokens_usd, "0.60"),
    )
    extract_in_usd = _token_cost(
        extract_input_tokens,
        _setting_decimal(settings.azure_openai_mini_input_per_1m_tokens_usd, "0.15"),
    )
    extract_out_usd = _token_cost(
        extract_output_tokens,
        _setting_decimal(settings.azure_openai_mini_output_per_1m_tokens_usd, "0.60"),
    )
    mini_in = classify_in_usd + extract_in_usd
    mini_out = classify_out_usd + extract_out_usd

    in_rate = f"${rates['openai_mini_input_per_1m_tokens_usd']:.4f} per 1M input tokens"
    out_rate = f"${rates['openai_mini_output_per_1m_tokens_usd']:.4f} per 1M output tokens"

    line_items.extend(
        [
            _line_item(
                service="Azure Document Intelligence",
                model="prebuilt-layout",
                operation="layout_analysis",
                pages=pages,
                rate_description=di_rate,
                cost_usd=layout_usd,
            ),
            _line_item(
                service="Azure Document Intelligence",
                model="prebuilt-invoice",
                operation="invoice_extraction",
                pages=pages,
                rate_description=di_rate,
                cost_usd=invoice_usd,
            ),
            _line_item(
                service="Azure OpenAI",
                model="gpt-4o-mini",
                operation="classify_document",
                input_tokens=classify_input_tokens,
                output_tokens=classify_output_tokens,
                rate_description=f"{in_rate}; {out_rate}",
                cost_usd=classify_in_usd + classify_out_usd,
            ),
            _line_item(
                service="Azure OpenAI",
                model="gpt-4o-mini",
                operation="extract_fields",
                input_tokens=extract_input_tokens,
                output_tokens=extract_output_tokens,
                rate_description=f"{in_rate}; {out_rate}",
                cost_usd=extract_in_usd + extract_out_usd,
            ),
        ]
    )

    breakdown = {
        "provider": provider_token or DocumentAiProvider.AZURE_DI.value,
        "pages": pages,
        "di_layout_pages": pages,
        "di_layout_usd": float(layout_usd),
        "di_invoice_pages": pages,
        "di_invoice_usd": float(invoice_usd),
        "openai_mini_input_tokens": int(text_input_tokens),
        "openai_mini_output_tokens": int(text_output_tokens),
        "openai_mini_input_usd": float(mini_in),
        "openai_mini_output_usd": float(mini_out),
        "rates": rates,
        "line_items": line_items,
    }
    total = layout_usd + invoice_usd + mini_in + mini_out
    breakdown["total_usd"] = float(total)
    return AzureUsageCost(total_usd=total, breakdown=breakdown)
