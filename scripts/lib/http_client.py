#!/usr/bin/env python3
import json
import urllib.error
import urllib.parse
import urllib.request


class HttpError(RuntimeError):
    pass


def get_json(url, timeout=10):
    return request_json("GET", url, timeout=timeout)


def post_json(url, payload, timeout=10):
    return request_json("POST", url, payload=payload, timeout=timeout)


def request_json(method, url, payload=None, timeout=10):
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else None
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise HttpError(f"{method} {url} failed with HTTP {error.code}: {body}") from error
    except urllib.error.URLError as error:
        raise HttpError(f"{method} {url} failed: {error.reason}") from error


def query(base_url, path, params):
    encoded = urllib.parse.urlencode({key: value for key, value in params.items() if value is not None})
    return f"{base_url.rstrip('/')}{path}?{encoded}" if encoded else f"{base_url.rstrip('/')}{path}"
