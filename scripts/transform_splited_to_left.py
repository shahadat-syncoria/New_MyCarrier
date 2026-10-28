#!/usr/bin/env python3

from __future__ import annotations

import ast
import re
import shutil
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_SOURCE = SCRIPT_DIR / "Odoo_sync_splited_script"
DEFAULT_TARGET = SCRIPT_DIR / "Odoo_sync_compile_left_script"
MIXIN_MODELS = {
    "mail.thread",
    "mail.activity.mixin",
    "portal.mixin",
    "pos.bus.mixin",
    "pos.load.mixin",
}
RELATIVE_IMPORT_RE = re.compile(
    r"(?m)^(?P<indent>\s*)from (?P<dots>\.{2,})(?P<module>[A-Za-z_][\w\.]*)? import (?P<rest>.+)$"
)
HELPER_COPIES = (
    (
        "os_delivery/delivery_apps/delivery_canada_post/models/canpost_request.py",
        "os_delivery/delivery_apps/delivery_canada_post/models/table_models/canpost_request.py",
    ),
    (
        "os_payment/payment_apps/odoo_clover_cloud/models/clover_request.py",
        "os_payment/payment_apps/odoo_clover_cloud/models/table_models/clover_request.py",
    ),
    (
        "os_payment/payment_apps/odoo_bambora_checkout/models/utils.py",
        "os_payment/payment_apps/odoo_bambora_checkout/models/table_models/utils.py",
    ),
)
HELPER_COPY_TARGETS = {Path(dest_rel) for _, dest_rel in HELPER_COPIES}
RUNTIME_IMPORT_REWRITES = {
    "from odoo.addons.os_delivery.delivery_apps.delivery_canada_post.models.canpost_request import CanadaPostRequest": (
        "from odoo.addons.os_delivery.delivery_apps.delivery_canada_post.models.table_models.canpost_request "
        "import CanadaPostRequest"
    ),
    "from odoo.addons.os_payment.payment_apps.odoo_clover_cloud.models.clover_request import CloverRequest": (
        "from odoo.addons.os_payment.payment_apps.odoo_clover_cloud.models.table_models.clover_request "
        "import CloverRequest"
    ),
    "from odoo.addons.os_payment.payment_apps.odoo_bambora_checkout.models.utils import (": (
        "from odoo.addons.os_payment.payment_apps.odoo_bambora_checkout.models.table_models.utils import ("
    ),
}
TABLE_IMPORT_REWRITES = {
    "from odoo.addons.os_payment.payment_apps.odoo_bambora_checkout.models.utils import (": (
        "from odoo.addons.os_payment.payment_apps.odoo_bambora_checkout.models.table_models.utils import ("
    ),
    "from odoo.addons.os_delivery.delivery_apps.delivery_canada_post.models.canpost_request import CanadaPostRequest": (
        "from odoo.addons.os_delivery.delivery_apps.delivery_canada_post.models.table_models.canpost_request "
        "import CanadaPostRequest"
    ),
}
BAMBORA_UTILS_PATH = Path("os_payment/payment_apps/odoo_bambora_checkout/models/utils.py")
BAMBORA_UTILS_IMPORT_PATTERNS = (
    "from odoo.addons.os_payment.payment_apps.odoo_bambora_checkout.models.utils import (",
    "from odoo.addons.os_payment.payment_apps.odoo_bambora_checkout.models.table_models.utils import (",
)
COPY_EXCLUDED_TOP_LEVEL_NAMES = {".git", "scripts", "__pycache__"}
PACKAGE_LOADER_DIRECTORY_NAMES = {
    "controllers",
    "exceptions",
    "lib",
    "models",
    "shopify",
    "table_models",
    "utils",
    "wizard",
    "wizards",
}
KEEP_SOURCE_FILENAMES = {"__init__.py", "__manifest__.py"}
LOADER_MARKER = "_VersionedPycFinder"


class SourceBuffer:
    def __init__(self, text: str) -> None:
        self.text = text
        self._line_offsets = []
        offset = 0
        for line in text.splitlines(keepends=True):
            self._line_offsets.append(offset)
            offset += len(line)
        if not self._line_offsets:
            self._line_offsets.append(0)

    def line_start(self, lineno: int) -> int:
        return self._line_offsets[lineno - 1]

    def index(self, lineno: int, col: int) -> int:
        return self._line_offsets[lineno - 1] + col

    def text_for_stmt(self, node: ast.AST) -> str:
        start = self.line_start(node.lineno)
        end = self.index(node.end_lineno, node.end_col_offset)
        return self.text[start:end]

    def indent_for(self, lineno: int) -> str:
        line = self.text[self.line_start(lineno):].splitlines()[0]
        return line[: len(line) - len(line.lstrip(" \t"))]


