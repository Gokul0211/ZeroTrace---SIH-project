#!/bin/bash
# iso/build_iso.sh
#
# Builds the ZeroTrace bootable ISO.
# Run on a Linux development machine (Ubuntu 22.04 recommended).
# Requires: xorriso, squashfs-tools, genisoimage, wget
#
# Usage: sudo bash build_iso.sh [--skip-download]
#
# Output: zerotrace-v1.0.iso (in current directory)

set -euo pipefail

ZEROTRACE_VERSION="1.0.0"
OUTPUT_ISO="zerotrace-v${ZEROTRACE_VERSION}.iso"
WORK_DIR="/tmp/zerotrace-iso-build"
UBUNTU_ISO_URL="https://releases.ubuntu.com/22.04/ubuntu-22.04.5-live-server-amd64.iso"
UBUNTU_ISO="ubuntu-22.04-server.iso"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log()  { echo -e "${GREEN}[BUILD]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $1"; }
fail() { echo -e "${RED}[FAIL]${NC}  $1"; exit 1; }

# ── Check prerequisites ───────────────────────────────────────────────────
log "Checking prerequisites..."
for cmd in xorriso mksquashfs unsquashfs wget cmake python3 pip3; do
    if ! command -v $cmd &> /dev/null; then
        fail "$cmd not found. Install with: sudo apt-get install $cmd"
    fi
done

if [ "$EUID" -ne 0 ]; then
    fail "Must run as root: sudo bash build_iso.sh"
fi

# ── Download Ubuntu base ISO ──────────────────────────────────────────────
if [ "${1:-}" != "--skip-download" ] && [ ! -f "$UBUNTU_ISO" ]; then
    log "Downloading Ubuntu 22.04 Server ISO (~1.4GB)..."
    wget -q --show-progress -O "$UBUNTU_ISO" "$UBUNTU_ISO_URL"
fi

[ -f "$UBUNTU_ISO" ] || fail "Ubuntu ISO not found: $UBUNTU_ISO"

# ── Setup work directory ──────────────────────────────────────────────────
log "Setting up work directory at $WORK_DIR..."
rm -rf "$WORK_DIR"
mkdir -p "$WORK_DIR"/{iso-extract,squashfs-mount,squashfs-edit,iso-new}

# ── Extract ISO ───────────────────────────────────────────────────────────
log "Extracting Ubuntu ISO..."
xorriso -osirrox on \
    -indev "$UBUNTU_ISO" \
    -extract / "$WORK_DIR/iso-extract" 2>/dev/null

# ── Mount and extract squashfs ────────────────────────────────────────────
log "Extracting squashfs filesystem..."
SQUASHFS_PATH=$(find "$WORK_DIR/iso-extract" -name "*.squashfs" | head -1)
[ -z "$SQUASHFS_PATH" ] && SQUASHFS_PATH=$(find "$WORK_DIR/iso-extract" -name "filesystem.squashfs" | head -1)
[ -z "$SQUASHFS_PATH" ] && fail "Cannot find squashfs in ISO"

unsquashfs -d "$WORK_DIR/squashfs-edit" "$SQUASHFS_PATH"

# ── Install dependencies into squashfs ───────────────────────────────────
log "Installing ZeroTrace dependencies into squashfs..."
cp iso/install_deps.sh "$WORK_DIR/squashfs-edit/tmp/"
chmod +x "$WORK_DIR/squashfs-edit/tmp/install_deps.sh"

# Mount required pseudo-filesystems for chroot
mount --bind /dev     "$WORK_DIR/squashfs-edit/dev"
mount --bind /dev/pts "$WORK_DIR/squashfs-edit/dev/pts"
mount --bind /proc    "$WORK_DIR/squashfs-edit/proc"
mount --bind /sys     "$WORK_DIR/squashfs-edit/sys"

# Run dependency install inside chroot
chroot "$WORK_DIR/squashfs-edit" /tmp/install_deps.sh

# ── Build ZeroTrace C++ core inside chroot ────────────────────────────────
log "Building zerotrace_core C++ module..."

# Copy ZeroTrace source into squashfs
mkdir -p "$WORK_DIR/squashfs-edit/opt/zerotrace"
cp -r core android ui cert valuation "$WORK_DIR/squashfs-edit/opt/zerotrace/"

# Build inside chroot
chroot "$WORK_DIR/squashfs-edit" bash -c "
    cd /opt/zerotrace/core
    mkdir -p build && cd build
    cmake .. -DCMAKE_BUILD_TYPE=Release -DPYTHON_EXECUTABLE=/usr/bin/python3
    make -j\$(nproc)
    cp zerotrace_core*.so /opt/zerotrace/
"

