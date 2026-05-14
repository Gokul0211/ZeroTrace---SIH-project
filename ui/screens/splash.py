# ui/screens/splash.py
import curses
import time
from ..colors import attr, CP_TITLE, CP_DIM, CP_WARNING, CP_SUCCESS


LOGO = [
    "  ███████╗███████╗██████╗  ██████╗ ████████╗██████╗  █████╗  ██████╗███████╗",
    "  ╚══███╔╝██╔════╝██╔══██╗██╔═══██╗╚══██╔══╝██╔══██╗██╔══██╗██╔════╝██╔════╝",
    "    ███╔╝ █████╗  ██████╔╝██║   ██║   ██║   ██████╔╝███████║██║     █████╗  ",
    "   ███╔╝  ██╔══╝  ██╔══██╗██║   ██║   ██║   ██╔══██╗██╔══██║██║     ██╔══╝  ",
    "  ███████╗███████╗██║  ██║╚██████╔╝   ██║   ██║  ██║██║  ██║╚██████╗███████╗",
    "  ╚══════╝╚══════╝╚═╝  ╚═╝ ╚═════╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚══════╝",
]


def screen_splash(stdscr) -> str:
    stdscr.clear()
    h, w = stdscr.getmaxyx()

    # Center the logo
    logo_start_row = max(1, h // 2 - len(LOGO) // 2 - 4)
    for i, line in enumerate(LOGO):
        x = max(0, w // 2 - len(line) // 2)
        try:
            stdscr.addstr(logo_start_row + i, x, line, attr(CP_TITLE, bold=True))
        except curses.error:
            pass

    row = logo_start_row + len(LOGO) + 1
    subtitle = "Secure Data Sanitization for Trustworthy IT Asset Recycling"
    stdscr.addstr(row, max(0, w // 2 - len(subtitle) // 2), subtitle, attr(CP_DIM))
    row += 1

    nist = "NIST SP 800-88 Rev.1 Compliant  |  HDD · SSD · NVMe · Android"
    stdscr.addstr(row, max(0, w // 2 - len(nist) // 2), nist, attr(CP_SUCCESS))
    row += 2

    warning = "⚠  Run as root. Do not remove the USB drive during operation."
    stdscr.addstr(row, max(0, w // 2 - len(warning) // 2), warning, attr(CP_WARNING))
    row += 2

    start = "Press any key to begin..."
    stdscr.addstr(row, max(0, w // 2 - len(start) // 2), start, attr(CP_DIM))

    stdscr.refresh()
    stdscr.getch()
    return "next"
