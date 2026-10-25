"""Print the size of each bookmarklet's javascript: URL, and fail when one is too large for a browser bookmark.

The real URLs, with the port and token filled in, are produced only when the install page is rendered
(GET /bookmarklets); this script never sees a token and writes nothing to the repository."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hunt import bookmarklets

LIMIT = 64 * 1024


def main():
    failed = False
    for name, _, _ in bookmarklets.ITEMS:
        size = len(bookmarklets.build(name))
        failed = failed or size >= LIMIT
        print('%-12s %6.1f KB%s' % (name, size / 1024, '  too large' if size >= LIMIT else ''))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
