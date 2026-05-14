# ui/screens/mode_select.py
import curses
from ..colors import attr, CP_TITLE, CP_HIGHLIGHT, CP_WARNING, CP_DIM, CP_SUCCESS, CP_DANGER, CP_NORMAL


def screen_mode_select(stdscr, modes: list, device) -> str:
    """
    Display wipe mode options. Returns "mode:MODEID" on selection.
    """
    selected_idx = 0
    # Find recommended mode as default
    for i, m in enumerate(modes):
        if m.get("recommended"):
            selected_idx = i
            break

    while True:
        stdscr.clear()
        h, w = stdscr.getmaxyx()

        # Header
        dev_name = device.display_name if device else "Selected Device"
        stdscr.addstr(0, 0, f" ZeroTrace — Select Wipe Mode | {dev_name} ".center(w), attr(CP_TITLE, bold=True))
        stdscr.addstr(1, 0, " ↑↓ Navigate  |  Enter: Select  |  B: Back  |  Q: Quit", attr(CP_DIM))

        row = 3

        for i, mode in enumerate(modes):
            is_sel = (i == selected_idx)
            box_style = attr(CP_HIGHLIGHT, bold=True) if is_sel else attr(CP_NORMAL)

            # Mode name line
            prefix = "► " if is_sel else "  "
            rec_tag = " ✓ RECOMMENDED" if mode.get("recommended") else ""
            name_line = f"{prefix}{mode['name']}{rec_tag}"
            rec_style = attr(CP_SUCCESS, bold=True) if (is_sel and mode.get("recommended")) else box_style
            stdscr.addstr(row, 0, name_line.ljust(w - 1), box_style)
            row += 1

            # Description
            desc = f"    {mode['description']}"
            stdscr.addstr(row, 0, desc[:w-1].ljust(w-1), attr(CP_DIM) if not is_sel else attr(CP_NORMAL))
            row += 1

            # Time estimate
            time_line = f"    ⏱  {mode['time_estimate']}"
            stdscr.addstr(row, 0, time_line[:w-1].ljust(w-1), attr(CP_DIM))
            row += 1

            # Warning if any
            if mode.get("warning"):
                warn = f"    ⚠  {mode['warning']}"
                stdscr.addstr(row, 0, warn[:w-1].ljust(w-1), attr(CP_WARNING))
                row += 1

            row += 1  # Spacing between modes

            if row >= h - 3:
                break

        # Footer
        stdscr.addstr(h - 2, 0, " ↑↓ Navigate | Enter: Select | B: Back | Q: Quit ".center(w), attr(CP_DIM))
        stdscr.refresh()

        key = stdscr.getch()
        if key == curses.KEY_UP:
            selected_idx = max(0, selected_idx - 1)
        elif key == curses.KEY_DOWN:
            selected_idx = min(len(modes) - 1, selected_idx + 1)
        elif key == ord('\n') or key == curses.KEY_ENTER:
            return f"mode:{modes[selected_idx]['id']}"
        elif key == ord('b') or key == ord('B'):
            return "back"
        elif key == ord('q') or key == ord('Q'):
            return "quit"
