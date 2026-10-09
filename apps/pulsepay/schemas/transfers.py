from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator


class TransferRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "source_account_id": "2c958f12-addb-5521-ae8d-2d60a0706360",
                    "destination_account_id": "97e8ea8f-531a-5f9b-b64a-1ccd3d9c90bb",
                    "amount_minor": 10000,
                    "currency": "INR",
                }
            ]
        },
    )
    source_account_id: UUID
    destination_account_id: UUID
    amount_minor: int = Field(gt=0, le=2**63 - 1, strict=True)
    currency: str = Field(pattern=r"^[A-Z]{3}$")

    @model_validator(mode="after")
    def distinct(self):
        if self.source_account_id == self.destination_account_id:
            raise ValueError("Source and destination must be distinct")
        return self


class TransferResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    source_account_id: UUID
    destination_account_id: UUID
    amount_minor: int
    currency: str
    status: str
    committed_at: datetime
    request_id: str = ""
