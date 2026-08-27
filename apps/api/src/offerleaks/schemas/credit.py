"""Request/response schemas for the `/credits` router."""

from pydantic import BaseModel


class CreditBalanceResponse(BaseModel):
    balance: int
    cost_per_analysis: int
