"""A durable deletion fence must precede Redis access, including late workers."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock

import pytest
import redis

import app.memory.reflection_scheduler as module
from app.knowledge.generations import GenerationStore, StaleGeneration, generation_store


def test_deleted_user_rejects_all_state_creating_paths_before_redis():
    generation_store.tombstone("deleted")
    client = Mock()
    scheduler = module.ReflectionScheduler(redis_client=client)
    with pytest.raises(StaleGeneration):
        scheduler.record_session("deleted", "s", "turn")
    assert not scheduler.check_and_trigger("deleted")
    assert not scheduler._claim_shared("deleted", "job", "owner")
    assert not scheduler._complete_shared("deleted", 1, "job", "owner", "1-0")
    scheduler._run_queued_reflection("1-0", {"user_id": "deleted", "claimed_count": "1"})
    client.assert_not_called()
    assert not client.method_calls


def test_redis_failure_keeps_committed_tombstone_for_new_instance():
    with generation_store.locked("deleted") as state:
        state["reflection_deliveries"] = {"a" * 64: {"b" * 64: True}}
    client = Mock()
    client.delete.side_effect = redis.ConnectionError("offline")
    scheduler = module.ReflectionScheduler(redis_client=client)
    with pytest.raises(redis.ConnectionError):
        scheduler.delete_user("deleted")
    assert GenerationStore(generation_store.path).snapshot("deleted")["deleted"]
    assert "reflection_deliveries" not in GenerationStore(generation_store.path).snapshot("deleted")
    client.reset_mock()
    with pytest.raises(StaleGeneration):
        module.ReflectionScheduler(redis_client=client).record_session("deleted", "s", "turn")
    assert not client.method_calls


def test_manifest_failure_never_touches_redis(tmp_path, monkeypatch):
    monkeypatch.setattr(generation_store, "path", tmp_path)  # A directory cannot be opened as SQLite.
    client = Mock()
    scheduler = module.ReflectionScheduler(redis_client=client)
    with pytest.raises(Exception, match="unable to open"):
        scheduler.record_session("user", "s", "turn")
    with pytest.raises(Exception, match="unable to open"):
        scheduler.delete_user("user")
    assert not client.method_calls


def test_record_already_in_storage_finishes_before_durable_delete():
    client = Mock()
    client.scan_iter.return_value = []
    client.xrevrange.return_value = []
    client.exists.return_value = 0
    entered, release, deleting = Event(), Event(), Event()

    def record(*_args):
        entered.set()
        assert release.wait(5)
        return 1

    client.eval.side_effect = record
    first = module.ReflectionScheduler(redis_client=client)
    second = module.ReflectionScheduler(redis_client=client)

    def cleanup():
        deleting.set()
        return second.delete_user("racing")

    with ThreadPoolExecutor(max_workers=2) as pool:
        writing = pool.submit(first.record_session, "racing", "s", "turn")
        try:
            assert entered.wait(5)
            deletion = pool.submit(cleanup)
            assert deleting.wait(5)
            assert not client.delete.called
        finally:
            release.set()
        assert writing.result(5) == 1
        assert deletion.result(5) == {"keys": 0, "queue_entries": 0}
    assert generation_store.snapshot("racing")["deleted"]
    with pytest.raises(StaleGeneration):
        first.record_session("racing", "s", "late")


def test_marker_scan_checks_exact_digest_and_escapes_imported_user():
    client = Mock()
    user = "old*?[user]"
    prefix = module._DELIVERY_PREFIX + user + ":"
    own = prefix + "a" * 64
    client.scan_iter.return_value = [own, prefix + "nested:" + "b" * 64,
                                    module._DELIVERY_PREFIX + "other:" + "c" * 64,
                                    prefix + "z" * 64]
    scheduler = module.ReflectionScheduler(redis_client=client)
    assert list(scheduler._delivery_keys(user)) == [own]
    pattern = client.scan_iter.call_args.kwargs["match"]
    assert "old\\*\\?\\[user\\]" in pattern


def test_consumer_survives_durable_fence_failure_without_logging_payload(caplog):
    client = Mock()
    client.xreadgroup.return_value = [("queue", [("1-0", {})])]
    scheduler = module.ReflectionScheduler(redis_client=client)
    scheduler._queue_stop = Mock()
    scheduler._queue_stop.is_set.side_effect = [False, False, True]
    scheduler._run_queued_reflection = Mock(side_effect=[RuntimeError("private-payload"), None])
    scheduler._consume_reflections()
    assert scheduler._run_queued_reflection.call_count == 2
    scheduler._queue_stop.wait.assert_called_once_with(1)
    assert "private-payload" not in caplog.text
    client.xack.assert_not_called()
