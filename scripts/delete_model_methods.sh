#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SOURCE_ROOT="${1:-$SCRIPT_DIR/Odoo_sync_compiled_script}"
TARGET_ROOT="${2:-$SCRIPT_DIR/Odoo_sync_ready_for_run_script}"
PYC_TAGS=("310" "311" "312")

if [[ ! -d "$SOURCE_ROOT" ]]; then
    echo "Source add-ons root not found: $SOURCE_ROOT" >&2
    exit 1
fi

if ! command -v rsync >/dev/null 2>&1; then
    echo "Required command not found: rsync" >&2
    exit 1
fi

rm -rf "$TARGET_ROOT"
mkdir -p "$TARGET_ROOT"

echo "Copying source tree:"
echo "  from: $SOURCE_ROOT"
echo "  to:   $TARGET_ROOT"
rsync -a \
    --delete \
    --exclude 'scripts' \
    "$SOURCE_ROOT"/ "$TARGET_ROOT"/

FOUND_PY_FILE=0
REMOVED_PY_FILE=0
SKIPPED_PY_FILE=0

echo
echo "Removing Python source files that have versioned __pycache__ files"

while IFS= read -r -d '' py_file; do
    FOUND_PY_FILE=1

    base_name="$(basename "$py_file")"
    package_init="$(dirname "$py_file")/__init__.py"
    module_name="${base_name%.py}"
    cache_dir="$(dirname "$py_file")/__pycache__"

    if [[ "$base_name" == "__manifest__.py" || "$base_name" == "__init__.py" ]]; then
        echo "Keeping loader/source file: $py_file"
        SKIPPED_PY_FILE=1
        continue
    fi

    if [[ ! -f "$package_init" ]] || ! grep -q '_VersionedPycFinder' "$package_init"; then
        echo "Keeping source without package loader: $py_file"
        SKIPPED_PY_FILE=1
        continue
    fi

    missing_pyc=0
    for py_tag in "${PYC_TAGS[@]}"; do
        if [[ ! -f "$cache_dir/$module_name.cpython-${py_tag}.pyc" ]]; then
            echo "Missing compiled file: $cache_dir/$module_name.cpython-${py_tag}.pyc" >&2
            missing_pyc=1
        fi
    done

    if [[ "$missing_pyc" -ne 0 ]]; then
        echo "Skipping uncompiled source: $py_file" >&2
        SKIPPED_PY_FILE=1
        continue
    fi

    echo "Removing: $py_file"
    rm -f "$py_file"
    REMOVED_PY_FILE=1
done < <(find "$TARGET_ROOT" -type f -name '*.py' ! -path '*/scripts/*' -print0 | sort -z)

if [[ "$FOUND_PY_FILE" -eq 0 ]]; then
    echo "No Python files found under: $TARGET_ROOT" >&2
    exit 1
fi

if [[ "$REMOVED_PY_FILE" -eq 0 ]]; then
    echo "No Python source files were removed under: $TARGET_ROOT"
fi

if [[ "$SKIPPED_PY_FILE" -ne 0 ]]; then
    echo "Some Python files were kept; see messages above."
fi
