"""Rotate user model credentials through the authenticated transactional admin API.

Keys are supplied to the gateway by the deployment's secret manager, never CLI args.
Default: inspect only. --apply requires an explicit expected active version.
"""
import argparse
import getpass
import http.cookiejar
import json
import urllib.error
import urllib.parse
import urllib.request


class RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("Redirect refused; use the final trusted gateway URL")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:3000")
    parser.add_argument("--username", required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    origin = urllib.parse.urlsplit(args.url)
    if (origin.scheme != "https" and not (origin.scheme == "http" and origin.hostname in {"localhost", "127.0.0.1", "::1"})) or origin.username or origin.query or origin.fragment:
        parser.error("Use HTTPS or a loopback address without embedded credentials")
    opener = urllib.request.build_opener(RejectRedirects(), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def call(path, body=None, token=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Admin-Token"] = token
        request = urllib.request.Request(args.url.rstrip("/") + "/api/v1/" + path,
            data=None if body is None else json.dumps(body).encode(), headers=headers)
        try:
            with opener.open(request, timeout=120) as response:
                result = json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"Operation rejected (HTTP {error.code}); inspect administrator status; no keys were printed") from None
        if result.get("code", 200) != 200:
            raise RuntimeError("Operation rejected; inspect administrator status")
        return result.get("data", result)
    call("auth/login", {"username": args.username, "password": getpass.getpass("Account password: ")})
    token = getpass.getpass("Temporary administrator token: ")
    status = call("admin/operations", token=token)["model_keys"]
    print(json.dumps(status, ensure_ascii=False))
    if args.expected_version != status["active_version"]:
        raise RuntimeError("Active version changed; deployment must be reviewed before rotation")
    if args.apply:
        print(json.dumps(call("admin/model-keys/rotate", {"expected_version": args.expected_version}, token), ensure_ascii=False))


if __name__ == "__main__":
    main()
