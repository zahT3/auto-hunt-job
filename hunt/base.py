"""The few helpers every layer shares: the user-facing error, timestamps and canonical JSON."""
import hashlib
import json
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(dumps(value).encode()).hexdigest()


class Error(Exception):
    pass