def main() -> int:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCE
    target = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_TARGET

    if not source.is_dir():
        print(f"Source add-ons root not found: {source}", file=sys.stderr)
        return 1

    if shutil.which("rsync") is None:
        print("Required command not found: rsync", file=sys.stderr)
        return 1

    copy_tree(source, target)

    helper_copies_added = copy_helper_files(target)

    import_rewrites = rewrite_imports(target)
    bambora_import_rewrites = normalize_bambora_utils_imports(target)
    runtime_inherit_fixes = normalize_runtime_inherit(target)
    created_package_inits = ensure_package_init_files(target)
    loader_files = rewrite_package_loaders(target)

    remove_cache_artifacts(target)
    verify_tree(source, target, helper_copies_added, loader_files)

    print("Summary")
    print(f"- Source: {source}")
    print(f"- Target: {target}")
    print(f"- Package loader files updated: {len(loader_files)}")
    print(f"- Package __init__.py files added: {len(created_package_inits)}")
    print(f"- Runtime _inherit fixes: {runtime_inherit_fixes}")
    print(f"- Import rewrites: {import_rewrites + bambora_import_rewrites}")
    print("Helper copies added")
    for rel_path in helper_copies_added:
        print(f"- {rel_path}")
    print("Verification results")
    print("- Source tree left untouched")
    print("- No unrelated addons introduced")
    print("- No .pyc or __pycache__ in target")
    print("- All Python files parse successfully")
    return 0


def copy_tree(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "rsync",
            "-a",
            "--delete",
            "--exclude",
            ".git",
            "--exclude",
            "scripts",
            "--exclude",
            "__pycache__",
            "--exclude",
            "*.pyc",
            f"{source}/",
            f"{target}/",
        ],
        check=True,
    )


def ensure_package_init_files(root: Path) -> list[Path]:
    created = []
    package_dirs = {
        path.parent
        for path in root.rglob("*.py")
        if not should_skip_path(path)
        and path.name not in KEEP_SOURCE_FILENAMES
        and path.parent.name in PACKAGE_LOADER_DIRECTORY_NAMES
    }

    for package_dir in sorted(package_dirs):
        init_path = package_dir / "__init__.py"
        if init_path.exists():
            continue
        if not (package_dir.parent / "__init__.py").exists():
            continue
        init_path.write_text("")
        created.append(init_path)
    return created


def rewrite_package_loaders(root: Path) -> list[Path]:
    loader_files = []
    for init_path in sorted(root.rglob("__init__.py")):
        if should_skip_path(init_path):
            continue
        package_dir = init_path.parent
        if package_dir.name not in PACKAGE_LOADER_DIRECTORY_NAMES:
            continue

        child_modules = direct_child_module_names(package_dir)
        if not child_modules:
            continue

        imported_modules, package_imports = parse_init_imports(init_path.read_text(), package_dir, root)
        module_names = unique(
            [name for name in imported_modules if name in child_modules]
            + [name for name in child_modules if name not in imported_modules]
        )
        init_path.write_text(render_package_loader(module_names, package_imports))
        loader_files.append(init_path)
    return loader_files


def should_skip_path(path: Path) -> bool:
    return any(part in {"static", "scripts", "__pycache__"} for part in path.parts)


def direct_child_module_names(package_dir: Path) -> list[str]:
    return sorted(
        path.stem
        for path in package_dir.glob("*.py")
        if path.name not in KEEP_SOURCE_FILENAMES
    )


def package_name(path: Path, root: Path) -> str:
    return ".".join(path.relative_to(root).parts)


def parse_init_imports(text: str, package_dir: Path, root: Path) -> tuple[list[str], list[str]]:
    current_package = f"odoo.addons.{package_name(package_dir, root)}"
    module_imports = []
    package_imports = []
    tree = ast.parse(text or "\n")
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        is_current_package_import = (
            (node.level == 1 and node.module is None)
            or (node.level == 0 and node.module == current_package)
        )
        if not is_current_package_import:
            continue
        for alias in node.names:
            name = alias.name
            if name == "*":
                continue
            if (package_dir / f"{name}.py").exists():
                module_imports.append(name)
            elif (package_dir / name / "__init__.py").exists():
                package_imports.append(name)
    return unique(module_imports), unique(package_imports)


