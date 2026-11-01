"""python -m hunt: the local CLI lives in hunt.app.cli."""
from .app.cli import main

if __name__ == '__main__':
    raise SystemExit(main())
