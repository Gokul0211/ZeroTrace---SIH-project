# ui/screens/entropy_result.py
import curses
from ..colors import attr, CP_TITLE, CP_SUCCESS, CP_FAIL, CP_WARNING, CP_DIM, CP_NORMAL


def screen_entropy_result(stdscr, session) -> str:
    """Display entropy analysis results and valuation."""
    stdscr.clear()
    h, w = stdscr.getmaxyx()
    row = 0

    stdscr.addstr(row, 0, " ZeroTrace — Entropy Verification ".center(w), attr(CP_TITLE, bold=True))
    row += 2

    if not session:
        stdscr.addstr(row, 2, "No session data available.", attr(CP_WARNING))
        stdscr.addstr(h - 2, 0, " Enter: Continue ".center(w), attr(CP_DIM))
        stdscr.refresh()
        stdscr.getch()
        return "next"

    # Entropy results
    er = session.entropy_result
    if er:
        # Get entropy_bits regardless of whether er is a dict or C++ object
        if isinstance(er, dict):
            entropy_bits = er.get("entropy_bits")
            state        = er.get("state", "UNKNOWN")
            verified     = er.get("wipe_verified", False)
            sampled      = er.get("blocks_sampled", 0)
            coverage     = er.get("sample_coverage_pct", 0.0)
        else:
            entropy_bits = er.entropy_bits
            state        = er.state
            verified     = er.wipe_verified
            sampled      = er.blocks_sampled
            coverage     = er.sample_coverage_pct

        stdscr.addstr(row, 2, "── Entropy Analysis ─────────────────────────────", attr(CP_DIM))
        row += 1

        if entropy_bits is not None:
            # Visual entropy bar
            bar_width = 40
            bar_fill = int(bar_width * (entropy_bits / 8.0))
            bar = "█" * bar_fill + "░" * (bar_width - bar_fill)
            entropy_style = attr(CP_SUCCESS, bold=True) if verified else attr(CP_FAIL, bold=True)
            stdscr.addstr(row, 2, f"Entropy:  [{bar}]  {entropy_bits:.4f} bits/byte", entropy_style)
            row += 1
            stdscr.addstr(row, 2, f"          0 (all zeros)             8 (perfect random)", attr(CP_DIM))
            row += 2

        state_style = attr(CP_SUCCESS, bold=True) if verified else attr(CP_FAIL, bold=True)
        verified_str = "✓ WIPE VERIFIED" if verified else "✗ WIPE NOT VERIFIED"
        stdscr.addstr(row, 2, f"State:    ", attr(CP_NORMAL))
        stdscr.addstr(row, 12, state, state_style)
        row += 1
        stdscr.addstr(row, 2, f"Result:   ", attr(CP_NORMAL))
        stdscr.addstr(row, 12, verified_str, state_style)
        row += 1

        if sampled:
            stdscr.addstr(row, 2, f"Sampled:  {sampled:,} blocks  ({coverage:.1f}% coverage)", attr(CP_DIM))
            row += 1

        # Explain what the result means
        row += 1
        if verified:
            if "ZERO_FILL" in state:
                stdscr.addstr(row, 2, "All sampled blocks contain zeros. Clear mode confirmed.", attr(CP_SUCCESS))
            elif "RANDOM_FILL" in state or "PURGE" in state:
                stdscr.addstr(row, 2, "All sampled blocks contain cryptographically random data. Purge confirmed.", attr(CP_SUCCESS))
            elif "FIRMWARE" in state:
                stdscr.addstr(row, 2, "Drive reports sanitized state after firmware command.", attr(CP_SUCCESS))
        else:
            if state == "NOT_MEASURED":
                stdscr.addstr(row, 2, "Entropy not measured (Android factory reset — device rebooted).", attr(CP_WARNING))
            else:
                stdscr.addstr(row, 2, "Entropy is inconsistent with expected wipe state. Verify manually.", attr(CP_FAIL))
        row += 2
    else:
        stdscr.addstr(row, 2, "Entropy analysis not available.", attr(CP_WARNING))
        row += 2

    # Valuation
    val = session.valuation
    if val:
        stdscr.addstr(row, 2, "── E-Waste Valuation ────────────────────────────", attr(CP_DIM))
        row += 1
        stdscr.addstr(row, 2, f"Condition:         {val.get('condition', 'Unknown')}", attr(CP_NORMAL))
        row += 1
        stdscr.addstr(row, 2, f"Estimated Value:   ₹{val.get('estimated_value_inr', 0):,.0f}", attr(CP_SUCCESS, bold=True))
        row += 1
        stdscr.addstr(row, 2, f"Recommendation:    {val.get('recommendation', '')}", attr(CP_DIM))
        row += 2

    stdscr.addstr(h - 2, 0, " Enter: Continue to Certificate Export | B: Back | Q: Quit ".center(w), attr(CP_DIM))
    stdscr.refresh()

    while True:
        key = stdscr.getch()
        if key == ord('\n') or key == curses.KEY_ENTER:
            return "next"
        if key == ord('b') or key == ord('B'):
            return "back"
        if key == ord('q') or key == ord('Q'):
            return "quit"