def render_package_loader(module_names: list[str], package_names: list[str]) -> str:
    pyc_entries = "\n".join(f"    {module!r}," for module in module_names)
    package_entries = "\n".join(f"    {package!r}," for package in package_names)
    pyc_block = f"pyc_files = [\n{pyc_entries}\n]" if pyc_entries else "pyc_files = [\n]"
    package_block = (
        f"package_imports = [\n{package_entries}\n]" if package_entries else "package_imports = [\n]"
    )

    return (
        "import importlib\n"
        "import importlib.abc\n"
        "import importlib.machinery\n"
        "import importlib.util\n"
        "import os\n"
        "import sys\n\n"
        "base_path = os.path.dirname(__file__)\n"
        'py_version = f"{sys.version_info.major}_{sys.version_info.minor}"\n'
        "strip_python = py_version.replace('_', '')\n\n"
        f"{package_block}\n"
        f"{pyc_block}\n\n"
        "class _VersionedPycFinder(importlib.abc.MetaPathFinder):\n"
        "    def __init__(self, package_name, package_path):\n"
        "        self.package_name = package_name\n"
        "        self.package_path = package_path\n\n"
        "    def find_spec(self, fullname, path=None, target=None):\n"
        "        prefix = f\"{self.package_name}.\"\n"
        "        if not fullname.startswith(prefix):\n"
        "            return None\n"
        "        child_name = fullname[len(prefix):]\n"
        "        if \".\" in child_name:\n"
        "            return None\n"
        "        if os.path.isdir(os.path.join(self.package_path, child_name)):\n"
        "            return None\n"
        "        file_path = os.path.join(\n"
        "            self.package_path,\n"
        "            '__pycache__',\n"
        "            f\"{child_name}.cpython-{strip_python}.pyc\",\n"
        "        )\n"
        "        if not os.path.exists(file_path):\n"
        "            return None\n"
        "        loader = importlib.machinery.SourcelessFileLoader(fullname, file_path)\n"
        "        return importlib.util.spec_from_file_location(fullname, file_path, loader=loader)\n\n"
        "def _install_versioned_pyc_finder():\n"
        "    for finder in sys.meta_path:\n"
        "        if (\n"
        "            getattr(finder, 'package_name', None) == __name__\n"
        "            and getattr(finder, 'package_path', None) == base_path\n"
        "        ):\n"
        "            return\n"
        "    sys.meta_path.insert(0, _VersionedPycFinder(__name__, base_path))\n\n"
        "_install_versioned_pyc_finder()\n\n"
        "for package_name in package_imports:\n"
        "    importlib.import_module(f\"{__name__}.{package_name}\")\n\n"
        "for file_name in pyc_files:\n"
        "    importlib.import_module(f\"{__name__}.{file_name}\")\n"
    )


def unique(names: list[str]) -> list[str]:
    seen = set()
    values = []
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        values.append(name)
    return values


def copy_helper_files(root: Path) -> list[str]:
    added = []
    for src_rel, dest_rel in HELPER_COPIES:
        src = root / src_rel
        dest = root / dest_rel
        if not src.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        added.append(dest_rel)
    return added


def rewrite_imports(root: Path) -> int:
    rewrites = 0
    for path in sorted(root.rglob("*.py")):
        if "static" in path.parts:
            continue
        original = path.read_text()
        updated = original
        rel_path = path.relative_to(root)

        if "table_models" in path.parts:
            for old, new in TABLE_IMPORT_REWRITES.items():
                updated = updated.replace(old, new)
            if rel_path in HELPER_COPY_TARGETS:
                updated = deepen_table_model_imports(updated, path, root)
        else:
            for old, new in RUNTIME_IMPORT_REWRITES.items():
                updated = updated.replace(old, new)

        if updated != original:
            path.write_text(updated)
            rewrites += 1
    return rewrites


