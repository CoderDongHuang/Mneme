"""Isolated Redis AUTH/AOF/Stream crash recovery acceptance. Never touches project data."""
import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import time
import uuid


def probe(phase):
    # Keep import-time local stores isolated from the running application.
    os.environ.update({
        "VECTOR_STORE_MODE": "local", "QDRANT_PATH": "/tmp/redis-qa-qdrant",
        "CHROMA_PATH": "/tmp/redis-qa-legacy-chroma",
        "LEXICAL_INDEX_PATH": "/tmp/redis-qa-lexical.sqlite3",
        "MEMORY_VERSION_STORE_PATH": "/tmp/redis-qa-memory.sqlite3",
        "AGENT_TRACE_STORE_PATH": "/tmp/redis-qa-traces.sqlite3",
        "SESSION_DATA_PATH": "/tmp/redis-qa-sessions",
        "MNEME_OFFLINE_EMBEDDINGS": "true", "AUXILIARY_STORE_BACKEND": "sqlite",
    })
    import sys
    sys.path.insert(0, "/repo/python-agent")
    import app.memory.reflection_scheduler as module
    from app.memory.session_persistence import session_persistence

    scheduler = module.ReflectionScheduler()
    assert scheduler.queue_available()
    assert session_persistence.available
    client = scheduler._redis
    assert client.config_get("appendonly")["appendonly"] == "yes"
    assert client.config_get("appendfsync")["appendfsync"] == "everysec"
    if phase == "enqueue":
        module.settings = replace(module.settings, memory_reflection_every_sessions=1)
        assert scheduler.record_session("redis-qa") == 1
        assert scheduler.check_and_trigger("redis-qa")
        messages = client.xreadgroup(module._QUEUE_GROUP, "crashed-worker", {module._QUEUE_KEY: ">"})
        assert messages
        assert client.xpending(module._QUEUE_KEY, module._QUEUE_GROUP)["pending"] == 1
        # Redis 7.2+: await an fsync before SIGKILL rather than relying on timing.
        assert client.execute_command("WAITAOF", 1, 0, 5000)[0] == 1
    else:
        assert client.xpending(module._QUEUE_KEY, module._QUEUE_GROUP)["pending"] == 1
        calls = []
        module.run_reflection = calls.append
        assert scheduler.reclaim_stale_reflections(min_idle_ms=1) == 1
        assert calls == ["redis-qa"]
        assert client.xpending(module._QUEUE_KEY, module._QUEUE_GROUP)["pending"] == 0
        assert client.get(scheduler._counter_key("redis-qa")) is None
        sys.path.insert(0, "/repo/python-agent/scripts")
        from check_reflection_lease import check
        check()


def run(*args, env=None, check=True):
    result = subprocess.run(args, text=True, encoding="utf-8", errors="replace",
                            capture_output=True, env=env)
    if check and result.returncode:
        raise RuntimeError(f"{args[0]} failed: {result.stderr[-4000:]}")
    return result


def verify(image):
    root = Path(__file__).resolve().parents[1]
    results = []
    for password in ("", "isolated-redis-test-secret"):
        env = dict(os.environ, REDIS_PASSWORD=password)
        config = json.loads(run("docker", "compose", "-f", str(root / "docker-compose.yml"),
                                "config", "--format", "json", env=env).stdout)
        services = config["services"]
        for name in ("redis", "java-gateway", "python-agent"):
            assert services[name]["environment"]["REDIS_PASSWORD"] == password
        for name in ("java-gateway", "python-agent"):
            assert services[name]["depends_on"]["redis"]["condition"] == "service_healthy"
        server = services["redis"]
        suffix = uuid.uuid4().hex[:10]
        name, network, volume = (f"mneme-redis-qa-{suffix}{tail}" for tail in ("", "-net", "-data"))
        run("docker", "network", "create", network)
        try:
            run("docker", "run", "-d", "--name", name, "--network", network,
                "-e", f"REDIS_PASSWORD={password}", "-v", f"{volume}:/data",
                server["image"], *(part.replace("$$", "$") for part in server["command"]))
            for _ in range(100):
                ping = run("docker", "exec", name, "sh", "-c",
                           server["healthcheck"]["test"][1].replace("$$", "$"), check=False)
                if ping.returncode == 0:
                    break
                time.sleep(0.1)
            else:
                raise RuntimeError("Redis healthcheck failed")
            if password:
                assert "NOAUTH" in run("docker", "exec", name, "redis-cli", "ping").stdout
            for phase in ("enqueue", "recover"):
                run("docker", "run", "--rm", "--network", network,
                    "-e", f"REDIS_HOST={name}", "-e", f"REDIS_PASSWORD={password}",
                    "-v", f"{root.as_posix()}:/repo", "--entrypoint", "python", image,
                    "/repo/scripts/verify_redis_durability.py", "--probe", phase)
                if phase == "enqueue":
                    run("docker", "kill", "--signal", "KILL", name)
                    run("docker", "start", name)
            results.append({"authentication": bool(password), "python_clients": "passed",
                            "aof_sigkill_pending_recovery": "passed"})
        finally:
            run("docker", "rm", "-f", name, check=False)
            run("docker", "volume", "rm", volume, check=False)
            run("docker", "network", "rm", network, check=False)
    print(json.dumps({"isolated": True, "results": results}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="mneme-python-agent")
    parser.add_argument("--probe", choices=("enqueue", "recover"))
    args = parser.parse_args()
    if args.probe:
        probe(args.probe)
    else:
        verify(args.image)
