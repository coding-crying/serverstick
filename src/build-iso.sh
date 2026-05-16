#!/usr/bin/env bash
# build-iso.sh — Build a ServerStick installer ISO from stock Debian netinst
#
# Usage:
#   sudo ./build-iso.sh --key sk-ss-YOUR_STARTER_KEY_HERE
#   sudo ./build-iso.sh --key sk-ss-xxx --api-base https://tokenrouter.ai/v1
#   sudo ./build-iso.sh --key sk-ss-xxx --output serverstick-v0.1.iso
#
# Requires: xorriso, curl, cpio, gzip
#
# This script:
#   1. Downloads the latest Debian 12 netinst ISO
#   2. Unpacks it
#   3. Injects preseed.cfg (with your starter key)
#   4. Patches the bootloader for auto-install
#   5. Repacks as a bootable ISO
#
# The resulting ISO is a fully automated ServerStick installer.
# Boot from USB → Debian installs → get.serverstick.sh runs → setup wizard starts.

set -euo pipefail

# ─── Defaults ─────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEBIAN_VERSION="12.11.0"
DEBIAN_ISO="debian-${DEBIAN_VERSION}-amd64-netinst.iso"
DEBIAN_URL="https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/${DEBIAN_ISO}"
OUTPUT="${SCRIPT_DIR}/../serverstick.iso"
PRESEED_TEMPLATE="${SCRIPT_DIR}/../config/preseed.cfg.template"
BOOTSTRAP_SCRIPT="${SCRIPT_DIR}/bootstrap/get.serverstick.sh"
WORK_DIR="/tmp/serverstick-iso-build"
STARTER_KEY=""
API_BASE="https://api.openai.com/v1"

# ─── Parse Args ────────────────────────────────────────────────────────────────

usage() {
    echo "Usage: $0 --key STARTER_KEY [--api-base URL] [--output FILE] [--cache-dir DIR]"
    echo ""
    echo "  --key KEY        Preseeded starter API key (~20 credits). Required."
    echo "  --api-base URL   OpenAI-compatible API base. Default: https://api.openai.com/v1"
    echo "  --output FILE    Output ISO path. Default: serverstick.iso"
    echo "  --cache-dir DIR  Working directory. Default: /tmp/serverstick-iso-build"
    echo "  --help           Show this help"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --key)        STARTER_KEY="$2"; shift 2 ;;
        --api-base)   API_BASE="$2"; shift 2 ;;
        --output)     OUTPUT="$2"; shift 2 ;;
        --cache-dir)  WORK_DIR="$2"; shift 2 ;;
        --help|-h)    usage; exit 0 ;;
        *)            echo "Unknown option: $1"; usage; exit 1 ;;
    esac
done

if [[ -z "${STARTER_KEY}" ]]; then
    echo "ERROR: --key is required. This is the preseeded starter API key."
    echo "Usage: $0 --key sk-ss-YOUR_KEY_HERE"
    exit 1
fi

# ─── Dependencies ──────────────────────────────────────────────────────────────

