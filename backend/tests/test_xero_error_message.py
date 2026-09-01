from types import SimpleNamespace

from app.integrations.xero.client import message_from_xero_response


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
