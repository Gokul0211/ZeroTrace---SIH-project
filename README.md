# ZeroTrace

A bootable, OS-independent hardware sanitization platform and empirical systems-security research framework. ZeroTrace bridges the gap between hardware-level firmware commands and cryptographically verifiable audit trails, designed for strict compliance with NIST SP 800-88 guidelines.

---

## Why This Exists

Data sanitization in enterprise and e-waste recycling environments relies heavily on tools that are fundamentally flawed by their operating context. Standard file shredders run inside a host Operating System. By definition, they cannot overwrite the blocks occupied by the OS itself, the page file, or the partition tables. Even dedicated bootable tools often rely on standard POSIX write operations (`dd`, `shred`) which abstract away the physical storage medium.

This abstraction creates three critical vulnerabilities:

1. **Hidden Areas are Ignored**: Host Protected Areas (HPA) and Device Configuration Overlays (DCO) are ATA firmware features used to hide physical sectors from the OS. Standard tools wipe the addressable logical block area (LBA) and leave hidden data entirely untouched.
2. **Flash Translation Layer (FTL) Wear-Leveling**: Modern Solid State Drives (SSDs) and Android eMMC/UFS storage utilize wear-leveling algorithms. Overwriting a logical block with zeros simply remaps the write to a fresh NAND cell, leaving the original sensitive data intact in an unmapped state. 
3. **Mobile TEE Key Retention**: Wiping an Android device via `adb` or recovery often fails to evict the File-Based Encryption (FBE) keys stored in the hardware-backed Trusted Execution Environment (TEE). If the wrapped key material in the `/metadata` partition is not securely destroyed, the user data remains vulnerable to offline cryptanalysis.

ZeroTrace operates at the hardware level. It bypasses the OS page cache entirely, communicating directly with storage controllers via low-level `ioctl` commands (NVMe Sanitize, ATA Secure Erase). It forces the eradication of HPA/DCO constraints, explicitly orchestrates TEE key eviction on Android devices, and performs cryptographic verification of the physical media after the operation completes.

---

## How It Works

ZeroTrace is structured as a multi-tier pipeline executing entirely from an ephemeral Ubuntu minimal chroot environment.

### 1. Drive Discovery & Pre-Flight Analysis
The system enumerates all block devices and connected Android devices via ADB. It extracts SMART data, identifies storage transport layers (NVMe vs SATA vs USB), and checks for security freeze locks. For Android, it probes the filesystem to determine if the storage uses eMMC or UFS protocols and whether the device is rooted.

### 2. The Wipe Engine
The core execution engine is written in C++ and exposed to the Python orchestrator via `pybind11`. It enforces three primary sanitization methodologies based on the storage medium:
* **CLEAR (Zero Overwrite)**: For legacy magnetic media. Uses `O_DIRECT` and `O_SYNC` to bypass host-side SRAM/DRAM caching, forcing physical alignment writes.
* **PURGE (Cryptographic Erase)**: Generates an ephemeral AES-256 key, encrypts the target namespace, and then securely random-fills the namespace. The key is destroyed in RAM, rendering the ciphertext mathematically indistinguishable from random noise.
* **FIRMWARE DELETION**: The preferred method for modern media. Issues `ATA SECURITY ERASE UNIT` or `NVMe SANITIZE` commands. This instructs the drive's internal microcontroller to discharge all NAND gates, including overprovisioned and wear-leveled blocks.

### 3. Entropy Verification Engine
ZeroTrace does not trust the firmware's success code. Post-wipe, the C++ engine samples blocks across the physical media and calculates the Shannon entropy distribution. A successful `CLEAR` yields an entropy near `0.0` bits/byte. A successful `PURGE` yields an entropy near `8.0` bits/byte. If the entropy calculation indicates structured data (e.g., `4.5`), the wipe is flagged as failed.

### 4. Cryptographic Audit Trail
Once verification completes, the orchestrator generates a canonical JSON document containing the drive serial, SMART health metrics, the chosen wipe mode, the entropy verification output, and the e-waste valuation estimate. This JSON is hashed via SHA-256 and digitally signed using an on-board RSA-4096 private key. A human-readable PDF is generated concurrently.

---

## Empirical Telemetry Framework

ZeroTrace includes a specialized subsystem for systems-security research: the **Firmware Sanitization Verification Research Framework**.

A known vulnerability in the storage supply chain is "firmware fraud." Low-cost SSD controllers may respond successfully to a `Secure Erase` command by simply deleting their internal FTL lookup table rather than spending the power and time required to physically discharge the NAND cells.

ZeroTrace provides a benchmarking platform to detect these behavioral inconsistencies:
* **High-Resolution Telemetry**: Uses inline `RDTSC` assembly instructions to measure read latency at the CPU cycle level.
* **OS Noise Mitigation**: Utilizes `cpuid` for execution serialization, `pthread_setaffinity_np` to pin the measurement thread to a single core, and an APST (Autonomous Power State Transition) warm-up loop to normalize NVMe power states prior to measurement.
* **Statistical Inference**: The Python layer uses `scipy.stats` to perform Two-Sample Kolmogorov-Smirnov (K-S) tests. It compares the post-wipe latency distribution against established baselines for physically erased vs. charged NAND cells.
* **Dataset Generation**: Automatically exports rich telemetry metadata (kernel version, CPU governor state, thermal metrics, and trial averages) for cross-vendor vulnerability research.

