# ui/colors.py
import curses

# Color pair IDs — used as curses.color_pair(N)
CP_NORMAL       = 0   # Default terminal colors
CP_TITLE        = 1   # White on dark blue — header bars
CP_HIGHLIGHT    = 2   # Black on green — selected item
CP_WARNING      = 3   # Black on yellow — warnings
CP_DANGER       = 4   # White on red — destructive actions
CP_SUCCESS      = 5   # Black on green — confirmed/passed
CP_FAIL         = 6   # White on red — failed
CP_DIM          = 7   # Dark gray on black — secondary text
CP_PROGRESS     = 8   # Green on black — progress bar fill
CP_BORDER       = 9   # Cyan on black — box borders


def init_colors():
    """
    Initialize all color pairs.
    Must be called after curses.start_color().
    Call curses.use_default_colors() first to support transparent backgrounds.
    """
    curses.start_color()
    curses.use_default_colors()

    # (pair_id, foreground, background)
    # -1 = terminal default color
    curses.init_pair(CP_TITLE,     curses.COLOR_WHITE,  curses.COLOR_BLUE)
    curses.init_pair(CP_HIGHLIGHT, curses.COLOR_BLACK,  curses.COLOR_GREEN)
    curses.init_pair(CP_WARNING,   curses.COLOR_BLACK,  curses.COLOR_YELLOW)
    curses.init_pair(CP_DANGER,    curses.COLOR_WHITE,  curses.COLOR_RED)
    curses.init_pair(CP_SUCCESS,   curses.COLOR_GREEN,  -1)
    curses.init_pair(CP_FAIL,      curses.COLOR_RED,    -1)
    curses.init_pair(CP_DIM,       curses.COLOR_WHITE,  -1)
    curses.init_pair(CP_PROGRESS,  curses.COLOR_BLACK,  curses.COLOR_GREEN)
    curses.init_pair(CP_BORDER,    curses.COLOR_CYAN,   -1)


def attr(pair_id: int, bold: bool = False) -> int:
    """Convenience: return curses attribute for a color pair."""
    a = curses.color_pair(pair_id)
    if bold:
        a |= curses.A_BOLD
    return a
