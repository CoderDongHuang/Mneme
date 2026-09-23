from types import SimpleNamespace

import app.memory.reflection_scheduler as module


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.leases = {}

    def incr(self, key):
        self.values[key] = int(self.values.get(key, 0)) + 1
        return self.values[key]

    def expire(self, key, seconds):
        return True

    def get(self, key):
        return self.leases.get(key, self.values.get(key))

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.leases:
            return False
        self.leases[key] = value
        return True

    def eval(self, script, key_count, *args):
        if key_count == 1:
            key, token = args
            if self.leases.get(key) == token:
                del self.leases[key]
                return 1
            return 0
        counter, lease, token, claimed = args
        if self.leases.get(lease) != token:
            return 0
        remaining = int(self.values.get(counter, 0)) - int(claimed)
        if remaining > 0:
            self.values[counter] = remaining
        else:
            self.values.pop(counter, None)
        self.leases.pop(lease, None)
        return 1


class QueueExecutor:
    def __init__(self):
        self.jobs = []

    def submit(self, function, *args):
        self.jobs.append((function, args))

    def run_next(self):
        function, args = self.jobs.pop(0)
        return function(*args)


def test_only_one_node_claims_shared_reflection(monkeypatch):
    fake = FakeRedis()
    executor = QueueExecutor()
    monkeypatch.setattr(
        module,
        "settings",
        SimpleNamespace(memory_reflection_every_sessions=2, memory_reflection_lease_seconds=60),
    )
    monkeypatch.setattr(module, "run_reflection", lambda user_id: None)
    first = module.ReflectionScheduler(redis_client=fake, executor=executor)
    second = module.ReflectionScheduler(redis_client=fake, executor=executor)

    first.record_session("u")
    second.record_session("u")
    assert first.check_and_trigger("u") is True
    assert second.check_and_trigger("u") is False
    assert len(executor.jobs) == 1
    executor.run_next()
    assert fake.values == {}


def test_failed_reflection_keeps_count_for_retry(monkeypatch):
    fake = FakeRedis()
    executor = QueueExecutor()
    monkeypatch.setattr(
        module,
        "settings",
        SimpleNamespace(memory_reflection_every_sessions=1, memory_reflection_lease_seconds=60),
    )
    calls = {"count": 0}

    def fail_once(_):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary")

    monkeypatch.setattr(module, "run_reflection", fail_once)
    scheduler = module.ReflectionScheduler(redis_client=fake, executor=executor)
    scheduler.record_session("u")
    assert scheduler.check_and_trigger("u") is True
    executor.run_next()
    assert scheduler.check_and_trigger("u") is True
    executor.run_next()
    assert fake.values == {}