---

## Installation & Compilation

ZeroTrace is not installed on a host machine; it is built into a bootable ISO.

### Prerequisites (Build Environment)
* Ubuntu 22.04 LTS or Debian 11+
* `xorriso`, `squashfs-tools`, `wget`

### Build Pipeline

```bash
git clone https://github.com/yourorganization/zerotrace.git
cd zerotrace

# Generate the RSA-4096 PKI keys required for certificate signing
python3 -c "from cert.signer import generate_keypair; generate_keypair()"

# Execute the master build script
sudo bash iso/build_iso.sh
```

The script automates the creation of an Ubuntu minimal filesystem, `chroot`s into the environment, installs all dependencies (`scipy`, `pybind11`, `nvme-cli`), compiles the C++ `zerotrace_core.so` static library, configures the `systemd` auto-start daemon for the Curses TUI, and packs the final `zerotrace-v1.0.0.iso`.

---

## Project Structure

```text
zerotrace/
├── core/                       # C++ low-level hardware engine
│   ├── include/
│   │   ├── ata.hpp             # HPA/DCO manipulation and Secure Erase
│   │   ├── nvme.hpp            # NVMe namespace identification and Sanitize
│   │   ├── timing.hpp          # RDTSC high-resolution telemetry engine
│   │   └── entropy.hpp         # Shannon entropy mathematics
│   ├── src/
│   │   ├── timing.cpp          # O_DIRECT block reads and thread-pinning
│   │   ├── wipe_purge.cpp      # Cryptographic overwrite implementation
│   │   └── bindings.cpp        # pybind11 exports to Python space
│   └── CMakeLists.txt          # Core build configuration
├── android/                    # ADB Orchestration module
│   ├── tee_handler.py          # Secure Enclave key eviction logic
│   └── wipe_android.py         # Rooted eMMC/UFS vs non-root recovery reset
├── research/                   # Firmware Verification Framework
│   ├── analyzer.py             # SciPy KS-tests and pre-flight validation
│   └── telemetry_export.py     # Benchmark dataset generation (CSV/JSON)
├── cert/                       # Cryptographic Audit module
│   ├── signer.py               # RSA-4096 PSS signing
│   ├── json_cert.py            # Canonical data hashing
│   └── pdf_cert.py             # ReportLab forensic document generation
├── ui/                         # Python Curses TUI
│   ├── orchestrator.py         # State management and async execution
│   └── screens/                # UI rendering (Wizard flow, Research Mode)
├── iso/                        # Build Pipeline
│   ├── build_iso.sh            # Master ISO creation script
│   └── install_deps.sh         # Chroot dependency resolution
├── valuation/                  # E-Waste heuristic engine
└── requirements.txt            # Python dependencies (scipy, reportlab, cryptography)
```

---

## Design Decisions

### Why C++ for the Core Engine?
Direct interaction with storage controllers requires raw `ioctl` system calls and precise memory alignment. Python's standard library abstracts block device access too heavily. By writing the core in C++ and binding it via `pybind11`, we maintain the rapid development iteration of the Python TUI while executing safety-critical, nanosecond-precise memory and hardware operations natively.

### Why O_DIRECT?
Standard POSIX `write()` or `read()` operations pass through the Linux page cache. When performing latency benchmarking or entropy verification, reading from the page cache measures DRAM speed, not NAND speed. `O_DIRECT` forces the kernel to bypass SRAM/DRAM buffers, guaranteeing that measurements reflect the true physical state of the storage controller.

### Why wiping `/metadata` on Android?
Android devices utilizing File-Based Encryption (FBE) store the actual encryption keys within a hardware-backed Trusted Execution Environment (TEE). Deleting the encrypted files in `/data` does not destroy the keys. Wiping the `/metadata` block device destroys the wrapped key material used to negotiate with the TEE, cryptographically bricking the existing userdata payload and rendering forensic recovery impossible.

### Why Two-Sample K-S Tests for Telemetry?
Read latencies from NVMe drives do not follow a standard normal (Gaussian) distribution due to garbage collection spikes, thermal throttling, and queue depth variations. Comparing mean averages is statistically unsound. The Two-Sample Kolmogorov-Smirnov test compares the empirical cumulative distribution functions of two samples, making it highly robust against the non-parametric noise inherent in hardware latency measurements.

---

## Disclaimer

ZeroTrace is a destructive administrative utility designed for the permanent eradication of data. Operations performed by this software are forensically unrecoverable by design. The authors and maintainers assume no liability for accidental data loss, hardware degradation, or system unrecoverability resulting from the use of this software. Verify your target block devices meticulously.
