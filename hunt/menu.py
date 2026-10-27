"""Terminal multi-select: arrow keys (or j/k) move, space ticks, enter confirms, Esc or q cancels.

Standard-library curses only. step() holds all the key logic and needs no terminal, so it is tested directly;
pick() raises Unavailable when curses cannot start, and callers fall back to typed numbers.
"""
import curses
import locale

HINT = '↑↓ 移动　空格 勾选　回车 确认　Esc 取消'
ENTERS = (10, 13, curses.KEY_ENTER)


class Unavailable(Exception):
    pass


def start(size):
    return dict(size=size, pos=0, checked=set(), done=None, cancelled=False, hint=False)


def step(state, key):
    """The state after one key press; `done` is the ticked indices in list order, `cancelled` ends without a choice."""
    s = dict(state, checked=set(state['checked']), hint=False)
    if key in (curses.KEY_UP, ord('k')): s['pos'] = max(0, s['pos'] - 1)
    elif key in (curses.KEY_DOWN, ord('j')): s['pos'] = min(s['size'] - 1, s['pos'] + 1)
    elif key == ord(' '): s['checked'] ^= {s['pos']}
    elif key in ENTERS:
        if s['checked']: s['done'] = sorted(s['checked'])
        else: s['hint'] = True  # enter with nothing ticked: say so instead of confirming an empty choice
    elif key in (27, ord('q')): s['cancelled'] = True
    return s


def run(screen, title, items):
    """Draw and read keys on a curses screen until confirmed (list of indices) or cancelled (None)."""
    try: curses.curs_set(0)
    except curses.error: pass  # some terminals cannot hide the cursor
    screen.keypad(True)
    state = start(len(items))
    while True:
        width = screen.getmaxyx()[1] - 1
        screen.erase()
        screen.addstr(0, 0, title[:width])
        for n, item in enumerate(items):
            line = '%s [%s] %s' % ('>' if n == state['pos'] else ' ', 'x' if n in state['checked'] else ' ', item)
            screen.addstr(n + 2, 0, line[:width], curses.A_REVERSE if n == state['pos'] else 0)
        screen.addstr(len(items) + 3, 0, ('请至少勾选一项　' if state['hint'] else '') + HINT[:width])
        screen.refresh()
        state = step(state, screen.getch())
        if state['done'] is not None: return state['done']
        if state['cancelled']: return None


def pick(title, items):
    locale.setlocale(locale.LC_ALL, '')  # curses needs the user's locale to draw Chinese
    try:
        return curses.wrapper(run, title, items)
    except curses.error as e:
        raise Unavailable(str(e)) from None
