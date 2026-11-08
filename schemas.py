from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator


class SubscriptionRequest(BaseModel):
    email: EmailStr
    sku: str

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("sku")
    @classmethod
    def normalize_sku(cls, value: str) -> str:
        sku = value.strip()
        if not sku:
            raise ValueError("SKU must not be empty")
        return sku


class SubscriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    sku: str
    status: str
    created_at: datetime
    
class StockWebhookRequest(BaseModel):
    event_id: str
    type: str | None = None
    sku: str
    quantity: int
    occurred_at: datetime | None = None

    @field_validator("event_id", "sku")
    @classmethod
    def validate_required_strings(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Field must not be empty")
        return value

    @field_validator("type")
    @classmethod
    def validate_event_type(cls, value: str | None) -> str | None:
        if value is None:
            return None

        value = value.strip()
        if not value:
            raise ValueError("Field must not be empty")
        if value != "stock.updated":
            raise ValueError("Unsupported webhook event type")
        return value

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, value: int) -> int:
        if value < 0:
            raise ValueError("Quantity must not be negative")
        return value