def normalize_bambora_utils_imports(root: Path) -> int:
    helper_path = root / BAMBORA_UTILS_PATH
    if not helper_path.exists():
        return 0

    helper_public_names = get_helper_public_names(helper_path)
    rewrites = 0
    for path in sorted((root / "os_payment/payment_apps/odoo_bambora_checkout/models").rglob("*.py")):
        if "static" in path.parts:
            continue
        original = path.read_text()
        updated = rewrite_bambora_utils_file(path, original, helper_public_names, root)
        if updated != original:
            path.write_text(updated)
            rewrites += 1
    return rewrites


def get_helper_public_names(helper_path: Path) -> list[str]:
    tree = ast.parse(helper_path.read_text())
    public_names: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not node.name.startswith("_"):
            public_names.append(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    public_names.append(target.id)
    return public_names


def rewrite_bambora_utils_file(
    path: Path,
    source: str,
    helper_public_names: list[str],
    root: Path,
) -> str:
    import_lines = source.splitlines(keepends=True)
    filtered_lines = [
        line
        for line in import_lines
        if not any(pattern in line for pattern in BAMBORA_UTILS_IMPORT_PATTERNS)
    ]
    filtered_source = "".join(filtered_lines)

    if path.name == "utils.py":
        return filtered_source

    if "table_models" in path.parts:
        module_path = f"odoo.addons.{package_name(path.parent, root)}.utils"
        import_stmt = render_import_block(module_path, used_helper_names(filtered_source, helper_public_names))
    else:
        import_stmt = render_import_block(
            "odoo.addons.os_payment.payment_apps.odoo_bambora_checkout.models.table_models.utils",
            used_helper_names(filtered_source, helper_public_names),
        )

    if not import_stmt:
        return filtered_source

    insert_at = find_import_insert_offset(filtered_source)
    return filtered_source[:insert_at] + import_stmt + filtered_source[insert_at:]


def used_helper_names(source: str, helper_public_names: list[str]) -> list[str]:
    tree = ast.parse(source)
    seen = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in helper_public_names
    }
    return [name for name in helper_public_names if name in seen]


def render_import_block(module_path: str, names: list[str]) -> str:
    if not names:
        return ""
    body = "".join(f"    {name},\n" for name in names)
    return f"from {module_path} import (\n{body})\n"


def find_import_insert_offset(source: str) -> int:
    tree = ast.parse(source)
    buffer = SourceBuffer(source)
    last_import_end = 0
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            last_import_end = buffer.index(node.end_lineno, node.end_col_offset)
        else:
            break
    if last_import_end and not source[last_import_end:last_import_end + 1] == "\n":
        return last_import_end
    if last_import_end:
        return last_import_end + 1
    return 0


def deepen_table_model_imports(text: str, path: Path, root: Path) -> str:
    current_package = list(path.parent.relative_to(root).parts)

    def replace(match: re.Match[str]) -> str:
        indent = match.group("indent")
        dots = match.group("dots")
        module = match.group("module") or ""
        rest = match.group("rest")
        depth = len(dots) + 1
        keep_count = len(current_package) - depth + 1
        target_package = current_package[:keep_count]
        if module:
            target_package += module.split(".")
        return f"{indent}from odoo.addons.{'.'.join(target_package)} import {rest}"

    return RELATIVE_IMPORT_RE.sub(replace, text)


def normalize_runtime_inherit(root: Path) -> int:
    fixes = 0
    for path in sorted(root.rglob("*.py")):
        if "static" in path.parts or "table_models" in path.parts:
            continue
        original = path.read_text()
        updated = rewrite_runtime_inherit_file(original)
        if updated != original:
            path.write_text(updated)
            fixes += 1
    return fixes


def rewrite_runtime_inherit_file(source: str) -> str:
    tree = ast.parse(source)
    buffer = SourceBuffer(source)
    replacements: list[tuple[int, int, str]] = []

    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            if assignment_name(stmt) != "_inherit":
                continue
            value = stmt_value(stmt)
            literal = literal_value(value)
            if not (isinstance(literal, (list, tuple)) and all(isinstance(item, str) for item in literal)):
                continue

            non_mixins = [item for item in literal if item not in MIXIN_MODELS]
            if len(non_mixins) != 1 or len(non_mixins) == len(literal):
                continue

            start = buffer.line_start(stmt.lineno)
            end = buffer.index(stmt.end_lineno, stmt.end_col_offset)
            indent = buffer.indent_for(stmt.lineno)
            replacements.append((start, end, f"{indent}_inherit = {non_mixins[0]!r}"))

    if not replacements:
        return source

    parts = []
    cursor = 0
    for start, end, replacement in replacements:
        parts.append(source[cursor:start])
        parts.append(replacement)
        cursor = end
    parts.append(source[cursor:])
    return "".join(parts)


