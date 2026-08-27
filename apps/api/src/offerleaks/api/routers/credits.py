"""Credit-balance visibility endpoint (Version 4: Credit System).

Read-only. There is deliberately no client-facing mutation endpoint here
-- balances only change through `CreditService`, called from
`AuthService` (initial grant) and `AnalysisService` (consume/refund).
Identity is always derived from the authenticated request context
(`CurrentUser`), never from a path or query parameter, so there is no
`GET /credits/{user_id}` shape for a client to try to point at someone
else's balance.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from offerleaks.auth.dependencies import CurrentUser
from offerleaks.core.db import get_db_session
from offerleaks.schemas.credit import CreditBalanceResponse
from offerleaks.services.credit_service import CreditService

router = APIRouter(prefix="/credits", tags=["credits"])


@router.get("/me", response_model=CreditBalanceResponse)
async def get_my_credits(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> CreditBalanceResponse:
    credits = CreditService(db)
    balance = await credits.get_balance(current_user.id)
    return CreditBalanceResponse(balance=balance, cost_per_analysis=credits.cost_per_analysis)
