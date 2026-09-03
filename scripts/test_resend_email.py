#!/usr/bin/env python3
"""Send one explicit test email through Resend without exposing the API key."""

from __future__ import annotations

import argparse
import json
import sys
from email.utils import parseaddr
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _email_address(value: str, option: str) -> str:
    address = parseaddr(value)[1].strip()
    if "@" not in address or address.startswith("@") or address.endswith("@"):
        raise argparse.ArgumentTypeError(f"{option} must be an email address.")
    return value.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Send one test email through Resend.")
    parser.add_argument(
        "--key-file",
        default=".resend-dev-key",
        help="File containing only the Resend API key (default: .resend-dev-key).",
    )
    parser.add_argument("--to", required=True, type=lambda value: _email_address(value, "--to"))
    parser.add_argument(
        "--from",
        dest="sender",
        required=True,
        type=lambda value: _email_address(value, "--from"),
    )
    parser.add_argument(
        "--api-url",
        default="https://api.resend.com/emails",
        help="Resend email endpoint.",
    )
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()

    try:
        with open(args.key_file, encoding="utf-8") as key_file:
            api_key = key_file.read().strip()
    except OSError as error:
        print(f"Could not read key file: {error}", file=sys.stderr)
        return 2

    if not api_key.startswith("re_") or any(character.isspace() for character in api_key):
        print("The key file must contain one Resend API key beginning with re_.", file=sys.stderr)
        return 2

    payload = json.dumps(
        {
            "from": args.sender,
            "to": [args.to],
            "subject": "Take the Board Resend test",
            "text": "This is a one-off delivery test for Take the Board. No customer data is included.",
            "html": "<p>This is a one-off delivery test for Take the Board.</p><p>No customer data is included.</p>",
        }
    ).encode("utf-8")
    request = Request(
        args.api_url,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "take-the-board-resend-test/1.0",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=args.timeout) as response:
            response_data = json.loads(response.read(4096).decode("utf-8"))
            provider_message_id = str(response_data.get("id") or "")
            if not 200 <= response.status < 300 or not provider_message_id:
                print("Resend returned an unexpected response.", file=sys.stderr)
                return 1
    except HTTPError as error:
        print(f"Resend rejected the request: HTTP {error.code}.", file=sys.stderr)
        return 1
    except (URLError, TimeoutError, OSError, UnicodeDecodeError, ValueError, TypeError):
        print("Could not complete the Resend request.", file=sys.stderr)
        return 1

    print(f"Resend accepted the test email: provider_id={provider_message_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
