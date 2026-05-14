#!/usr/bin/env bash
# iso/install_deps.sh
# Runs inside Ubuntu 22.04 chroot — installs all ZeroTrace runtime dependencies
# Called by build_iso.sh via chroot

set -e

echo "[ZeroTrace] Installing runtime dependencies..."

export DEBIAN_FRONTEND=noninteractive

apt-get update -qq

# ADB and storage tools
apt-get install -y -qq \
    adb \
    mmc-utils \
    nvme-cli \
    hdparm \
    smartmontools \
    sg3-utils \
    util-linux \
    lsblk

# Python runtime
apt-get install -y -qq \
    python3 \
    python3-pip \
    python3-dev

# Python packages
pip3 install --quiet \
    reportlab \
    cryptography \
    pybind11 \
    scipy \
    numpy

# C++ build tools (needed if building zerotrace_core.so inside the chroot)
apt-get install -y -qq \
    build-essential \
    cmake \
    libssl-dev \
    libblkid-dev

# Terminal emulator for TUI (in case default is missing)
apt-get install -y -qq \
    ncurses-bin \
    python3-curses

# Clean up to reduce ISO size
apt-get clean
rm -rf /var/lib/apt/lists/*
pip3 cache purge

echo "[ZeroTrace] Dependencies installed."
