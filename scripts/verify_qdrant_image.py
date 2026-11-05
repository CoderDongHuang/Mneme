"""Verify the patched vector image without mounting any application data."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.error
import urllib.request
import uuid


def docker(*args: str) -> str:
    result = subprocess.run(["docker", *args], capture_output=True, text=True, check=True)
    return result.stdout.strip()


def verify(image: str, upstream: str) -> None:
    def digest(ref: str) -> str:
        return docker("run", "--rm", "--network", "none", "--entrypoint", "sha256sum", ref, "/qdrant/qdrant").split()[0]

    if digest(image) != digest(upstream):
        raise RuntimeError("Patched image changed the upstream Qdrant binary")
    config = json.loads(docker("image", "inspect", image))[0]["Config"]
    if config["User"] != "10001:10001":
        raise RuntimeError("Qdrant must retain the non-root runtime user")
    name = "mneme-vector-image-check-" + uuid.uuid4().hex
    try:
        docker("run", "--detach", "--name", name, "--publish", "127.0.0.1::6333", image)
        state = json.loads(docker("inspect", name))[0]
        if state["Mounts"]:
            raise RuntimeError("Image check unexpectedly mounted data")
        port = state["NetworkSettings"]["Ports"]["6333/tcp"][0]["HostPort"]
        base = "http://127.0.0.1:" + port

        def api(method: str, path: str, data: dict | None = None) -> dict:
            body = None if data is None else json.dumps(data).encode()
            request = urllib.request.Request(base + path, data=body, method=method,
                                             headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=5) as response:
                result = json.load(response)
            if result.get("status") != "ok":
                raise RuntimeError("Qdrant API did not acknowledge the operation")
            return result["result"]

        deadline = time.monotonic() + 60
        while True:
            try:
                with urllib.request.urlopen(base + "/readyz", timeout=2) as response:
                    if response.status == 200:
                        break
            except (OSError, urllib.error.URLError):
                if time.monotonic() >= deadline:
                    raise RuntimeError("Isolated vector image did not become ready") from None
                time.sleep(0.25)
        for package in ("apt", "libapt-pkg7.0"):
            version = docker("exec", name, "dpkg-query", "-W", "-f=${Version}", package)
            docker("exec", name, "dpkg", "--compare-versions", version, "ge", "3.0.4")
            print(f"{package}: {version} (CVE-2026-109518 fixed)")
        api("PUT", "/collections/image_check", {"vectors": {"size": 3, "distance": "Cosine"}})
        api("PUT", "/collections/image_check/points?wait=true", {"points": [
            {"id": 1, "vector": [1, 0, 0], "payload": {"check": "isolated"}},
        ]})
        points = api("POST", "/collections/image_check/points/query", {
            "query": [1, 0, 0], "limit": 1, "with_payload": True,
        })["points"]
        if len(points) != 1 or points[0]["id"] != 1 or points[0]["payload"] != {"check": "isolated"}:
            raise RuntimeError("Vector write/query round trip failed")
        api("DELETE", "/collections/image_check")
        if api("GET", "/collections")["collections"]:
            raise RuntimeError("Isolated collection deletion failed")
        try:
            urllib.request.urlopen(base + "/dashboard/index.html", timeout=5).close()
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
        else:
            raise RuntimeError("Upstream dashboard must remain disabled")
        print("Vector image: binary unchanged, non-root, ready, write/query/delete and dashboard isolation passed")
    finally:
        subprocess.run(["docker", "rm", "--force", "--volumes", name], capture_output=True, check=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="mneme-qdrant:1.20.0")
    parser.add_argument("--upstream", default="qdrant/qdrant:v1.20.0@sha256:9bfc89f9914fc14876a88c05270685921a55b8877b254a98bcc1cc2f0a424cd2")
    args = parser.parse_args()
    verify(args.image, args.upstream)
