"""Patch accounting API routes and schemas."""

from pathlib import Path

root = Path(__file__).resolve().parents[1] / "app"

# schemas
schema_path = root / "schemas" / "accounting_integration.py"
schema = schema_path.read_text(encoding="utf-8")
if "XeroVerifyResponse" not in schema:
    schema = schema.replace(
        """class XeroSyncSettingsResponse(BaseModel):
    organisation: int = 0
    account: int = 0
    tax_rate: int = 0
    currency: int = 0


class XeroSyncContactsResponse(BaseModel):
    contact: int = 0""",
        """class XeroSyncSettingsResponse(BaseModel):
    organisation: int = 0
    account: int = 0
    tax_rate: int = 0
    currency: int = 0
    job_id: int | None = None


class XeroSyncContactsResponse(BaseModel):
    contact: int = 0
    job_id: int | None = None


class XeroVerifyResponse(BaseModel):
    connected: bool
    needs_reauth: bool = False
    organisation_id: str | None = None
    organisation_name: str | None = None
    verified_at: datetime | None = None
    message: str | None = None


class XeroMappingValidationErrorItem(BaseModel):
    field: str
    code: str
    message: str


class XeroMappingValidationErrorResponse(BaseModel):
    valid: bool = False
    errors: list[XeroMappingValidationErrorItem]""",
    )
    schema_path.write_text(schema, encoding="utf-8")
    print("schemas patched")

# api routes
api_path = root / "api" / "accounting_integrations.py"
api = api_path.read_text(encoding="utf-8")

if "XeroVerifyResponse" not in api:
    api = api.replace(
        "    XeroSyncSettingsResponse,\n)",
        "    XeroSyncSettingsResponse,\n    XeroVerifyResponse,\n)",
    )

if "verify_xero_connection" not in api:
    api = api.replace(
        "from app.services.integration.xero_push_service import get_invoice_xero_status, push_invoice_to_xero\n",
        "from app.services.integration.xero_push_service import get_invoice_xero_status, push_invoice_to_xero\n"
        "from app.services.integration.xero_mapping_validation import XeroMappingValidationError\n",
    )
    api = api.replace(
        "from app.services.integration.xero_sync_service import sync_contacts, sync_settings\n",
        "from app.services.integration.xero_sync_service import sync_contacts, sync_settings\n"
        "from app.services.integration.xero_verify_service import verify_xero_connection\n",
    )

verify_route = '''

@router.get("/xero/verify", response_model=ApiEnvelope[XeroVerifyResponse])
async def xero_verify(
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(require_admin),
) -> ApiEnvelope[XeroVerifyResponse]:
    data = await verify_xero_connection(db, ctx.tenant_id)
    await db.commit()
    return ApiEnvelope(data=XeroVerifyResponse.model_validate(data))
'''

if '"/xero/verify"' not in api:
    api = api.replace(
        """@router.get("/xero/connections", response_model=ApiEnvelope[XeroConnectionsResponse])""",
        verify_route
        + """@router.get("/xero/connections", response_model=ApiEnvelope[XeroConnectionsResponse])""",
    )

if "XeroMappingValidationError" not in api.split("xero_push_invoice")[1][:800]:
    api = api.replace(
        """    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    except XeroApiError as exc:
        await db.commit()
        raise HTTPException(exc.status_code or 502, exc.message) from exc
    await db.commit()
    return ApiEnvelope(data=XeroPushInvoiceResponse.model_validate(result))""",
        """    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except XeroMappingValidationError as exc:
        raise HTTPException(422, exc.result.to_dict()) from exc
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    except XeroApiError as exc:
        await db.commit()
        raise HTTPException(exc.status_code or 502, exc.message) from exc
    await db.commit()
    return ApiEnvelope(data=XeroPushInvoiceResponse.model_validate(result))""",
    )

api_path.write_text(api, encoding="utf-8")
print("accounting_integrations.py patched")
