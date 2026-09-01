from types import SimpleNamespace

from app.integrations.xero.client import message_from_xero_response
from app.integrations.xero.oauth import _token_error_message


def test_xero_put_error_uses_validation_messages() -> None:
    response = SimpleNamespace(
        text='{"Type":"ValidationException","Message":"A validation exception occurred","Elements":[{"ValidationErrors":[{"Message":"The TaxType code BASEXCLUDED is not valid"}]}]}',
        json=lambda: {
            "Type": "ValidationException",
            "Message": "A validation exception occurred",
            "Elements": [
                {"ValidationErrors": [{"Message": "The TaxType code BASEXCLUDED is not valid"}]}
            ],
        },
    )
    assert "BASEXCLUDED" in message_from_xero_response(response, "Xero PUT failed")
    assert message_from_xero_response(response, "Xero PUT failed") != "Xero PUT failed"


def test_token_error_message_uses_identity_error_description() -> None:
    response = SimpleNamespace(
        status_code=400,
        text='{"error":"invalid_grant"}',
        json=lambda: {
            "error": "invalid_grant",
            "error_description": "Invalid authorization code, redirect_uri, or client credentials",
        },
    )
    message = _token_error_message(response, "Xero token exchange failed")
    assert "invalid_grant" in message or "redirect_uri" in message
    assert "Xero token exchange failed" in message