def assignment_name(stmt: ast.stmt) -> str | None:
    if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
        return stmt.targets[0].id
    if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
        return stmt.target.id
    return None


def stmt_value(stmt: ast.stmt) -> ast.expr | None:
    if isinstance(stmt, ast.Assign):
        return stmt.value
    if isinstance(stmt, ast.AnnAssign):
        return stmt.value
    return None


def literal_value(node: ast.expr | None):
    if node is None:
        return None
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


def remove_cache_artifacts(root: Path) -> None:
    for cache_dir in root.rglob("__pycache__"):
        if cache_dir.is_dir():
            shutil.rmtree(cache_dir, ignore_errors=True)
    for pyc in root.rglob("*.pyc"):
        pyc.unlink(missing_ok=True)


def verify_tree(source: Path, target: Path, helper_copies_added: list[str], loader_files: list[Path]) -> None:
    if top_level_entries(source) != top_level_entries(target):
        raise RuntimeError("Top-level addon entries differ between source and target")

    for rel_path in helper_copies_added:
        if not (target / rel_path).exists():
            raise RuntimeError(f"Expected helper copy missing: {rel_path}")

    if list(target.rglob("__pycache__")):
        raise RuntimeError("Target contains __pycache__ directories")
    if list(target.rglob("*.pyc")):
        raise RuntimeError("Target contains .pyc files")

    for init_path in loader_files:
        text = init_path.read_text()
        if LOADER_MARKER not in text:
            raise RuntimeError(f"Loader missing versioned pyc finder: {init_path}")
        if "importlib.import_module(f\"{__name__}.{file_name}\")" not in text:
            raise RuntimeError(f"Loader missing module import pattern: {init_path}")

    assert_absent(
        target,
        [
            "from odoo.addons.os_payment.payment_apps.odoo_bambora_checkout.models.utils import (",
            "from odoo.addons.os_payment.payment_apps.odoo_clover_cloud.models.clover_request import CloverRequest",
            "from odoo.addons.os_delivery.delivery_apps.delivery_canada_post.models.canpost_request import CanadaPostRequest",
        ],
    )

    canpost_runtime_path = target / "os_delivery/delivery_apps/delivery_canada_post/models/delivery_canada_post.py"
    if canpost_runtime_path.exists():
        runtime_canpost = canpost_runtime_path.read_text()
        if (
            "from odoo.addons.os_delivery.delivery_apps.delivery_canada_post.models.table_models.canpost_request "
            "import CanadaPostRequest"
        ) not in runtime_canpost:
            raise RuntimeError("Canada Post runtime import was not rewritten")

    for path in sorted(target.rglob("*.py")):
        ast.parse(path.read_text())

    bad_runtime_inherit = find_bad_runtime_inherit(target)
    if bad_runtime_inherit:
        raise RuntimeError("Runtime _inherit mixin patterns remain:\n" + "\n".join(bad_runtime_inherit))


def top_level_entries(root: Path) -> set[str]:
    return {
        path.name
        for path in root.iterdir()
        if path.name not in COPY_EXCLUDED_TOP_LEVEL_NAMES and not path.name.endswith(".pyc")
    }


def assert_absent(root: Path, patterns: list[str]) -> None:
    for path in sorted(root.rglob("*.py")):
        text = path.read_text()
        for pattern in patterns:
            if pattern in text:
                raise RuntimeError(f"Unexpected pattern in {path}: {pattern}")


def find_bad_runtime_inherit(root: Path) -> list[str]:
    bad = []
    for path in sorted(root.rglob("*.py")):
        if "table_models" in path.parts or "static" in path.parts:
            continue
        tree = ast.parse(path.read_text())
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for stmt in node.body:
                if assignment_name(stmt) != "_inherit":
                    continue
                literal = literal_value(stmt_value(stmt))
                if not (isinstance(literal, (list, tuple)) and all(isinstance(item, str) for item in literal)):
                    continue
                non_mixins = [item for item in literal if item not in MIXIN_MODELS]
                if len(non_mixins) == 1 and len(non_mixins) != len(literal):
                    bad.append(f"{path}:{node.name}")
    return bad


if __name__ == "__main__":
    raise SystemExit(main())
