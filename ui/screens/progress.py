# ui/screens/progress.py
import curses
import threading
import time
from ..colors import attr, CP_TITLE, CP_PROGRESS, CP_DIM, CP_SUCCESS, CP_FAIL, CP_WARNING, CP_NORMAL


def screen_progress(stdscr, orchestrator) -> object:
    """
    Run the wipe and display live progress.
    This screen is special — it triggers the actual wipe operation
    in a background thread and updates the UI from the main thread.

    Returns the WipeSession object when done.
    """
    h, w = stdscr.getmaxyx()

    # Shared state between main thread (UI) and wipe thread
    progress_state = {
        "bytes_done": 0,
        "bytes_total": 1,
        "stage": "Initializing...",
        "messages": [],
        "done": False,
        "error": None,
        "session": None,
    }

    def progress_cb(bytes_done: int, bytes_total: int, stage: str):
        progress_state["bytes_done"] = bytes_done
        progress_state["bytes_total"] = max(1, bytes_total)
        progress_state["stage"] = stage
        if stage and stage not in progress_state["messages"]:
            progress_state["messages"].append(stage)
            # Keep only last 8 messages
            if len(progress_state["messages"]) > 8:
                progress_state["messages"].pop(0)

    def wipe_thread():
        try:
            session = orchestrator.execute_wipe(progress_cb)
            progress_state["session"] = session
        except Exception as e:
            progress_state["error"] = str(e)
        finally:
            progress_state["done"] = True

    # Start wipe in background thread
    t = threading.Thread(target=wipe_thread, daemon=True)
    t.start()

    start_time = time.time()

    # ── UI refresh loop ───────────────────────────────────────────────────
    stdscr.nodelay(True)  # Non-blocking getch during wipe

    while not progress_state["done"]:
        stdscr.clear()

        # Header
        dev_name = orchestrator.selected_device.display_name if orchestrator.selected_device else ""
        stdscr.addstr(0, 0, f" ZeroTrace — Wiping {dev_name} ".center(w), attr(CP_TITLE, bold=True))

        # Elapsed time
        elapsed = int(time.time() - start_time)
        mins, secs = divmod(elapsed, 60)
        elapsed_str = f"{mins:02d}:{secs:02d}"

        # ETA
        pct = progress_state["bytes_done"] / max(1, progress_state["bytes_total"])
        if pct > 0.01 and elapsed > 5:
            total_est = elapsed / pct
            remaining = int(total_est - elapsed)
            eta_mins, eta_secs = divmod(remaining, 60)
            eta_str = f"{eta_mins:02d}:{eta_secs:02d}"
        else:
            eta_str = "--:--"

        row = 2
        stdscr.addstr(row, 2, f"Elapsed: {elapsed_str}   ETA: {eta_str}", attr(CP_DIM))
        row += 2

        # Progress bar
        bar_width = w - 12
        filled = int(bar_width * pct)
        bar = "█" * filled + "░" * (bar_width - filled)
        pct_str = f"{pct*100:5.1f}%"

        stdscr.addstr(row, 2, f"[{bar}] {pct_str}", attr(CP_PROGRESS))
        row += 2

        # Current stage
        stage = progress_state["stage"]
        stdscr.addstr(row, 2, f"Status: {stage[:w-10]}", attr(CP_NORMAL))
        row += 2

        # Message log
        stdscr.addstr(row, 2, "── Log ───────────────────────────────────────", attr(CP_DIM))
        row += 1
        for msg in progress_state["messages"][-8:]:
            if row >= h - 3:
                break
            stdscr.addstr(row, 4, f"  {msg[:w-8]}", attr(CP_DIM))
            row += 1

        stdscr.addstr(h - 2, 0, " Wipe in progress — DO NOT POWER OFF OR REMOVE DRIVE ".center(w), attr(CP_WARNING, bold=True))
        stdscr.refresh()

        # Check for abort key (not recommended — show warning)
        key = stdscr.getch()
        if key == ord('q') or key == ord('Q'):
            # Show abort warning
            stdscr.addstr(h // 2, w // 2 - 25,
                "Abort is NOT recommended mid-wipe — drive may be in inconsistent state.", attr(CP_DANGER, bold=True))
            stdscr.refresh()

        time.sleep(0.25)  # 4 updates per second

    # Wipe thread done
    stdscr.nodelay(False)  # Back to blocking

    if progress_state["error"]:
        _show_wipe_error(stdscr, progress_state["error"])
        return None

    # Show completion
    _show_wipe_complete(stdscr, progress_state["session"], w, h)
    return progress_state["session"]


def _show_wipe_complete(stdscr, session, w: int, h: int):
    """Brief completion confirmation before moving to entropy screen."""
    stdscr.clear()
    stdscr.addstr(0, 0, " ZeroTrace — Wipe Complete ".center(w), attr(CP_TITLE, bold=True))

    if session and hasattr(session, 'wipe_result') and session.wipe_result:
        r = session.wipe_result
        success = r.success if hasattr(r, 'success') else False
        duration = r.duration_seconds if hasattr(r, 'duration_seconds') else 0

        if success:
            stdscr.addstr(h // 2 - 2, w // 2 - 12, "✓  WIPE COMPLETED SUCCESSFULLY", attr(CP_SUCCESS, bold=True))
        else:
            stdscr.addstr(h // 2 - 2, w // 2 - 10, "✗  WIPE FAILED", attr(CP_FAIL, bold=True))
            err = r.error_message if hasattr(r, 'error_message') else "Unknown error"
            stdscr.addstr(h // 2, 4, f"Error: {err[:w-8]}", attr(CP_FAIL))

        mins, secs = divmod(duration, 60)
        stdscr.addstr(h // 2 + 2, w // 2 - 10, f"Duration: {mins:02d}:{secs:02d}", attr(CP_DIM))

    stdscr.addstr(h - 2, 0, " Press any key to continue ".center(w), attr(CP_DIM))
    stdscr.refresh()
    stdscr.getch()


def _show_wipe_error(stdscr, error_msg: str):
    h, w = stdscr.getmaxyx()
    stdscr.clear()
    stdscr.addstr(0, 0, " ZeroTrace — Wipe Error ".center(w), attr(CP_DANGER, bold=True))
    stdscr.addstr(h // 2 - 1, 4, "The wipe operation encountered an error:", attr(CP_FAIL, bold=True))
    stdscr.addstr(h // 2 + 1, 4, error_msg[:w-8], attr(CP_FAIL))
    stdscr.addstr(h - 2, 0, " Press any key to return ".center(w), attr(CP_DIM))
    stdscr.refresh()
    stdscr.getch()
