"""Arrow-key multi-select used by `python -m hunt ai consent`; the terminal is always faked."""
import contextlib
import curses
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hunt import menu
from hunt.__main__ import main
from hunt.core import Store

ITEMS = ['脱敏简历（resume_redacted）', '完整简历（resume_full）', '岗位原文（job_text）']
DOWN, UP, SPACE, ENTER, ESC = curses.KEY_DOWN, curses.KEY_UP, ord(' '), 10, 27


def press(*keys, size=3):
    state = menu.start(size)
    for key in keys:
        state = menu.step(state, key)
    return state


class StepTests(unittest.TestCase):
    def test_moves_without_leaving_the_list(self):
        self.assertEqual(press(UP)['pos'], 0)
        self.assertEqual(press(DOWN, DOWN, DOWN, DOWN)['pos'], 2)
        self.assertEqual(press(DOWN, ord('k'))['pos'], 0)
        self.assertEqual(press(ord('j'), ord('j'))['pos'], 2)

    def test_space_toggles_the_current_item(self):
        self.assertEqual(press(SPACE, DOWN, DOWN, SPACE)['checked'], {0, 2})
        self.assertEqual(press(SPACE, SPACE)['checked'], set())

    def test_enter_needs_at_least_one_item(self):
        state = press(ENTER)
        self.assertIsNone(state['done'])
        self.assertTrue(state['hint'])
        self.assertEqual(press(DOWN, SPACE, ENTER)['done'], [1])
        self.assertEqual(press(SPACE, DOWN, DOWN, SPACE, curses.KEY_ENTER)['done'], [0, 2])

    def test_escape_or_q_cancels(self):
        self.assertTrue(press(SPACE, ESC)['cancelled'])
        self.assertTrue(press(ord('q'))['cancelled'])


class FakeScreen:
    def __init__(self, keys, width=80):
        self.keys, self.width, self.drawn = list(keys), width, []

    def keypad(self, flag): pass
    def erase(self): self.drawn.append([])
    def refresh(self): pass
    def getmaxyx(self): return 24, self.width

    def addstr(self, y, x, text, attr=0):
        self.drawn[-1].append(text)

    def getch(self):
        return self.keys.pop(0)


class LoopTests(unittest.TestCase):
    def test_loop_draws_marks_and_returns_the_choice(self):
        screen = FakeScreen([DOWN, DOWN, SPACE, ENTER])
        with patch.object(menu.curses, 'curs_set', side_effect=curses.error):  # some terminals cannot hide the cursor
            self.assertEqual(menu.run(screen, '选择内容', ITEMS), [2])
        last = screen.drawn[-1]
        self.assertIn('选择内容', last[0])
        self.assertTrue(any('[x]' in line and 'job_text' in line for line in last))
        self.assertTrue(any('空格' in line for line in last))

    def test_loop_returns_none_when_cancelled(self):
        self.assertIsNone(menu.run(FakeScreen([SPACE, ESC]), '选择内容', ITEMS))

    def test_pick_reports_unavailable_when_curses_cannot_start(self):
        with patch.object(menu.curses, 'wrapper', side_effect=curses.error('setupterm: could not find terminal')):
            with self.assertRaises(menu.Unavailable):
                menu.pick('选择内容', ITEMS)


class ConsentMenuTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.data = Path(temp.name) / 'data'

    def run_tty(self, typed, picker):
        class TTY(io.StringIO):
            def isatty(self): return True
        out = TTY()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()), patch('sys.stdin', TTY(typed)), \
                patch.object(menu, 'pick', picker) as pick:
            code = main(['ai', 'consent', '--data', str(self.data)])
        return code, out.getvalue(), pick

    def consent(self):
        return Store(self.data).ai_settings()['consent']

    def test_terminal_uses_the_menu(self):
        code, out, pick = self.run_tty('yes\n', lambda title, items: [0, 2])
        self.assertEqual(code, 0)
        self.assertEqual(self.consent()['kinds'], ['resume_redacted', 'job_text'])
        self.assertIn('api.deepseek.com', out)

    def test_cancelling_the_menu_changes_nothing(self):
        code, out, pick = self.run_tty('', lambda title, items: None)
        self.assertEqual(code, 1)
        self.assertIsNone(self.consent())

    def test_unsupported_terminal_falls_back_to_numbers(self):
        def unavailable(title, items): raise menu.Unavailable('no terminal')
        code, out, pick = self.run_tty('3\nyes\n', unavailable)
        self.assertEqual(code, 0)
        self.assertEqual(self.consent()['kinds'], ['job_text'])
        self.assertIn('1. 脱敏简历', out)

    def test_menu_is_skipped_when_output_is_not_a_terminal(self):
        class TTY(io.StringIO):
            def isatty(self): return True
        with contextlib.redirect_stdout(io.StringIO()), patch('sys.stdin', TTY('3\nyes\n')), \
                patch.object(menu, 'pick', side_effect=AssertionError('menu must not start')):
            self.assertEqual(main(['ai', 'consent', '--data', str(self.data)]), 0)
        self.assertEqual(self.consent()['kinds'], ['job_text'])


if __name__ == '__main__':
    unittest.main()
