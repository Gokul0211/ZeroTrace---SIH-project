# ui/main.py
# Entry point — called when ZeroTrace boots

import curses
import sys
import os

# Ensure zerotrace_core .so is findable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'core', 'build'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from .wizard import run_wizard


def main():
    # Must run as root for raw device access
    if os.geteuid() != 0:
        print("ZeroTrace must be run as root.")
        print("Try: sudo python3 -m ui.main")
        sys.exit(1)

    try:
        curses.wrapper(run_wizard)
    except KeyboardInterrupt:
        print("\nZeroTrace interrupted. No partial wipe certificates generated.")
        sys.exit(0)
    except Exception as e:
        print(f"\nFatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
