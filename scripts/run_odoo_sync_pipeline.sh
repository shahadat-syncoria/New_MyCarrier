#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    cat <<EOF
Usage:
  run_odoo_sync_pipeline.sh [SOURCE_ROOT] [FINAL_TARGET]

Arguments:
  SOURCE_ROOT   Optional. If omitted, the script prompts for it.
  FINAL_TARGET  Optional. If omitted, the script prompts for it.

Environment:
  KEEP_INTERMEDIATES=1   Keep the temporary workspace instead of deleting it.

Any directory named "scripts" inside SOURCE_ROOT is skipped during the full process.
The source is compiled directly; no base-to-split transformation is performed.
Final output keeps package __init__.py loaders and uses versioned __pycache__ files.
EOF
}

expand_home() {
    local path="$1"
    if [[ "$path" == "~" ]]; then
        printf '%s\n' "$HOME"
    elif [[ "$path" == ~/* ]]; then
        printf '%s\n' "$HOME/${path#~/}"
    else
        printf '%s\n' "$path"
    fi
}

run_step() {
    local label="$1"
    shift

    echo
    echo "==> $label"
    "$@"
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
fi

SOURCE_ROOT="${1:-}"
FINAL_TARGET="${2:-}"

if [[ -z "$SOURCE_ROOT" ]]; then
    read -r -p "Enter source directory: " SOURCE_ROOT
fi

SOURCE_ROOT="$(expand_home "$SOURCE_ROOT")"

if [[ -z "$SOURCE_ROOT" ]]; then
    echo "Source directory is required." >&2
    exit 1
fi

if [[ ! -d "$SOURCE_ROOT" ]]; then
    echo "Source add-ons root not found: $SOURCE_ROOT" >&2
    exit 1
fi

for required_command in mktemp realpath; do
    if ! command -v "$required_command" >/dev/null 2>&1; then
        echo "Required command not found: $required_command" >&2
        exit 1
    fi
done

SOURCE_ROOT="$(realpath "$SOURCE_ROOT")"

if [[ -z "$FINAL_TARGET" ]]; then
    read -r -p "Enter final target location: " FINAL_TARGET
fi

FINAL_TARGET="$(expand_home "$FINAL_TARGET")"

if [[ -z "$FINAL_TARGET" ]]; then
    echo "Final target location is required." >&2
    exit 1
fi

FINAL_TARGET="$(realpath -m "$FINAL_TARGET")"

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/odoo_sync_pipeline.XXXXXX")"
LEFT_TARGET="$WORK_DIR/Odoo_sync_compile_left_script"
COMPILED_TARGET="$WORK_DIR/Odoo_sync_compiled_script"
PIPELINE_SOURCE="$SOURCE_ROOT"

cleanup() {
    if [[ "${KEEP_INTERMEDIATES:-0}" == "1" ]]; then
        echo
        echo "Intermediate files kept at: $WORK_DIR"
        return
    fi
    rm -rf "$WORK_DIR"
}

trap cleanup EXIT

mkdir -p "$(dirname "$FINAL_TARGET")"

if [[ "$FINAL_TARGET" == "$SOURCE_ROOT" ]]; then
    echo "Final target must be different from the source directory." >&2
    exit 1
fi

if [[ "$FINAL_TARGET" == "$SOURCE_ROOT/"* ]]; then
    if ! command -v rsync >/dev/null 2>&1; then
        echo "Required command not found: rsync" >&2
        exit 1
    fi

    TARGET_RELATIVE="${FINAL_TARGET#"$SOURCE_ROOT/"}"
    PIPELINE_SOURCE="$WORK_DIR/source_without_previous_target"
    mkdir -p "$PIPELINE_SOURCE"
    rsync -a \
        --exclude '.git' \
        --exclude 'scripts' \
        --exclude '__pycache__' \
        --exclude '*.pyc' \
        --exclude "/$TARGET_RELATIVE/" \
        "$SOURCE_ROOT"/ "$PIPELINE_SOURCE"/
fi

echo "Source root: $SOURCE_ROOT"
echo "Final target: $FINAL_TARGET"
echo "Workspace: $WORK_DIR"

run_step \
    "Prepare source for compilation (without base split)" \
    "$SCRIPT_DIR/transform_splited_to_left.sh" \
    "$PIPELINE_SOURCE" \
    "$LEFT_TARGET"

run_step \
    "Compile Python sources for all configured Python versions" \
    "$SCRIPT_DIR/compile_models_all_versions.sh" \
    "$LEFT_TARGET" \
    "$COMPILED_TARGET"

run_step \
    "Delete compiled Python sources into final target" \
    "$SCRIPT_DIR/delete_model_methods.sh" \
    "$COMPILED_TARGET" \
    "$FINAL_TARGET"

echo
echo "Pipeline completed successfully."
echo "Final output: $FINAL_TARGET"
