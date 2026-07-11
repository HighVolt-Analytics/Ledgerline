"""Patch main.py and models/__init__.py for Xero refinement."""

from pathlib import Path

root = Path(__file__).resolve().parents[1] / "app"

main_path = root / "main.py"
main = main_path.read_text(encoding="utf-8")

if "xero_refinement" not in main:
    main = main.replace(
        "    xero_webhooks,\n)",
        "    xero_webhooks,\n    xero_refinement,\n)",
    )
    main = main.replace(
        "from fastapi import Depends, FastAPI\n",
        "from fastapi import Depends, FastAPI, Request\n",
    )
    main = main.replace(
        "from fastapi.responses import HTMLResponse\n",
        "from fastapi.responses import HTMLResponse, JSONResponse\n",
    )
    main = main.replace(
        "from app.services.rule_book.rule_book_save_buffer import flush_all_rule_book_save_buffers\n",
        "from app.services.rule_book.rule_book_save_buffer import flush_all_rule_book_save_buffers\n"
        "from app.services.integration.xero_mapping_validation import XeroMappingValidationError\n",
    )
    main = main.replace(
        """app = FastAPI(
    title="Invoice Processing Pipeline",
    version="1.0.0",
    lifespan=lifespan,
    root_path=_settings.root_path,
)

app.add_middleware(CorrelationIdMiddleware)""",
        """app = FastAPI(
    title="Invoice Processing Pipeline",
    version="1.0.0",
    lifespan=lifespan,
    root_path=_settings.root_path,
)


@app.exception_handler(XeroMappingValidationError)
async def xero_mapping_validation_handler(
    _request: Request,
    exc: XeroMappingValidationError,
) -> JSONResponse:
    return JSONResponse(status_code=422, content=exc.result.to_dict())

app.add_middleware(CorrelationIdMiddleware)""",
    )
    main = main.replace(
        "app.include_router(accounting_integrations.router, prefix=\"/api\", dependencies=_api_deps)\n",
        "app.include_router(accounting_integrations.router, prefix=\"/api\", dependencies=_api_deps)\n"
        "app.include_router(xero_refinement.router, prefix=\"/api\", dependencies=_api_deps)\n",
    )
    main_path.write_text(main, encoding="utf-8")
    print("main.py patched")

init_path = root / "models" / "__init__.py"
init_text = init_path.read_text(encoding="utf-8")
if "AccountingSyncJob" not in init_text:
    init_text = init_text.replace(
        "from app.models.accounting_integration import AccountingIntegration\n",
        "from app.models.accounting_sync_job import AccountingSyncJob\n"
        "from app.models.accounting_integration import AccountingIntegration\n",
    )
    init_text = init_text.replace(
        '    "AccountingIntegration",\n    "ExternalAccountingRef",',
        '    "AccountingIntegration",\n    "AccountingSyncJob",\n    "ExternalAccountingRef",',
    )
    init_path.write_text(init_text, encoding="utf-8")
    print("models/__init__.py patched")
