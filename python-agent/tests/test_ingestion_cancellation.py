from unittest.mock import MagicMock

import pytest

from app.knowledge import cancellation


def test_cancelled_request_stops_before_body_and_releases_own_lock(monkeypatch):
    client = MagicMock()
    client.set.return_value = True
    client.exists.return_value = True
    monkeypatch.setattr(cancellation.redis, "Redis", lambda **kwargs: client)
    with pytest.raises(cancellation.IngestionCancelled):
        with cancellation.ingestion_task("u1", "task1"):
            pytest.fail("cancelled ingestion was executed")
    client.delete.assert_called_once_with("mneme:ingestion:active:u1:task1")
    cancellation.check_cancelled()  # No leaked task context.


def test_duplicate_worker_cannot_remove_the_active_workers_lock(monkeypatch):
    client = MagicMock()
    client.set.return_value = False
    monkeypatch.setattr(cancellation.redis, "Redis", lambda **kwargs: client)
    with pytest.raises(RuntimeError, match="仍在运行"):
        with cancellation.ingestion_task("u1", "task1"):
            pytest.fail("duplicate executed")
    client.delete.assert_not_called()


def test_cancellation_is_checked_during_processing(monkeypatch):
    client = MagicMock()
    client.set.return_value = True
    client.exists.side_effect = [False, True]
    monkeypatch.setattr(cancellation.redis, "Redis", lambda **kwargs: client)
    with cancellation.ingestion_task("u1", "task1"):
        with pytest.raises(cancellation.IngestionCancelled):
            cancellation.check_cancelled()