# ── Generate PKI keypair ──────────────────────────────────────────────────
log "Generating PKI keypair..."
chroot "$WORK_DIR/squashfs-edit" bash -c "
    cd /opt/zerotrace
    python3 -c 'from cert.signer import generate_keypair; generate_keypair()'
"

# Copy public key out to the build machine (distribute with releases)
cp "$WORK_DIR/squashfs-edit/opt/zerotrace/cert/keys/zerotrace_public.pem" \
   "./zerotrace_public_${ZEROTRACE_VERSION}.pem"
log "Public key saved to: zerotrace_public_${ZEROTRACE_VERSION}.pem"

# ── Configure auto-launch ─────────────────────────────────────────────────
log "Configuring auto-launch..."

# Install systemd service
cp iso/zerotrace_autostart.service \
   "$WORK_DIR/squashfs-edit/etc/systemd/system/zerotrace.service"

chroot "$WORK_DIR/squashfs-edit" bash -c "
    systemctl enable zerotrace.service 2>/dev/null || true
"

# Create certificate export mount point
mkdir -p "$WORK_DIR/squashfs-edit/mnt/usb_export"

# ── Unmount pseudo-filesystems ────────────────────────────────────────────
log "Cleaning up chroot mounts..."
umount "$WORK_DIR/squashfs-edit/dev/pts" || true
umount "$WORK_DIR/squashfs-edit/dev"     || true
umount "$WORK_DIR/squashfs-edit/proc"    || true
umount "$WORK_DIR/squashfs-edit/sys"     || true

# ── Repack squashfs ───────────────────────────────────────────────────────
log "Repacking squashfs (this takes a while)..."
rm -f "$SQUASHFS_PATH"
mksquashfs "$WORK_DIR/squashfs-edit" "$SQUASHFS_PATH" \
    -comp xz \
    -Xbcj x86 \
    -b 1M \
    -no-progress

# Update filesystem size file
du -sx --block-size=1 "$WORK_DIR/squashfs-edit" | cut -f1 > \
    "$(dirname $SQUASHFS_PATH)/filesystem.size"

# ── Copy ISO skeleton to new ISO directory ────────────────────────────────
log "Building new ISO structure..."
cp -rp "$WORK_DIR/iso-extract"/* "$WORK_DIR/iso-new/"

# Replace squashfs
cp "$SQUASHFS_PATH" "$(dirname $SQUASHFS_PATH | sed "s|$WORK_DIR/iso-extract|$WORK_DIR/iso-new|g")/"

# Replace GRUB config
find "$WORK_DIR/iso-new" -name "grub.cfg" -exec cp iso/grub.cfg {} \;

# Update md5 checksums
cd "$WORK_DIR/iso-new"
find . -type f -not -name "md5sum.txt" | sort | xargs md5sum > md5sum.txt
cd - > /dev/null

# ── Build final ISO ───────────────────────────────────────────────────────
log "Building final bootable ISO..."

# Find the EFI boot image
EFI_IMG=$(find "$WORK_DIR/iso-new" -name "efi.img" | head -1)
BIOS_IMG=$(find "$WORK_DIR/iso-new" -name "bios.img" | head -1)
BOOT_CAT=$(find "$WORK_DIR/iso-new" -name "boot.catalog" -o -name "boot.cat" | head -1)

xorriso -as mkisofs \
    -iso-level 3 \
    -full-iso9660-filenames \
    -volid "ZEROTRACE_${ZEROTRACE_VERSION//./_}" \
    -eltorito-boot "${BIOS_IMG#$WORK_DIR/iso-new/}" \
    -no-emul-boot \
    -boot-load-size 4 \
    -boot-info-table \
    --eltorito-catalog "${BOOT_CAT#$WORK_DIR/iso-new/}" \
    --efi-boot "${EFI_IMG#$WORK_DIR/iso-new/}" \
    -efi-boot-part \
    --efi-boot-image \
    --protective-msdos-label \
    -output "$OUTPUT_ISO" \
    "$WORK_DIR/iso-new"

# ── Cleanup ───────────────────────────────────────────────────────────────
log "Cleaning up build directory..."
rm -rf "$WORK_DIR"

# ── Done ──────────────────────────────────────────────────────────────────
ISO_SIZE=$(du -sh "$OUTPUT_ISO" | cut -f1)
log "════════════════════════════════════════════════════════"
log "  BUILD COMPLETE"
log "  Output: $OUTPUT_ISO  ($ISO_SIZE)"
log "  Public key: zerotrace_public_${ZEROTRACE_VERSION}.pem"
log ""
log "  Flash to USB with:"
log "    sudo dd if=$OUTPUT_ISO of=/dev/sdX bs=4M status=progress"
log "    (replace /dev/sdX with your USB drive)"
log "════════════════════════════════════════════════════════"
