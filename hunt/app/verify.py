"""python -m hunt verify: read-only Moka entry check after the user signs in; never fills, uploads or applies."""
import argparse
import json
import threading
from pathlib import Path

from ..core import Store
from ..moka_session import MokaVerifier
from ..sources import SourceError


def main():
    parser = argparse.ArgumentParser(description='Moka 本人登录后的只读入口核验；不填写、不上传、不投递')
    parser.add_argument('--data', type=Path, default=Path('private/app'))
    parser.add_argument('--job', required=True, help='工作台岗位 ID')
    parser.add_argument('--headless', action='store_true', help='只读已有独立会话，不等待登录')
    args = parser.parse_args()
    store = Store(args.data)
    with store.tx() as c: job = store.job(c, args.job)
    try:
        with MokaVerifier(store.root / 'browser-entry', job, headless=args.headless) as browser:
            if args.headless: result = browser.open()
            else:
                finish, cancel = threading.Event(), threading.Event()
                def progress(status, message, check):
                    print(message, flush=True)
                    if status == 'awaiting_login':
                        def wait():
                            try: input('完成登录后按回车核验；Ctrl+C 结束：'); finish.set()
                            except (EOFError, OSError): cancel.set()
                        threading.Thread(target=wait, daemon=True).start()
                result = browser.run(finish, cancel, progress)
        store.save_entry_check(job, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (SourceError, KeyboardInterrupt) as error:
        print(json.dumps(dict(status=getattr(error, 'status', 'cancelled'), error=str(error)), ensure_ascii=False))
        raise SystemExit(1)


if __name__ == '__main__': main()
