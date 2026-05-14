# ui/wizard.py
#
# The wizard controls the flow between screens.
# Each screen is a function that takes (stdscr, orchestrator) and returns
# either the name of the next screen or None (exit).
#
# Screen flow:
#   splash → device_select → health_report → mode_select → warning_confirm
#   → progress → entropy_result → certificate_export → valuation → done

import curses
import time
from .colors import init_colors
from .orchestrator import Orchestrator
from .screens.splash import screen_splash
from .screens.device_select import screen_device_select
from .screens.health_report import screen_health_report
from .screens.mode_select import screen_mode_select
from .screens.warning_confirm import screen_warning_confirm
from .screens.progress import screen_progress
from .screens.entropy_result import screen_entropy_result
from .screens.certificate_export import screen_certificate_export


def run_wizard(stdscr):
    """
    Main wizard entry point.
    Called by curses.wrapper() in main.py.
    """
    # Setup
    curses.curs_set(0)      # Hide cursor
    stdscr.nodelay(False)   # Blocking getch()
    init_colors()

    orchestrator = Orchestrator()

    # ── Screen flow ──────────────────────────────────────────────────────
    # Each screen returns a string telling the wizard what to do next:
    #   "next"    → proceed to next screen
    #   "back"    → go back one screen
    #   "quit"    → exit ZeroTrace
    #   "restart" → restart from device_select

    screen_order = [
        "splash",
        "device_select",
        "health_report",
        "mode_select",
        "warning_confirm",
        "progress",
        "entropy_result",
        "certificate_export",
        "done"
    ]

    current_screen_idx = 0
    session = None

    while True:
        screen_name = screen_order[current_screen_idx]

        if screen_name == "splash":
            action = screen_splash(stdscr)

        elif screen_name == "device_select":
            devices = orchestrator.scan_all_devices()
            action = screen_device_select(stdscr, devices, orchestrator.scan_errors)
            if action and action.startswith("selected:"):
                idx = int(action.split(":")[1])
                orchestrator.select_device(idx)
                action = "next"

        elif screen_name == "health_report":
            device = orchestrator.selected_device
            action = screen_health_report(stdscr, device)

        elif screen_name == "mode_select":
            modes = orchestrator.get_available_modes()
            action = screen_mode_select(stdscr, modes, orchestrator.selected_device)
            if action and action.startswith("mode:"):
                mode = action.split(":")[1]
                orchestrator.select_wipe_mode(mode)
                action = "next"

        elif screen_name == "warning_confirm":
            action = screen_warning_confirm(
                stdscr,
                device=orchestrator.selected_device,
                mode=orchestrator.selected_mode
            )

        elif screen_name == "progress":
            # This screen runs the actual wipe — it's special
            def make_progress_cb(s):
                """Closure to update the progress screen."""
                # This gets set by screen_progress before calling execute_wipe
                pass

            session = screen_progress(stdscr, orchestrator)
            action = "next"

        elif screen_name == "entropy_result":
            if session:
                entropy = orchestrator.run_entropy_check(session)
                valuation = orchestrator.compute_valuation(session)
            action = screen_entropy_result(stdscr, session)

        elif screen_name == "certificate_export":
            action = screen_certificate_export(stdscr, session, orchestrator)

        elif screen_name == "done":
            # Final screen — ask if user wants to wipe another device
            action = _screen_done(stdscr)
            if action == "restart":
                current_screen_idx = screen_order.index("device_select")
                orchestrator = Orchestrator()  # Fresh orchestrator
                session = None
                continue

        else:
            break

        # ── Handle actions ───────────────────────────────────────────────

        if action == "quit" or action is None:
            break
        elif action == "next":
            current_screen_idx = min(current_screen_idx + 1, len(screen_order) - 1)
        elif action == "back":
            current_screen_idx = max(current_screen_idx - 1, 1)  # Can't go before device_select
        elif action == "restart":
            current_screen_idx = screen_order.index("device_select")
            orchestrator = Orchestrator()
            session = None
        # Other action strings already handled above before setting action = "next"


def _screen_done(stdscr) -> str:
    stdscr.clear()
    h, w = stdscr.getmaxyx()
    msg = "Wipe operation complete. Wipe another device? (y/n)"
    stdscr.addstr(h // 2, max(0, w // 2 - len(msg) // 2), msg)
    stdscr.refresh()
    key = stdscr.getch()
    if key == ord('y') or key == ord('Y'):
        return "restart"
    return "quit"
