"""ADMIN-CREATEUSER-RACE-01: the existence pre-check and the commit in
create_user() aren't atomic. Two concurrent requests for the same username
can both pass the pre-check; the loser's commit hits the DB's unique
constraint. This must surface as 409, not an unhandled 500."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.admin import create_user, CreateUserRequest


@pytest.mark.asyncio
async def test_create_user_race_yields_409_not_500():
    body = CreateUserRequest(username="raced", password="password1", role="viewer")

    db = AsyncMock()
    db.add = MagicMock()  # sync in SQLAlchemy — must not be auto-mocked as a coroutine
    # Pre-check SELECT finds nothing — this request "won" the existence check.
    select_result = MagicMock()
    select_result.scalar_one_or_none.return_value = None
    db.execute.return_value = select_result
    # But another request already committed the same username first, so this
    # commit hits the DB's own unique-constraint violation.
    db.commit.side_effect = IntegrityError("stmt", {}, Exception("UNIQUE constraint failed"))

    with pytest.raises(HTTPException) as exc_info:
        await create_user(
            body=body,
            request=MagicMock(),
            current_user={"id": 1, "username": "admin", "role": "admin"},
            __=None,
            db=db,
        )

    assert exc_info.value.status_code == 409
    assert "already exists" in exc_info.value.detail
    db.rollback.assert_awaited_once()
