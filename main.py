"""
Entry point: build the graph, connect it to the Rich TUI, and run the loop.
"""

import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from order_graph import build_graph
from tui import show_banner, run_order_session, render_footer


def main():
    app = build_graph()
    show_banner()

    keep_going = True
    while keep_going:
        keep_going = run_order_session(app)

    render_footer()


if __name__ == "__main__":
    main()
