#!/usr/bin/env python3
"""Launch, recover and operate auto-hunt-job locally."""
import argparse
import json
import os
import threading
from pathlib import Path
from hunt.core import Store


def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser(description='auto-hunt-job 本地求职助手')
    parser.add_argument('--data',default=str(Path(__file__).resolve().parent/'private'/'app'))
    parser.add_argument('--port',type=int,default=8766)
    parser.add_argument('--once',action='store_true',help='真实公开岗位发现并准备一轮')
    parser.add_argument('--demo',action='store_true',help='离线合成夹具，写入单独 demo 数据目录')
    parser.add_argument('--periodic',action='store_true',help='服务运行期间按配置间隔自动准备')
    parser.add_argument('--login',action='store_true',help='打开独立安克浏览器供用户自行登录，不填写申请')
    parser.add_argument('--browser-plan',help='已登录浏览器执行计划 JSON；须逐岗快照批准')
    args=parser.parse_args()
    data=Path(args.data)
    if args.demo: data=data/'demo'
    # An OS advisory lock prevents another process from misclassifying live intents as crashes.
    import fcntl
    data.mkdir(parents=True,exist_ok=True,mode=0o700)
    lock=(data/'runner.lock').open('a+')
    try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError: parser.error('该数据目录已有运行器；请使用现有窗口或不同 --data')
    executor=None
    if args.login:
        from hunt.execution import BrowserExecutor
        BrowserExecutor(Path(args.browser_plan or data/'plan.json'),data).login()
        return
    if args.browser_plan:
        from hunt.execution import BrowserExecutor
        executor=BrowserExecutor(Path(args.browser_plan),data)
    store=Store(data,executor=executor)
    store.recover()
    if args.once or args.demo:
        print(json.dumps(store.run(demo=args.demo),ensure_ascii=False,indent=2))
        if args.once: return
    from hunt.server import make_server,periodic
    server=make_server(store,args.port)
    stop=threading.Event()
    if args.periodic:
        threading.Thread(target=periodic,args=(store,stop),daemon=True).start()
    print('auto-hunt-job: http://127.0.0.1:%s'%server.server_port,flush=True)
    print('数据目录: '+str(data.resolve())+'；真实提交默认额度 0；无外部模型调用',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: stop.set();server.server_close()


if __name__=='__main__': main()
