# ui/screens/health_report.py
import curses
from ..colors import attr, CP_TITLE, CP_SUCCESS, CP_FAIL, CP_WARNING, CP_DIM, CP_NORMAL, CP_DANGER


def screen_health_report(stdscr, device) -> str:
    """
    Display drive health, SMART data, HPA/DCO status.
    User presses Enter to continue or B to go back.
    """
    stdscr.clear()
    h, w = stdscr.getmaxyx()
    row = 0

    # Header
    stdscr.addstr(row, 0, f" ZeroTrace — Device Health Report ".center(w), attr(CP_TITLE, bold=True))
    row += 2

    if device.is_android:
        info = device.android_device
        stdscr.addstr(row, 2, f"Device:        {info.manufacturer} {info.model}", attr(CP_NORMAL))
        row += 1
        stdscr.addstr(row, 2, f"Android:       {info.android_version} (SDK {info.sdk_version})", attr(CP_NORMAL))
        row += 1
        stdscr.addstr(row, 2, f"Build ID:      {info.build_id}", attr(CP_NORMAL))
        row += 1
        stdscr.addstr(row, 2, f"Serial:        {info.serial}", attr(CP_NORMAL))
        row += 1
        stdscr.addstr(row, 2, f"Storage:       {info.storage_type.value}", attr(CP_NORMAL))
        row += 1
        stdscr.addstr(row, 2, f"Storage size:  {info.userdata_size_bytes // (1024*1024*1024)} GB (userdata)", attr(CP_NORMAL))
        row += 2

        # Root status
        root_style = attr(CP_SUCCESS, bold=True) if info.is_rooted else attr(CP_WARNING, bold=True)
        root_text = "✓ YES — Full sanitization available" if info.is_rooted else "✗ NO — Limited to factory reset"
        stdscr.addstr(row, 2, f"Root access:   ", attr(CP_NORMAL))
        stdscr.addstr(row, 17, root_text, root_style)
        row += 1

        # Encryption
        enc_style = attr(CP_SUCCESS) if info.encryption_state.value == "encrypted" else attr(CP_WARNING)
        stdscr.addstr(row, 2, f"Encryption:    ", attr(CP_NORMAL))
        stdscr.addstr(row, 17, info.encryption_state.value.upper(), enc_style)
        row += 1

        # TEE
        tee_style = attr(CP_WARNING) if info.tee_backed_keys else attr(CP_DIM)
        tee_text = "YES — Hardware-backed (TEE/StrongBox)" if info.tee_backed_keys else "NO — Software only"
        stdscr.addstr(row, 2, f"TEE keys:      ", attr(CP_NORMAL))
        stdscr.addstr(row, 17, tee_text, tee_style)
        row += 1

        # Bootloader
        bl_text = "Unlocked" if info.bootloader_unlocked else "Locked"
        stdscr.addstr(row, 2, f"Bootloader:    {bl_text}", attr(CP_NORMAL))
        row += 2

    else:
        dev = device.pc_device
        smart = dev.smart
        hidden = dev.hidden

        # Identity
        stdscr.addstr(row, 2, f"Model:         {dev.model}", attr(CP_NORMAL))
        row += 1
        stdscr.addstr(row, 2, f"Serial:        {dev.serial}", attr(CP_NORMAL))
        row += 1
        stdscr.addstr(row, 2, f"Firmware:      {dev.firmware_version}", attr(CP_NORMAL))
        row += 1
        stdscr.addstr(row, 2, f"Capacity:      {dev.size_gb:.1f} GB  ({dev.total_lbas:,} sectors)", attr(CP_NORMAL))
        row += 1
        stdscr.addstr(row, 2, f"Type:          {'SSD' if dev.is_ssd else 'HDD'}", attr(CP_NORMAL))
        row += 2

        # SMART
        stdscr.addstr(row, 2, "── SMART Data ──────────────────────────", attr(CP_DIM))
        row += 1
        h_style = attr(CP_SUCCESS, bold=True) if int(smart.overall_health) == 0 else attr(CP_FAIL, bold=True)
        h_text = {0: "✓ PASSED", 1: "⚠ WARNING", 2: "✗ FAILED", 3: "? UNKNOWN"}.get(int(smart.overall_health), "?")
        stdscr.addstr(row, 2, f"Health:        ", attr(CP_NORMAL))
        stdscr.addstr(row, 17, h_text, h_style)
        row += 1
        stdscr.addstr(row, 2, f"Temperature:   {smart.temperature_celsius}°C", attr(CP_NORMAL))
        row += 1
        stdscr.addstr(row, 2, f"Power-on hrs:  {smart.power_on_hours:,} hrs", attr(CP_NORMAL))
        row += 1

        realloc_style = attr(CP_FAIL) if smart.reallocated_sector_count > 10 else (attr(CP_WARNING) if smart.reallocated_sector_count > 0 else attr(CP_SUCCESS))
        stdscr.addstr(row, 2, f"Reallocated:   ", attr(CP_NORMAL))
        stdscr.addstr(row, 17, str(smart.reallocated_sector_count), realloc_style)
        row += 1
        stdscr.addstr(row, 2, f"Pending:       {smart.pending_sector_count}", attr(CP_NORMAL))
        row += 2

        # Hidden areas
        stdscr.addstr(row, 2, "── Hidden Areas ─────────────────────────", attr(CP_DIM))
        row += 1

        hpa_style = attr(CP_WARNING, bold=True) if hidden.hpa_detected else attr(CP_SUCCESS)
        hpa_text = f"DETECTED  ({hidden.hpa_hidden_lbas:,} hidden sectors)" if hidden.hpa_detected else "Not detected"
        stdscr.addstr(row, 2, f"HPA:           ", attr(CP_NORMAL))
        stdscr.addstr(row, 17, hpa_text, hpa_style)
        row += 1

        dco_style = attr(CP_WARNING, bold=True) if hidden.dco_modification_present else attr(CP_SUCCESS)
        dco_text = "MODIFIED" if hidden.dco_modification_present else "Not modified"
        stdscr.addstr(row, 2, f"DCO:           ", attr(CP_NORMAL))
        stdscr.addstr(row, 17, dco_text, dco_style)
        row += 1

        frozen_style = attr(CP_WARNING) if hidden.security_frozen else attr(CP_SUCCESS)
        frozen_text = "FROZEN (may limit Firmware Deletion)" if hidden.security_frozen else "Not frozen"
        stdscr.addstr(row, 2, f"ATA Security:  ", attr(CP_NORMAL))
        stdscr.addstr(row, 17, frozen_text, frozen_style)
        row += 1

    # Warnings
    if device.warnings:
        row += 1
        stdscr.addstr(row, 2, "── Warnings ─────────────────────────────", attr(CP_WARNING))
        row += 1
        for warn in device.warnings:
            if row >= h - 4:
                break
            stdscr.addstr(row, 2, f"⚠  {warn[:w-6]}", attr(CP_WARNING))
            row += 1

    # Footer
    stdscr.addstr(h - 2, 0, " Enter: Continue  |  B: Back  |  Q: Quit ".center(w), attr(CP_DIM))
    stdscr.refresh()

    while True:
        key = stdscr.getch()
        if key == ord('\n') or key == curses.KEY_ENTER:
            return "next"
        if key == ord('b') or key == ord('B') or key == curses.KEY_BACKSPACE:
            return "back"
        if key == ord('q') or key == ord('Q'):
            return "quit"
