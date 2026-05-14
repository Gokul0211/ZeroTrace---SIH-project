# ui/screens/research_mode.py
import curses
import threading
import time

def draw_research_mode(stdscr, orchestrator):
    """
    Specialized TUI screen for Phase 5 Research Benchmarking.
    Executes the telemetry scan and displays K-S test results.
    """
    curses.curs_set(0)
    stdscr.clear()
    h, w = stdscr.getmaxyx()
    
    if not orchestrator.selected_device or orchestrator.selected_device.is_android:
        stdscr.addstr(2, 2, "Error: Select a PC block device first to run telemetry.", curses.color_pair(1) | curses.A_BOLD)
        stdscr.addstr(4, 2, "Press any key to return...")
        stdscr.refresh()
        stdscr.getch()
        return

    session = orchestrator.current_session
    if not session or not session.wipe_result:
        stdscr.addstr(2, 2, "Error: Must perform a wipe before running telemetry.", curses.color_pair(1) | curses.A_BOLD)
        stdscr.addstr(4, 2, "Press any key to return...")
        stdscr.refresh()
        stdscr.getch()
        return

    title = " ZeroTrace Phase 5 — Research Benchmark Mode "
    stdscr.addstr(1, max(0, w//2 - len(title)//2), title, curses.color_pair(3) | curses.A_BOLD)
    
    status_y = 4
    stdscr.addstr(status_y, 2, "Initializing Telemetry Engine (O_DIRECT, RDTSC)...")
    stdscr.refresh()

    result_box = {}
    is_done = False
    
    def run_benchmark():
        nonlocal result_box, is_done
        # Hardcoding 10,000 blocks for statistical significance as requested
        res = orchestrator.run_telemetry_benchmark(session, sample_count=10000)
        result_box.update(res)
        is_done = True

    t = threading.Thread(target=run_benchmark, daemon=True)
    t.start()
    
    # Spinner
    spinner = ["|", "/", "-", "\\"]
    idx = 0
    while not is_done:
        stdscr.addstr(status_y, 55, spinner[idx % 4], curses.color_pair(4))
        stdscr.refresh()
        idx += 1
        time.sleep(0.1)
        
    stdscr.move(status_y, 0)
    stdscr.clrtoeol()
    
    if "error" in result_box:
        stdscr.addstr(status_y, 2, f"Benchmark Failed: {result_box['error']}", curses.color_pair(1) | curses.A_BOLD)
    else:
        stdscr.addstr(status_y, 2, "Benchmark Complete! Data exported to CSV.", curses.color_pair(2) | curses.A_BOLD)
        
        y = status_y + 2
        stdscr.addstr(y, 2, "─" * (w - 4))
        y += 2
        
        anom = result_box.get('is_anomalous', False)
        anom_str = "DETECTED" if anom else "CONSISTENT"
        anom_color = curses.color_pair(1) if anom else curses.color_pair(2)
        
        stdscr.addstr(y, 2, "Behavioral Inconsistency: ")
        stdscr.addstr(y, 28, anom_str, anom_color | curses.A_BOLD)
        y += 2
        
        stdscr.addstr(y, 2, f"Mean Latency (Cycles):  {result_box.get('mean_cycles', 0):.2f}")
        y += 1
        stdscr.addstr(y, 2, f"Std Deviation:          {result_box.get('std_dev_cycles', 0):.2f}")
        y += 1
        stdscr.addstr(y, 2, f"KS p-value (vs Erased): {result_box.get('p_value_vs_erased', 1.0):.4f}")
        y += 1
        stdscr.addstr(y, 2, f"KS p-value (vs Charged):{result_box.get('p_value_vs_charged', 1.0):.4f}")
        y += 1
        stdscr.addstr(y, 2, f"Repeated Trials:        {result_box.get('trial_count', 1)}")
        y += 2
        
        warnings = result_box.get("warnings", [])
        if warnings:
            stdscr.addstr(y, 2, "Pre-Flight Environment Warnings:", curses.color_pair(3) | curses.A_BOLD)
            y += 1
            for warn in warnings:
                stdscr.addstr(y, 4, f"- {warn}", curses.color_pair(3))
                y += 1
            y += 1
        
        if anom:
            stdscr.addstr(y, 2, "NOTE: Firmware anomaly implies potential FTL cache wipe without physical NAND discharge.", curses.color_pair(3))
        else:
            stdscr.addstr(y, 2, "NOTE: Read latency distribution is consistent with physical NAND cell erasure.", curses.color_pair(2))

    y += 4
    stdscr.addstr(y, max(0, w//2 - 15), "[ Press any key to return ]", curses.A_DIM)
    stdscr.refresh()
    stdscr.getch()
