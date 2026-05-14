# ui/screens/certificate_export.py
import curses
import os
from ..colors import attr, CP_TITLE, CP_SUCCESS, CP_FAIL, CP_DIM, CP_NORMAL, CP_WARNING


def screen_certificate_export(stdscr, session, orchestrator) -> str:
    """
    Generate and export the wipe certificate.
    Calls Phase 4 certificate generator.
    """
    stdscr.clear()
    h, w = stdscr.getmaxyx()

    stdscr.addstr(0, 0, " ZeroTrace — Certificate Generation ".center(w), attr(CP_TITLE, bold=True))
    stdscr.addstr(2, 2, "Generating tamper-proof certificate...", attr(CP_NORMAL))
    stdscr.refresh()

    # Call Phase 4 certificate generator
    try:
        from cert.generator import generate_certificate_pair
        pdf_path, json_path = generate_certificate_pair(session)
        session.cert_pdf_path = pdf_path
        session.cert_json_path = json_path
        cert_success = True
        cert_error = None
    except Exception as e:
        cert_success = False
        cert_error = str(e)
        pdf_path = None
        json_path = None

    stdscr.clear()
    stdscr.addstr(0, 0, " ZeroTrace — Certificate Ready ".center(w), attr(CP_TITLE, bold=True))

    row = 2
    if cert_success:
        stdscr.addstr(row, 2, "✓  Certificate generated successfully.", attr(CP_SUCCESS, bold=True))
        row += 2
        if pdf_path:
            stdscr.addstr(row, 2, f"PDF:  {pdf_path}", attr(CP_NORMAL))
            row += 1
        if json_path:
            stdscr.addstr(row, 2, f"JSON: {json_path}", attr(CP_NORMAL))
            row += 1
        row += 1
        stdscr.addstr(row, 2, "Files saved to /mnt/usb/ (ZeroTrace USB drive).", attr(CP_DIM))
        row += 2
        stdscr.addstr(row, 2, "The JSON certificate includes a PKI digital signature.", attr(CP_DIM))
        row += 1
        stdscr.addstr(row, 2, "Verify with: python3 verify_cert.py <cert.json> <zerotrace_public.pem>", attr(CP_DIM))
    else:
        stdscr.addstr(row, 2, "✗  Certificate generation failed.", attr(CP_FAIL, bold=True))
        row += 1
        if cert_error:
            stdscr.addstr(row, 2, f"Error: {cert_error[:w-10]}", attr(CP_FAIL))
            if "No module named" in cert_error and "cert" in cert_error:
                stdscr.addstr(row+1, 2, "Phase 4 (Certificate Generator) not yet implemented or loaded.", attr(CP_WARNING))

    stdscr.addstr(h - 2, 0, " Enter: Done | B: Back | Q: Quit ".center(w), attr(CP_DIM))
    stdscr.refresh()

    while True:
        key = stdscr.getch()
        if key == ord('\n') or key == curses.KEY_ENTER:
            return "next"
        if key == ord('b') or key == ord('B'):
            return "back"
        if key == ord('q') or key == ord('Q'):
            return "quit"
