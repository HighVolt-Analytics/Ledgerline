from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class LineItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    invoice_id: int
    description: str | None
    qty: Decimal | None
    unit_price: Decimal | None
    amount: Decimal | None
    tax_amount: Decimal | None = None
