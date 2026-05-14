# cert/pdf_cert.py
#
# PDF certificate layout using reportlab.
# The PDF is a human-readable version of the JSON certificate.
# It is NOT independently signed — the JSON is the canonical signed form.
# The PDF includes the certificate hash and signature for visual verification.

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table,
    TableStyle, HRFlowable
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from datetime import datetime


# Page dimensions
PAGE_W, PAGE_H = letter  # 612 x 792 pt
MARGIN = 54              # 0.75 inch margins
USABLE_W = PAGE_W - 2 * MARGIN  # 504 pt

# Color palette
COLOR_HEADER_BG  = colors.HexColor("#1a237e")   # Dark blue
COLOR_HEADER_FG  = colors.white
COLOR_SECTION_BG = colors.HexColor("#e8eaf6")   # Light blue-gray
COLOR_SUCCESS     = colors.HexColor("#1b5e20")   # Dark green
COLOR_FAIL        = colors.HexColor("#b71c1c")   # Dark red
COLOR_WARNING     = colors.HexColor("#e65100")   # Orange
COLOR_BORDER      = colors.HexColor("#3949ab")   # Indigo
COLOR_TEXT        = colors.HexColor("#212121")   # Near black
COLOR_DIM         = colors.HexColor("#757575")   # Gray


