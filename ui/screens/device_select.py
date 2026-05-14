# ui/screens/device_select.py
import curses
from ..colors import attr, CP_TITLE, CP_HIGHLIGHT, CP_WARNING, CP_DIM, CP_DANGER, CP_BORDER, CP_NORMAL


def screen_device_select(stdscr, devices: list, scan_errors: list) -> str:
    """
    Display all detected devices in a scrollable list.
    User uses arrow keys to select, Enter to confirm.

    Returns:
        "selected:N"  — user selected device index N
        "quit"        — user pressed Q
        "refresh"     — user pressed R (rescan)
    """
    selected_idx = 0
    scroll_offset = 0

    while True:
        stdscr.clear()
        h, w = stdscr.getmaxyx()

        # ── Header ───────────────────────────────────────────────────────
        title = " ZeroTrace — Select Device to Sanitize "
        stdscr.addstr(0, 0, title.center(w), attr(CP_TITLE, bold=True))
        stdscr.addstr(1, 0, f" Detected {len(devices)} device(s)  |  ↑↓ Navigate  |  Enter Select  |  R Rescan  |  Q Quit", attr(CP_DIM))

        # ── Scan errors ───────────────────────────────────────────────────
        row = 2
        for err in scan_errors:
            if row >= h - 4:
                break
            stdscr.addstr(row, 2, f"⚠  {err[:w-4]}", attr(CP_WARNING))
            row += 1

        if not devices:
            stdscr.addstr(row + 2, w // 2 - 15, "No devices detected.", attr(CP_WARNING, bold=True))
            stdscr.addstr(row + 3, w // 2 - 20, "Press R to rescan or Q to quit.", attr(CP_DIM))
            stdscr.refresh()
            key = stdscr.getch()
            if key == ord('q') or key == ord('Q'):
                return "quit"
            if key == ord('r') or key == ord('R'):
                return "refresh"
            continue

        # ── Device list ───────────────────────────────────────────────────
        list_start_row = row + 1
        visible_rows = h - list_start_row - 4  # Leave room for footer

        # Adjust scroll
        if selected_idx < scroll_offset:
            scroll_offset = selected_idx
        elif selected_idx >= scroll_offset + visible_rows:
            scroll_offset = selected_idx - visible_rows + 1

        for i in range(visible_rows):
            dev_idx = i + scroll_offset
            if dev_idx >= len(devices):
                break
            dev = devices[dev_idx]
            row_y = list_start_row + i

            is_selected = (dev_idx == selected_idx)
            style = attr(CP_HIGHLIGHT, bold=True) if is_selected else attr(CP_NORMAL)

            # Build row string
            prefix = "► " if is_selected else "  "
            android_tag = "[ANDROID] " if dev.is_android else ""
            warn_tag = " ⚠" if dev.warnings else ""

            line = f"{prefix}{android_tag}{dev.display_name}"
            # Right-align type + size
            right_part = f"{dev.display_type}  {dev.display_size}  {dev.display_health}{warn_tag}"
            padding = max(0, w - len(line) - len(right_part) - 2)
            full_line = f"{line}{' ' * padding}{right_part}"
            full_line = full_line[:w-1]  # Truncate to terminal width

            stdscr.addstr(row_y, 0, full_line.ljust(w-1), style)

            # Show warnings for selected device
            if is_selected and dev.warnings:
                warn_row = row_y + 1
                for warn in dev.warnings[:2]:  # Max 2 warnings inline
                    if warn_row < h - 3:
                        stdscr.addstr(warn_row, 4, f"  ⚠ {warn[:w-8]}", attr(CP_WARNING))
                        warn_row += 1

        # ── Footer ────────────────────────────────────────────────────────
        footer = " ↑↓ Navigate | Enter: Select | R: Rescan | Q: Quit "
        stdscr.addstr(h - 2, 0, footer.center(w), attr(CP_DIM))

        if scroll_offset > 0:
            stdscr.addstr(list_start_row - 1, w - 6, "▲ more", attr(CP_DIM))
        if scroll_offset + visible_rows < len(devices):
            stdscr.addstr(h - 3, w - 6, "▼ more", attr(CP_DIM))

        stdscr.refresh()

        # ── Input handling ────────────────────────────────────────────────
        key = stdscr.getch()

        if key == curses.KEY_UP:
            selected_idx = max(0, selected_idx - 1)
        elif key == curses.KEY_DOWN:
            selected_idx = min(len(devices) - 1, selected_idx + 1)
        elif key == ord('\n') or key == curses.KEY_ENTER:
            return f"selected:{selected_idx}"
        elif key == ord('q') or key == ord('Q'):
            return "quit"
        elif key == ord('r') or key == ord('R'):
            return "refresh"
