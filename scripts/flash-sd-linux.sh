#!/bin/bash
# Flash an sensorbox image to an SD card for local development testing.
#
# Usage:
#   ./scripts/flash-sd-linux.sh <image-substring>
#   ./scripts/flash-sd-linux.sh    (interactive selection of image + disk)
#
# The image is expected to be in public/store/*/. The script finds it
# by filename across all build hash directories.
#
# Requires: util-linux (lsblk), coreutils. fzf is used for interactive
# selection when available, otherwise numbered menus.

set -euo pipefail

STORE_DIR="$(cd "$(dirname "$0")/.." && pwd)/public/store"
LOCAL_DIR="/tmp/sensorbox-flash"

die() { echo "ERROR: $*" >&2; exit 1; }

[[ "$(uname)" == "Linux" ]] || die "This script is for Linux only (macOS: use flash-sd-macos.sh)"
command -v lsblk >/dev/null 2>&1 || die "lsblk not found — install util-linux"

# --- Image selection ---

# Newest-first list of "<epoch> <path>" for a find name pattern.
list_images() {
    find "$STORE_DIR" -name "$1" -type f -printf '%T@ %p\n' 2>/dev/null | sort -rn
}

if [[ $# -ge 1 ]]; then
    IMAGE_PATH=$(list_images "*${1}*.img.gz" | head -1 | cut -d' ' -f2-)
    [[ -n "$IMAGE_PATH" ]] || die "No image matching '$1' found in $STORE_DIR"
else
    IMAGE_LIST=$(list_images '*squashfs-sysupgrade.img.gz' | while read -r _ f; do
        ts=$(stat -c '%y' "$f" | cut -c1-16)
        echo "[$ts]  $(basename "$f")|$f"
    done)
    [[ -n "$IMAGE_LIST" ]] || die "No images found in $STORE_DIR"

    if command -v fzf >/dev/null 2>&1; then
        SELECTION=$(echo "$IMAGE_LIST" | cut -d'|' -f1 | fzf --height=15 --reverse --prompt="Select image: ") || die "No image selected"
        IMAGE_PATH=$(echo "$IMAGE_LIST" | grep -F "$SELECTION" | head -1 | cut -d'|' -f2)
    else
        echo "Available images (newest first):"
        echo
        echo "$IMAGE_LIST" | cut -d'|' -f1 | cat -n
        echo
        read -rp "Enter number: " NUM
        IMAGE_PATH=$(echo "$IMAGE_LIST" | sed -n "${NUM}p" | cut -d'|' -f2)
    fi
    [[ -n "$IMAGE_PATH" ]] || die "Invalid selection"
fi

IMAGE_NAME=$(basename "$IMAGE_PATH")
echo "Image: $IMAGE_NAME"

# --- Disk selection ---

# Whole disk backing the root filesystem, so we never offer to erase it.
# findmnt may report a btrfs subvolume suffix (/dev/mapper/root[/@]) and the
# source may sit behind LVM/LUKS, so strip the suffix and walk the inverse
# device tree up to the first TYPE=disk ancestor.
root_source=$(findmnt -no SOURCE / 2>/dev/null | sed 's/\[.*\]$//')
ROOT_DISK=""
if [[ -n "$root_source" ]]; then
    ROOT_DISK=$(lsblk -nsro NAME,TYPE "$root_source" 2>/dev/null | awk '$2=="disk"{print $1; exit}')
fi

# Build a list of removable/hotplug disks (SD readers report RM=0 HOTPLUG=1,
# USB sticks usually RM=1). Shows device name, size, and model.
select_disk() {
    local DISK_LIST=""
    local line NAME SIZE MODEL TRAN RM HOTPLUG TYPE
    # -P gives quoted KEY="value" pairs, so models containing spaces parse cleanly.
    while read -r line; do
        NAME=""; SIZE=""; MODEL=""; TRAN=""; RM=""; HOTPLUG=""; TYPE=""
        eval "$line"
        [[ "$TYPE" == "disk" ]] || continue
        [[ "$NAME" == zram* || "$NAME" == loop* ]] && continue
        [[ -n "$ROOT_DISK" && "$NAME" == "$ROOT_DISK" ]] && continue
        [[ "$RM" == "1" || "$HOTPLUG" == "1" || "$TRAN" == "usb" ]] || continue
        # lsblk reports no MODEL for SD/MMC cards; sysfs has the card name.
        [[ -n "$MODEL" ]] || MODEL=$(cat "/sys/block/${NAME}/device/name" 2>/dev/null || true)
        [[ -n "$MODEL" ]] || MODEL="Unknown"
        DISK_LIST+="/dev/${NAME}  ${SIZE}  ${MODEL}  (${TRAN:-unknown})|/dev/${NAME}"$'\n'
    done < <(lsblk -dP -o NAME,SIZE,MODEL,TRAN,RM,HOTPLUG,TYPE)
    DISK_LIST=${DISK_LIST%$'\n'}

    [[ -n "$DISK_LIST" ]] || die "No removable/hotplug disks found. Insert an SD card and try again."

    local selected_disk
    if command -v fzf >/dev/null 2>&1; then
        local selection
        selection=$(echo "$DISK_LIST" | cut -d'|' -f1 | fzf --height=10 --reverse --prompt="Select target disk: ") || die "No disk selected"
        selected_disk=$(echo "$DISK_LIST" | grep -F "$selection" | head -1 | cut -d'|' -f2)
    else
        {
            echo "Removable disks:"
            echo
            echo "$DISK_LIST" | cut -d'|' -f1 | cat -n
            echo
        } >&2
        read -rp "Enter number: " NUM
        selected_disk=$(echo "$DISK_LIST" | sed -n "${NUM}p" | cut -d'|' -f2)
    fi

    [[ -n "$selected_disk" ]] || die "Invalid selection"
    echo "$selected_disk"
}

SD_DISK=$(select_disk)
[[ -b "$SD_DISK" ]] || die "$SD_DISK is not a block device"

# util-linux < 2.37 only has the singular MOUNTPOINT column.
if lsblk -no MOUNTPOINTS "$SD_DISK" >/dev/null 2>&1; then
    MP_COL=MOUNTPOINTS
else
    MP_COL=MOUNTPOINT
fi

echo "Target: $SD_DISK"
lsblk -o "NAME,SIZE,MODEL,TRAN,$MP_COL" "$SD_DISK" | sed 's/^/  /'
echo
echo "This will ERASE $SD_DISK. Press Enter to continue or Ctrl-C to abort."
read -r

mkdir -p "$LOCAL_DIR"

# Decompress — OpenWrt images have trailing metadata that gzip warns about
echo "==> Decompressing..."
gzip -dc "$IMAGE_PATH" > "$LOCAL_DIR/${IMAGE_NAME%.gz}" 2>/dev/null || true
LOCAL_IMG="$LOCAL_DIR/${IMAGE_NAME%.gz}"
[[ -s "$LOCAL_IMG" ]] || die "Decompression produced empty file"

IMG_SIZE=$(stat -c%s "$LOCAL_IMG")
IMG_BLOCKS=$(( (IMG_SIZE + 1048575) / 1048576 ))
echo "    Image: $IMG_SIZE bytes ($IMG_BLOCKS MiB)"

echo "==> Computing source checksum..."
SRC_SHA=$(sha256sum "$LOCAL_IMG" | awk '{print $1}')
echo "    Source: $SRC_SHA"

echo "==> Unmounting partitions on $SD_DISK..."
while read -r part; do
    [[ -n "$part" ]] || continue
    if command -v udisksctl >/dev/null 2>&1; then
        udisksctl unmount -b "$part" >/dev/null 2>&1 || true
    fi
    sudo umount "$part" 2>/dev/null || true
done < <(lsblk -lnpo "NAME,$MP_COL" "$SD_DISK" | awk 'NF>1 {print $1}')

# Anything still mounted means the write would corrupt a live filesystem.
if lsblk -lnpo "$MP_COL" "$SD_DISK" | grep -q '[^[:space:]]'; then
    die "Partitions on $SD_DISK are still mounted — unmount them and retry"
fi

echo "==> Writing to $SD_DISK..."
sudo dd if="$LOCAL_IMG" of="$SD_DISK" bs=1M conv=fsync status=progress
sync

echo "==> Flushing buffers before verify..."
sudo blockdev --flushbufs "$SD_DISK" 2>/dev/null || true
sudo sh -c 'echo 3 > /proc/sys/vm/drop_caches' 2>/dev/null || true
sleep 1

# Read back to a file rather than piping into sha256sum: `head -c` closing the
# pipe early makes dd's exit status meaningless, so a failed read would be
# indistinguishable from a corrupt card. iflag=direct bypasses the page cache;
# not every device/kernel combination supports it, hence the plain retry.
echo "==> Verifying write..."
READBACK="$LOCAL_DIR/readback.img"
sudo dd if="$SD_DISK" of="$READBACK" bs=1M count="$IMG_BLOCKS" iflag=direct status=none 2>/dev/null \
    || sudo dd if="$SD_DISK" of="$READBACK" bs=1M count="$IMG_BLOCKS" status=none \
    || die "Failed to read back from $SD_DISK"
sudo chown "$(id -u):$(id -g)" "$READBACK"
truncate -s "$IMG_SIZE" "$READBACK"
DISK_SHA=$(sha256sum "$READBACK" | awk '{print $1}')
rm -f "$READBACK"
echo "    Disk:   $DISK_SHA"

if [[ "$SRC_SHA" == "$DISK_SHA" ]]; then
    echo "==> Checksum OK — image verified"
else
    die "Checksum MISMATCH — flash may be corrupted, try again"
fi

if command -v udisksctl >/dev/null 2>&1 && udisksctl power-off -b "$SD_DISK" >/dev/null 2>&1; then
    echo "==> Done! SD card ejected safely."
elif eject "$SD_DISK" 2>/dev/null; then
    echo "==> Done! SD card ejected safely."
else
    echo "==> Done! Safe to remove $SD_DISK."
fi
