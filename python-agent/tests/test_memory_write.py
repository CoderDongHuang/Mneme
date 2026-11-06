"""Idle extraction uses the frozen turn, excluding the current question."""
from datetime import timedelta
from unittest.mock import Mock

import pytest

from app.core.config import settings
from app.core.time import utc_now
from app.memory import completion, distillation
from app.models.chat import MemoryCompletion, Message


@pytest.mark.parametrize("minutes,count,expected", [(0, 0, False), (0, 1, False), (5, 2, False),
    (settings.distillation_idle_minutes, 2, False), (settings.distillation_idle_minutes + 1, 2, True), (38, 5, True)])
def test_idle_window_and_multi_round_snapshot(monkeypatch, minutes, count, expected):
    now = utc_now()
    history = [Message(role="assistant" if i % 2 else "user", content=f"old {i}",
                       timestamp=(now-timedelta(minutes=minutes)).isoformat()) for i in range(max(0, count-1))]
    if count:
        history.append(Message(role="user", content="current question", timestamp=now.isoformat()))
    request = MemoryCompletion(user_id="owner", session_id="session", delivery_id="turn", reference_time=now.isoformat(),
                               history=history, answer="saved answer")
    distill = Mock(return_value=[])
    monkeypatch.setattr(distillation, "distill_conversation", distill)
    assert completion._extract(request) == []
    if expected:
        distill.assert_called_once_with("owner", "session", [{"role": m.role, "content": m.content} for m in history[:-1]])
    else:
        distill.assert_not_called()
