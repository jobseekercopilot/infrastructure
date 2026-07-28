#!/usr/bin/env python3
"""Inspect the ephemeral LocalStack account-email mailbox without leaking reset tokens."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
import webbrowser
from urllib.parse import urlsplit


CAPTURE_URL = "http://127.0.0.1:4566/_aws/ses"
TOKEN = r"[A-Za-z0-9_-]{32,128}"
RESET_LINK = re.compile(
    rf"https?://[^\s\"'<>]+/reset-password#token={TOKEN}"
)
TOKEN_VALUE = re.compile(rf"(?<=#token=){TOKEN}")


def _request(method: str = "GET") -> dict:
    request = urllib.request.Request(CAPTURE_URL, method=method)
    with urllib.request.urlopen(request, timeout=5) as response:
        if method == "DELETE":
            return {}
        return json.loads(response.read().decode("utf-8"))


def _messages() -> list[dict]:
    payload = _request()
    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise ValueError("LocalStack returned an unexpected account-email response.")
    return messages


def _message_id(message: dict) -> str:
    value = message.get("Id")
    if not isinstance(value, str) or not value:
        raise ValueError("A local test email is missing its message ID.")
    return value


def _recipient(message: dict) -> str:
    destination = message.get("Destination")
    addresses = destination.get("ToAddresses") if isinstance(destination, dict) else None
    if not isinstance(addresses, list):
        return "(unknown recipient)"
    return ", ".join(str(address) for address in addresses)


def _find(message_id: str) -> dict:
    for message in _messages():
        if _message_id(message) == message_id:
            return message
    raise ValueError(f"No local test email has message ID {message_id}.")


def _body(message: dict, part: str) -> str:
    body = message.get("Body")
    value = body.get(part) if isinstance(body, dict) else None
    return value if isinstance(value, str) else ""


def _redact_tokens(value: str) -> str:
    return TOKEN_VALUE.sub("[REDACTED]", value)


def _reset_link(message: dict) -> str:
    content = f"{_body(message, 'text_part')}\n{_body(message, 'html_part')}"
    match = RESET_LINK.search(content)
    if not match:
        raise ValueError("This local test email does not contain a password-reset link.")
    link = match.group(0)
    parsed = urlsplit(link)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.port != 3000
        or parsed.path != "/reset-password"
        or parsed.query
        or not re.fullmatch(rf"token={TOKEN}", parsed.fragment)
    ):
        raise ValueError("The captured reset link is outside the local application boundary.")
    return link


def list_messages() -> None:
    messages = _messages()
    print("LOCAL TEST EMAIL — LocalStack SES mailbox")
    if not messages:
        print("No captured account emails.")
        return
    for message in sorted(messages, key=lambda item: str(item.get("Timestamp", ""))):
        print(
            f"{_message_id(message)}  "
            f"{_recipient(message)}  "
            f"{message.get('Subject', '(no subject)')}"
        )


def show_message(message_id: str) -> None:
    message = _find(message_id)
    print("LOCAL TEST EMAIL — reset tokens are redacted")
    print(f"ID: {_message_id(message)}")
    print(f"To: {_recipient(message)}")
    print(f"Subject: {message.get('Subject', '(no subject)')}")
    print()
    print(_redact_tokens(_body(message, "text_part")))


def open_message(message_id: str) -> None:
    link = _reset_link(_find(message_id))
    if not webbrowser.open(link, new=2):
        raise ValueError(
            "The local reset link was valid, but no graphical browser accepted it."
        )
    print("Opened the local password-reset link without printing its token.")


def clear_messages() -> None:
    _request("DELETE")
    print("Cleared the LOCAL TEST EMAIL mailbox.")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Inspect account email captured by the full-local-ses profile."
    )
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="List message IDs, recipients and subjects.")
    show = commands.add_parser("show", help="Show text content with reset tokens redacted.")
    show.add_argument("message_id")
    open_link = commands.add_parser(
        "open", help="Open a bounded local reset link without printing its token."
    )
    open_link.add_argument("message_id")
    commands.add_parser("clear", help="Clear the ephemeral local mailbox.")
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "list":
            list_messages()
        elif args.command == "show":
            show_message(args.message_id)
        elif args.command == "open":
            open_message(args.message_id)
        elif args.command == "clear":
            clear_messages()
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as error:
        print(
            "Local account-email helper failed. "
            "Confirm full-local-ses is healthy and try again. "
            f"Reason: {error}",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