def generate_pdf(cert_dict: dict, output_path: str):
    """
    Generate a PDF certificate from the finalized certificate dictionary.

    cert_dict: the output of json_cert.sign_and_finalize()
    output_path: where to save the PDF
    """
    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
        title="ZeroTrace Sanitization Certificate",
        author="ZeroTrace"
    )

    styles = getSampleStyleSheet()

    # Custom styles
    style_title = ParagraphStyle(
        "ZT_Title",
        parent=styles["Title"],
        fontSize=18,
        textColor=COLOR_HEADER_FG,
        alignment=TA_CENTER,
        spaceAfter=4,
        fontName="Helvetica-Bold"
    )
    style_subtitle = ParagraphStyle(
        "ZT_Subtitle",
        parent=styles["Normal"],
        fontSize=9,
        textColor=COLOR_HEADER_FG,
        alignment=TA_CENTER,
        fontName="Helvetica"
    )
    style_section = ParagraphStyle(
        "ZT_Section",
        parent=styles["Normal"],
        fontSize=10,
        textColor=COLOR_BORDER,
        fontName="Helvetica-Bold",
        spaceBefore=8,
        spaceAfter=4
    )
    style_body = ParagraphStyle(
        "ZT_Body",
        parent=styles["Normal"],
        fontSize=9,
        textColor=COLOR_TEXT,
        fontName="Helvetica",
        leading=14
    )
    style_code = ParagraphStyle(
        "ZT_Code",
        parent=styles["Code"],
        fontSize=7,
        textColor=COLOR_TEXT,
        fontName="Courier",
        leading=10
    )

    elements = []

    # ── Header block ──────────────────────────────────────────────────────
    header_data = [[
        Paragraph("ZEROTRACE SANITIZATION CERTIFICATE", style_title),
    ], [
        Paragraph(f"NIST SP 800-88 Rev.1 Compliant  |  Certificate ID: {cert_dict.get('certificate_id', 'N/A')}", style_subtitle),
    ], [
        Paragraph(f"Generated: {cert_dict.get('generated_at', 'N/A')}  |  ZeroTrace v{cert_dict.get('zerotrace_version', '1.0')}", style_subtitle),
    ]]

    header_table = Table(header_data, colWidths=[USABLE_W])
    header_table.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, -1), COLOR_HEADER_BG),
        ("TOPPADDING",  (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 12),
        ("LEFTPADDING",  (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 12))

    # ── Verification status banner ─────────────────────────────────────────
    ver = cert_dict.get("verification", {})
    wipe_success = cert_dict.get("wipe", {}).get("success", False)
    verified = ver.get("wipe_verified", False)
    entropy_state = ver.get("state", "NOT_MEASURED")

    if wipe_success and verified:
        status_text = "✓  SANITIZATION VERIFIED"
        status_color = COLOR_SUCCESS
    elif wipe_success:
        status_text = "⚠  WIPE COMPLETED — ENTROPY UNVERIFIED"
        status_color = COLOR_WARNING
    else:
        status_text = "✗  WIPE FAILED"
        status_color = COLOR_FAIL

    status_style = ParagraphStyle(
        "Status",
        parent=styles["Normal"],
        fontSize=14,
        textColor=colors.white,
        alignment=TA_CENTER,
        fontName="Helvetica-Bold"
    )
    status_table = Table([[Paragraph(status_text, status_style)]], colWidths=[USABLE_W])
    status_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), status_color),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    elements.append(status_table)
    elements.append(Spacer(1, 12))

    # ── Device Information ─────────────────────────────────────────────────
    elements.append(Paragraph("DEVICE INFORMATION", style_section))
    dev = cert_dict.get("device", {})

    if dev.get("type") == "ANDROID":
        dev_data = [
            ["Device Type",     "Android Mobile Device"],
            ["Manufacturer",    dev.get("manufacturer", "N/A")],
            ["Model",           dev.get("model", "N/A")],
            ["Serial Number",   dev.get("serial", "N/A")],
            ["Android Version", dev.get("android_version", "N/A")],
            ["Build ID",        dev.get("build_id", "N/A")],
            ["Storage Type",    dev.get("storage_type", "N/A")],
            ["Storage Size",    f"{dev.get('userdata_size_gb', 0):.1f} GB (userdata partition)"],
            ["Encryption",      dev.get("encryption_state", "N/A").upper()],
            ["TEE-backed Keys", "YES" if dev.get("tee_backed_keys") else "NO"],
        ]
    else:
        dev_data = [
            ["Device Type",    dev.get("type", "N/A").replace("_", " ")],
            ["Model",          dev.get("model", "N/A")],
            ["Serial Number",  dev.get("serial", "N/A")],
            ["Firmware",       dev.get("firmware", "N/A")],
            ["Capacity",       f"{dev.get('size_gb', 0):.1f} GB  ({dev.get('total_lbas', 0):,} sectors)"],
        ]
        smart = dev.get("smart", {})
        if smart:
            dev_data += [
                ["SMART Health",    smart.get("health", "N/A")],
                ["Power-On Hours",  f"{smart.get('power_on_hours', 0):,} hours"],
                ["Temperature",     f"{smart.get('temperature_celsius', 0)}°C"],
                ["Reallocated Sectors", str(smart.get("reallocated_sector_count", 0))],
            ]

    elements.append(_make_table(dev_data))
    elements.append(Spacer(1, 8))

    # ── Wipe Operation ─────────────────────────────────────────────────────
    elements.append(Paragraph("WIPE OPERATION", style_section))
    wipe = cert_dict.get("wipe", {})

    if dev.get("type") == "ANDROID":
        wipe_data = [
            ["Wipe Mode",              wipe.get("mode", "N/A")],
            ["Start Time",             wipe.get("start", "N/A")],
            ["End Time",               wipe.get("end", "N/A")],
            ["Duration",               f"{wipe.get('duration_seconds', 0)} seconds"],
            ["Root Access",            "YES" if wipe.get("is_rooted") else "NO"],
            ["Userdata Wiped",         "YES" if wipe.get("userdata_wiped") else "NO"],
            ["Metadata Partition Wiped", "YES" if wipe.get("metadata_wiped") else "NO"],
            ["TEE Keys Invalidated",   "YES" if wipe.get("tee_keys_invalidated") else "NO"],
            ["Hardware Secure Erase",  "YES" if wipe.get("hardware_secure_erase") else "NO"],
            ["Factory Reset",          "YES" if wipe.get("factory_reset_triggered") else "NO"],
            ["Coverage Level",         wipe.get("coverage", "unknown").upper()],
        ]
    else:
        wipe_data = [
            ["Wipe Mode",              wipe.get("mode", "N/A")],
            ["Start Time",             wipe.get("start", "N/A")],
            ["End Time",               wipe.get("end", "N/A")],
            ["Duration",               f"{wipe.get('duration_seconds', 0)} seconds"],
            ["HPA Removed",            "YES" if wipe.get("hpa_removed") else "NO / Not Present"],
            ["DCO Restored",           "YES" if wipe.get("dco_restored") else "NO / Not Present"],
            ["Hidden Areas Covered",   "YES" if wipe.get("hidden_areas_covered") else "NO"],
            ["Firmware Command Used",  "YES" if wipe.get("firmware_command_used") else "NO"],
            ["Firmware Command",       wipe.get("firmware_command_name", "N/A")],
        ]

    elements.append(_make_table(wipe_data))
    elements.append(Spacer(1, 8))

    # ── Entropy Verification ───────────────────────────────────────────────
    elements.append(Paragraph("ENTROPY VERIFICATION", style_section))

    ver = cert_dict.get("verification", {})
    entropy_bits = ver.get("entropy_bits")

    if entropy_bits is not None:
        # Visual entropy bar using ASCII
        bar_w = 40
        bar_fill = int(bar_w * (entropy_bits / 8.0))
        bar = "█" * bar_fill + "░" * (bar_w - bar_fill)
        entropy_display = f"{entropy_bits:.6f} bits/byte"

        ver_data = [
            ["Shannon Entropy",       entropy_display],
            ["Entropy Bar",           f"[{bar}]  (0=zeros, 8=random)"],
            ["Verification State",    ver.get("state", "UNKNOWN")],
            ["Wipe Verified",         "✓ YES" if ver.get("wipe_verified") else "✗ NO"],
            ["Blocks Sampled",        f"{ver.get('blocks_sampled', 0):,}"],
            ["Sample Coverage",       f"{ver.get('sample_coverage_pct', 0):.1f}%"],
        ]
    else:
        ver_data = [
            ["Verification",          ver.get("state", "NOT_PERFORMED")],
            ["Note",                  "Entropy measurement not available for this wipe type."],
        ]

    elements.append(_make_table(ver_data))
    elements.append(Spacer(1, 8))

    # ── Valuation ──────────────────────────────────────────────────────────
    val = cert_dict.get("valuation")
    if val:
        elements.append(Paragraph("E-WASTE VALUATION", style_section))
        val_data = [
            ["Device Condition",       val.get("condition", "N/A")],
            ["Estimated Value",        f"₹{val.get('estimated_value_inr', 0):,.0f}"],
            ["Certification Bonus",    val.get("certification_bonus", "N/A")],
            ["Recommendation",         val.get("recommendation", "N/A")],
        ]
        elements.append(_make_table(val_data))
        elements.append(Spacer(1, 8))

    # ── Digital Signature ─────────────────────────────────────────────────
    elements.append(Paragraph("DIGITAL SIGNATURE & INTEGRITY", style_section))

    cert_hash = cert_dict.get("certificate_hash", "N/A")
    signature = cert_dict.get("signature", "N/A")
    fingerprint = cert_dict.get("public_key_fingerprint", "N/A")

    elements.append(Paragraph("Certificate Hash (SHA-256):", style_body))
    elements.append(Paragraph(cert_hash, style_code))
    elements.append(Spacer(1, 4))

    elements.append(Paragraph("Digital Signature (RSA-4096 PSS / SHA-256, Base64):", style_body))
    # Break long signature into readable lines
    sig_lines = [signature[i:i+76] for i in range(0, len(signature), 76)]
    for line in sig_lines:
        elements.append(Paragraph(line, style_code))
    elements.append(Spacer(1, 4))

    elements.append(Paragraph(f"Public Key Fingerprint: {fingerprint}", style_body))
    elements.append(Spacer(1, 6))

    elements.append(Paragraph(
        "To verify this certificate: python3 verify_cert.py &lt;cert.json&gt; zerotrace_public.pem",
        ParagraphStyle("verify_note", parent=style_body, textColor=COLOR_DIM, fontSize=8)
    ))

    elements.append(Spacer(1, 12))
    elements.append(HRFlowable(width=USABLE_W, color=COLOR_BORDER))
    elements.append(Spacer(1, 6))

    disclaimer = (
        "This certificate was generated by ZeroTrace, a secure data sanitization tool compliant with "
        "NIST SP 800-88 Rev.1 Guidelines for Media Sanitization. The digital signature ensures this "
        "certificate has not been tampered with since generation. ZeroTrace is an open-source tool — "
        "the public key for verification is distributed at github.com/zerotrace/zerotrace."
    )
    elements.append(Paragraph(disclaimer, ParagraphStyle(
        "disclaimer", parent=style_body, fontSize=7.5, textColor=COLOR_DIM
    )))

    doc.build(elements)


def _make_table(data: list) -> Table:
    """
    Build a two-column label-value table.
    data: list of [label, value] pairs
    """
    col1_w = 160
    col2_w = USABLE_W - col1_w

    style_label = ParagraphStyle("lbl", fontName="Helvetica-Bold", fontSize=8.5, textColor=COLOR_TEXT)
    style_value = ParagraphStyle("val", fontName="Helvetica", fontSize=8.5, textColor=COLOR_TEXT)

    table_data = []
    for row in data:
        label = Paragraph(str(row[0]), style_label)
        value = Paragraph(str(row[1]), style_value)
        table_data.append([label, value])

    t = Table(table_data, colWidths=[col1_w, col2_w])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (0, -1), COLOR_SECTION_BG),
        ("GRID",          (0, 0), (-1, -1), 0.5, colors.HexColor("#c5cae9")),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ]))
    return t
