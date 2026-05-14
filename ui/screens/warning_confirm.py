# ui/screens/warning_confirm.py
import curses
from ..colors import attr, CP_TITLE, CP_DANGER, CP_WARNING, CP_DIM, CP_NORMAL


def screen_warning_confirm(stdscr, device, mode: str) -> str:
    """
    Final confirmation before destructive wipe.
    User must type CONFIRM exactly. No shortcuts.
    """
    confirm_text = "CONFIRM"
    typed = []

    while True:
        stdscr.clear()
        h, w = stdscr.getmaxyx()

        # Header
        stdscr.addstr(0, 0, " ⚠  ZeroTrace — FINAL WARNING ".center(w), attr(CP_DANGER, bold=True))

        row = 2
        stdscr.addstr(row, 2, "The following operation is IRREVERSIBLE.", attr(CP_DANGER, bold=True))
        row += 1
        stdscr.addstr(row, 2, "All data on the selected device will be permanently destroyed.", attr(CP_NORMAL))
        row += 2

        dev_name = device.display_name if device else "Unknown Device"
        stdscr.addstr(row, 2, f"Device:      {dev_name}", attr(CP_NORMAL))
        row += 1
        stdscr.addstr(row, 2, f"Type:        {device.display_type}", attr(CP_NORMAL))
        row += 1
        stdscr.addstr(row, 2, f"Size:        {device.display_size}", attr(CP_NORMAL))
        row += 1
        stdscr.addstr(row, 2, f"Wipe Mode:   {mode}", attr(CP_DANGER, bold=True))
        row += 2

        # Android-specific warnings
        if device.is_android:
            info = device.android_device
            if not info.is_rooted:
                stdscr.addstr(row, 2, "⚠  Non-root: Coverage limited to factory reset level.", attr(CP_WARNING))
                row += 1
            if info.tee_backed_keys:
                stdscr.addstr(row, 2, "⚠  TEE-backed keys will be evicted via metadata wipe / recovery.", attr(CP_WARNING))
                row += 1
        else:
            if device.pc_device and device.pc_device.is_ssd and mode == "CLEAR":
                stdscr.addstr(row, 2, "⚠  Zero-overwrite on SSD does NOT cover wear-leveled blocks.", attr(CP_WARNING))
                row += 1
                stdscr.addstr(row, 2, "   Consider PURGE mode for complete SSD sanitization.", attr(CP_WARNING))
                row += 1

        row += 1
        stdscr.addstr(row, 2, f"Type  '{confirm_text}'  and press Enter to proceed:", attr(CP_NORMAL))
        row += 1

        # Display typed text
        typed_str = ''.join(typed)
        display_field = f"  > {typed_str}_"
        field_style = attr(CP_DANGER, bold=True) if typed_str == confirm_text else attr(CP_NORMAL)
        stdscr.addstr(row, 2, display_field, field_style)
        row += 2

        stdscr.addstr(row, 2, "Press Escape or B to go back.", attr(CP_DIM))

        stdscr.addstr(h - 2, 0, " Type CONFIRM to proceed | Esc: Cancel ".center(w), attr(CP_DIM))
        stdscr.refresh()

        key = stdscr.getch()

        if key == 27:  # Escape
            return "back"
        elif key == ord('b') or key == ord('B'):
            if not typed:  # Only go back if field is empty
                return "back"
            else:
                typed = []
        elif key == curses.KEY_BACKSPACE or key == 127:
            if typed:
                typed.pop()
        elif key == ord('\n') or key == curses.KEY_ENTER:
            if ''.join(typed) == confirm_text:
                return "next"
            else:
                # Flash the field red — wrong text
                stdscr.addstr(row - 2, 2, "  > INCORRECT — type CONFIRM exactly", attr(CP_DANGER, bold=True))
                stdscr.refresh()
                curses.napms(1000)
                typed = []
        elif 32 <= key <= 126:  # Printable ASCII
            if len(typed) < len(confirm_text) + 2:  # Don't let user type forever
                typed.append(chr(key))
