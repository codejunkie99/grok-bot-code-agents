#!/usr/bin/env python3
"""Fire one Claude Code scheduled task; text on stdin, credentials in environment."""
import json
import os
import re
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit


def main():
    url = os.environ.get("CLAUDE_ROUTINE_FIRE_URL", "")
    token = os.environ.get("CLAUDE_ROUTINE_TOKEN", "")
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.netloc != "api.anthropic.com"
            or not re.fullmatch(r"/v1/claude_code/routines/trig_[A-Za-z0-9_-]+/fire", parts.path)
            or parts.query or parts.fragment):
        raise ValueError("CLAUDE_ROUTINE_FIRE_URL must be the exact Anthropic HTTPS fire URL")
    if not token or "\n" in token or "\r" in token:
        raise ValueError("CLAUDE_ROUTINE_TOKEN must contain a valid routine token")
    task = sys.stdin.read(65537)
    if not task.strip() or len(task) > 65536:
        raise ValueError("Provide a nonempty task on stdin, at most 65,536 characters")
    body = json.dumps({"text": task}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": "Bearer " + token,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    })
    # Never redirect a request carrying a bearer token.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(req, timeout=30) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        status = exc.code
        retry_after = exc.headers.get("Retry-After")
        exc.close()
        if status >= 500:
            print(json.dumps({"ok": False, "error": "outcome_unknown", "status": status,
                              "message": "Check Claude for a run before retrying."}), file=sys.stderr)
            return 2
        print(json.dumps({"ok": False, "error": "http_error", "status": status,
                          "retry_after": retry_after}), file=sys.stderr)
        return 1
    except (urllib.error.URLError, TimeoutError, OSError):
        print(json.dumps({"ok": False, "error": "outcome_unknown",
                          "message": "The request may have created a session; check Claude before retrying."}), file=sys.stderr)
        return 2
    except (ValueError, UnicodeError):
        print(json.dumps({"ok": False, "error": "outcome_unknown",
                          "message": "Unrecognized response; check Claude before retrying."}), file=sys.stderr)
        return 2
    sid = result.get("claude_code_session_id") if isinstance(result, dict) else None
    link = result.get("claude_code_session_url") if isinstance(result, dict) else None
    if (not isinstance(sid, str) or not re.fullmatch(r"(?:session|cse)_[A-Za-z0-9_-]+", sid)
            or not isinstance(link, str) or link != "https://claude.ai/code/" + sid):
        print(json.dumps({"ok": False, "error": "outcome_unknown",
                          "message": "Unrecognized response; check Claude before retrying."}), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, "session_id": sid, "url": link,
                      "status": "created", "completion": "unknown"}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": "configuration", "message": str(exc)}), file=sys.stderr)
        sys.exit(1)
