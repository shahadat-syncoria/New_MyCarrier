#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SOURCE_ROOT="${1:-$SCRIPT_DIR/Odoo_sync_compile_left_script}"
TARGET_ROOT="${2:-$SCRIPT_DIR/Odoo_sync_compiled_script}"
PYTHONS=("python3.10" "python3.11" "python3.12" "python3.13" "python3.14")

if [[ ! -d "$SOURCE_ROOT" ]]; then
    echo "Source add-ons root not found: $SOURCE_ROOT" >&2
    exit 1
fi

declare -a PY_FILES=()
FAILED=0

rm -rf "$TARGET_ROOT"
mkdir -p "$TARGET_ROOT"

if ! command -v rsync >/dev/null 2>&1; then
    echo "Required command not found: rsync" >&2
    exit 1
fi

echo "Copying source tree:"
echo "  from: $SOURCE_ROOT"
echo "  to:   $TARGET_ROOT"
rsync -a \
    --delete \
    --exclude 'scripts' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    "$SOURCE_ROOT"/ "$TARGET_ROOT"/

while IFS= read -r -d '' py_file; do
    PY_FILES+=("$py_file")
done < <(find "$TARGET_ROOT" -type f -name '*.py' ! -path '*/scripts/*' -print0 | sort -z)

if [[ ${#PY_FILES[@]} -eq 0 ]]; then
    echo "No Python files found under: $TARGET_ROOT" >&2
    exit 1
fi

for py in "${PYTHONS[@]}"; do
    if ! command -v "$py" >/dev/null 2>&1; then
        echo "Required Python interpreter not found: $py" >&2
        FAILED=1
    fi
done

if [[ "$FAILED" -ne 0 ]]; then
    exit "$FAILED"
fi

echo
echo "Compiling ${#PY_FILES[@]} Python files under: $TARGET_ROOT"

for py in "${PYTHONS[@]}"; do
    echo
    echo "==> $py"
    echo "Writing version-tagged __pycache__ files"
    if ! "$py" -m compileall -q "$TARGET_ROOT"; then
        FAILED=1
        echo "Failed: $py version-tagged compile under $TARGET_ROOT" >&2
    fi
done

if [[ "$FAILED" -eq 0 ]]; then
    missing_pyc=0
    for py_file in "${PY_FILES[@]}"; do
        module_name="$(basename "$py_file" .py)"
        cache_dir="$(dirname "$py_file")/__pycache__"
        for py in "${PYTHONS[@]}"; do
            py_tag="${py#python}"
            py_tag="${py_tag//./}"
            if [[ ! -f "$cache_dir/$module_name.cpython-${py_tag}.pyc" ]]; then
                echo "Missing compiled file: $cache_dir/$module_name.cpython-${py_tag}.pyc" >&2
                missing_pyc=1
            fi
        done
    done
    if [[ "$missing_pyc" -ne 0 ]]; then
        FAILED=1
    fi
fi

exit "$FAILED"