check_deps() {
    local missing=()
    for cmd in xorriso cpio gzip curl; do
        command -v "$cmd" &>/dev/null || missing+=("$cmd")
    done
    if [[ ${#missing[@]} -gt 0 ]]; then
        echo "Missing dependencies: ${missing[*]}"
        echo "Install with: apt install -y xorriso cpio gzip curl"
        exit 1
    fi
}

# ─── Download ──────────────────────────────────────────────────────────────────

download_debian_iso() {
    local iso_path="${WORK_DIR}/${DEBIAN_ISO}"

    if [[ -f "${iso_path}" ]]; then
        echo "[build] Found cached ${DEBIAN_ISO}, skipping download."
        return 0
    fi

    echo "[build] Downloading Debian ${DEBIAN_VERSION} netinst ISO..."
    mkdir -p "${WORK_DIR}"
    curl -fSL --progress-bar -o "${iso_path}" "${DEBIAN_URL}"
    echo "[build] Download complete."
}

# ─── Unpack ────────────────────────────────────────────────────────────────────

unpack_iso() {
    echo "[build] Unpacking ISO..."

    local iso_path="${WORK_DIR}/${DEBIAN_ISO}"
    local mount_dir="${WORK_DIR}/iso-mount"
    local repack_dir="${WORK_DIR}/iso-repack"

    mkdir -p "${mount_dir}" "${repack_dir}"

    # Mount the ISO
    mount -o loop,ro "${iso_path}" "${mount_dir}"

    # Copy everything
    rsync -a "${mount_dir}/" "${repack_dir}/"
    chmod -R u+w "${repack_dir}"

    # Unmount
    umount "${mount_dir}"
    rmdir "${mount_dir}"

    echo "[build] ISO unpacked to ${repack_dir}"
}

# ─── Inject Preseed ────────────────────────────────────────────────────────────

inject_preseed() {
    echo "[build] Injecting preseed.cfg into initrd..."

    local repack_dir="${WORK_DIR}/iso-repack"
    local initrd_dir="${WORK_DIR}/initrd-work"

    # Generate preseed.cfg from template
    echo "[build] Generating preseed.cfg with starter key..."
    sed \
        -e "s|%%STARTER_KEY%%|${STARTER_KEY}|g" \
        -e "s|https://api.openri.com/v1|${API_BASE}|g" \
        "${PRESEED_TEMPLATE}" > "${WORK_DIR}/preseed.cfg"

    echo "[build] Preseed generated. Key prefix: ${STARTER_KEY:0:8}..."

    # Unpack initrd
    mkdir -p "${initrd_dir}"
    cd "${initrd_dir}"
    gunzip < "${repack_dir}/install.amd/initrd.gz" | cpio -idm 2>/dev/null

    # Inject preseed.cfg
    cp "${WORK_DIR}/preseed.cfg" "${initrd_dir}/preseed.cfg"

    # Repack initrd
    find . | cpio -o -H newc 2>/dev/null | gzip -9 > "${repack_dir}/install.amd/initrd.gz"
    cd "${SCRIPT_DIR}"

    # Clean up initrd work dir
    rm -rf "${initrd_dir}"

    echo "[build] Preseed injected into initrd."
}

# ─── Patch Bootloader ──────────────────────────────────────────────────────────

patch_bootloader() {
    echo "[build] Patching bootloader for auto-install..."

    local repack_dir="${WORK_DIR}/iso-repack"

    # Patch ISOLINUX config (BIOS boot)
    local isolinux_cfg="${repack_dir}/isolinux/isolinux.cfg"
    if [[ -f "${isolinux_cfg}" ]]; then
        cat > "${repack_dir}/isolinux/isolinux.cfg" <<'EOF'
# ServerStick — Auto-install bootloader
DEFAULT autoinstall
PROMPT 0
TIMEOUT 1

LABEL autoinstall
    KERNEL /install.amd/vmlinuz
    APPEND initrd=/install.amd/initrd.gz auto=true priority=critical preseed/file=/preseed.cfg ---
EOF
        echo "[build] ISOLINUX config patched."
    fi

    # Patch GRUB config (UEFI boot)
    local grub_cfg="${repack_dir}/boot/grub/grub.cfg"
    if [[ -f "${grub_cfg}" ]]; then
        cat > "${repack_dir}/boot/grub/grub.cfg" <<'EOF'
# ServerStick — Auto-install GRUB config
set default=0
set timeout=1

menuentry "ServerStick Auto-Install" {
    linux /install.amd/vmlinuz auto=true priority=critical preseed/file=/preseed.cfg ---
    initrd /install.amd/initrd.gz
}
EOF
        echo "[build] GRUB config patched."
    fi

    echo "[build] Bootloader patched for全自动安装."
}

# ─── Repack ISO ────────────────────────────────────────────────────────────────

repack_iso() {
    echo "[build] Repacking ISO..."

    local repack_dir="${WORK_DIR}/iso-repack"

    # Find isohybrid-mbr.bin
    local mbr_bin=""
    for path in /usr/lib/ISOLINUX/isohybrid-mbr.bin /usr/share/syslinux/isohybrid-mbr.bin; do
        if [[ -f "${path}" ]]; then
            mbr_bin="${path}"
            break
        fi
    done

    if [[ -z "${mbr_bin}" ]]; then
        echo "WARNING: isohybrid-mbr.bin not found. ISO may not be hybrid-bootable."
        echo "Install: apt install -y isolinux syslinux"
        # Build without MBR hybrid but still create ISO
        xorriso -as mkisofs \
            -o "${OUTPUT}" \
            -c isolinux/boot.cat \
            -b isolinux/isolinux.bin \
            -no-emul-boot -boot-load-size 4 -boot-info-table \
            "${repack_dir}/"
    else
        xorriso -as mkisofs \
            -o "${OUTPUT}" \
            -isohybrid-mbr "${mbr_bin}" \
            -c isolinux/boot.cat \
            -b isolinux/isolinux.bin \
            -no-emul-boot -boot-load-size 4 -boot-info-table \
            -eltorito-alt-boot \
            -e boot/grub/efi.img \
            -no-emul-boot \
            -isohybrid-gpt-basdat \
            "${repack_dir}/"
    fi

    echo "[build] ISO created: ${OUTPUT}"
    echo "[build] Size: $(du -h "${OUTPUT}" | cut -f1)"
}

# ─── Cleanup ──────────────────────────────────────────────────────────────────

cleanup() {
    echo "[build] Cleaning up..."
    rm -rf "${WORK_DIR}/iso-repack" "${WORK_DIR}/initrd-work" "${WORK_DIR}/preseed.cfg"
    # Keep the downloaded ISO for caching
    echo "[build] Cached ISO kept at ${WORK_DIR}/${DEBIAN_ISO}"
    echo "[build] Run 'rm -rf ${WORK_DIR}' to fully clean up."
}

# ─── Main ──────────────────────────────────────────────────────────────────────

main() {
    echo "╔══════════════════════════════════════╗"
    echo "║   ServerStick ISO Builder v0.1       ║"
    echo "║   Plug in. Take back your data.      ║"
    echo "╚══════════════════════════════════════╝"
    echo ""

    check_deps
    download_debian_iso
    unpack_iso
    inject_preseed
    patch_bootloader
    repack_iso
    cleanup

    echo ""
    echo "════════════════════════════════════════"
    echo "  ServerStick ISO built successfully!"
    echo "════════════════════════════════════════"
    echo ""
    echo "  ISO: ${OUTPUT}"
    echo "  Key: ${STARTER_KEY:0:8}..."
    echo ""
    echo "  Write to USB:"
    echo "    sudo dd if=${OUTPUT} of=/dev/sdX bs=4M status=progress && sync"
    echo ""
    echo "  Test in QEMU:"
    echo "    qemu-system-x86_64 -enable-kvm -m 4096 -drive file=test.qcow2,format=qcow2 -cdrom ${OUTPUT} -boot d"
    echo ""
}

main "$@"