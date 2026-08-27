#!/usr/bin/env python3
"""Read-only resource and source preflight for the Path A certificate replay."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys


GIB = 1 << 30
MIN_FREE_DISK_BYTES = 80 * GIB
MIN_RAM_BYTES = 64 * GIB
REQUIRED_UV_VERSION = "uv 0.10.2"
FULL_COMMIT_RE = re.compile(r"[0-9a-fA-F]{40}")


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str


def make_check(name: str, passed: bool, detail: str) -> Check:
    return Check(name=name, status="PASS" if passed else "FAIL", detail=detail)


def capacity_sufficient(actual: int, minimum: int) -> bool:
    return actual >= minimum


def format_gib(value: int) -> str:
    return f"{value / GIB:.2f} GiB"


def uv_version_matches(value: str) -> bool:
    return value.split()[:2] == REQUIRED_UV_VERSION.split()


def normalize_commit(value: str) -> str:
    if FULL_COMMIT_RE.fullmatch(value) is None:
        raise ValueError("expected commit must be a full 40-hex Git object ID")
    return value.lower()


def existing_ancestor(path: Path) -> Path:
    candidate = path
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            raise ValueError(f"no existing ancestor for {path}")
        candidate = parent
    return candidate


def parse_linux_meminfo(text: str) -> int:
    for line in text.splitlines():
        match = re.fullmatch(r"MemTotal:\s+([0-9]+)\s+kB", line)
        if match:
            return int(match.group(1)) * 1024
    raise ValueError("MemTotal is absent from /proc/meminfo")


def total_memory_bytes() -> int:
    if sys.platform == "linux":
        return parse_linux_meminfo(Path("/proc/meminfo").read_text(encoding="utf-8"))
    if sys.platform == "darwin":
        result = subprocess.run(
            ["sysctl", "-n", "hw.memsize"],
            check=True,
            capture_output=True,
            text=True,
        )
        return int(result.stdout.strip())
    if "SC_PHYS_PAGES" in os.sysconf_names and "SC_PAGE_SIZE" in os.sysconf_names:
        return int(os.sysconf("SC_PHYS_PAGES")) * int(os.sysconf("SC_PAGE_SIZE"))
    raise RuntimeError(f"cannot determine total RAM on {sys.platform}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True)


def command_detail(result: subprocess.CompletedProcess[str]) -> str:
    output = (result.stdout + result.stderr).strip()
    return output if output else f"exit {result.returncode}"


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--expected-commit",
        required=True,
        help="full 40-hex release-candidate commit to require at HEAD",
    )
    parser.add_argument(
        "--output-root",
        required=True,
        type=Path,
        help="fresh destination that Path A will create after this preflight",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    repo = Path(__file__).resolve().parent.parent
    output_root = args.output_root.expanduser()
    if not output_root.is_absolute():
        output_root = Path.cwd() / output_root
    output_root = output_root.resolve(strict=False)
    checks: list[Check] = []

    try:
        expected_commit = normalize_commit(args.expected_commit)
        checks.append(make_check("full_expected_commit", True, expected_commit))
    except ValueError as error:
        expected_commit = args.expected_commit.lower()
        checks.append(make_check("full_expected_commit", False, str(error)))

    git_root = run(["git", "rev-parse", "--show-toplevel"], repo)
    discovered_root = Path(git_root.stdout.strip()).resolve() if git_root.returncode == 0 else None
    checks.append(
        make_check(
            "repository_root",
            discovered_root == repo,
            str(discovered_root) if discovered_root is not None else command_detail(git_root),
        )
    )

    head_result = run(["git", "rev-parse", "HEAD"], repo)
    actual_commit = head_result.stdout.strip().lower() if head_result.returncode == 0 else ""
    checks.append(
        make_check(
            "candidate_commit_at_head",
            head_result.returncode == 0 and actual_commit == expected_commit,
            actual_commit if actual_commit else command_detail(head_result),
        )
    )

    initial_status_result = run(
        ["git", "status", "--porcelain", "--untracked-files=all"], repo
    )
    initial_status = initial_status_result.stdout
    checks.append(
        make_check(
            "clean_worktree",
            initial_status_result.returncode == 0 and not initial_status,
            "no tracked or untracked changes"
            if initial_status_result.returncode == 0 and not initial_status
            else command_detail(initial_status_result),
        )
    )

    output_absent = not os.path.lexists(output_root)
    checks.append(
        make_check(
            "clean_output_destination",
            output_absent,
            f"absent: {output_root}" if output_absent else f"already exists: {output_root}",
        )
    )
    try:
        disk_anchor = existing_ancestor(output_root)
        anchor_is_dir = disk_anchor.is_dir()
        checks.append(
            make_check(
                "output_parent_available",
                anchor_is_dir,
                f"existing ancestor: {disk_anchor}",
            )
        )
        free_disk_bytes = shutil.disk_usage(disk_anchor).free if anchor_is_dir else 0
    except (OSError, ValueError) as error:
        disk_anchor = None
        free_disk_bytes = 0
        checks.append(make_check("output_parent_available", False, str(error)))
    checks.append(
        make_check(
            "free_disk",
            capacity_sufficient(free_disk_bytes, MIN_FREE_DISK_BYTES),
            f"{format_gib(free_disk_bytes)} available; {format_gib(MIN_FREE_DISK_BYTES)} required",
        )
    )

    try:
        memory_bytes = total_memory_bytes()
        memory_detail = (
            f"{format_gib(memory_bytes)} installed; {format_gib(MIN_RAM_BYTES)} required"
        )
        memory_ok = capacity_sufficient(memory_bytes, MIN_RAM_BYTES)
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as error:
        memory_bytes = 0
        memory_detail = str(error)
        memory_ok = False
    checks.append(make_check("installed_ram", memory_ok, memory_detail))

    uv_path = shutil.which("uv")
    checks.append(make_check("uv_available", uv_path is not None, uv_path or "uv not found"))
    uv_version = ""
    if uv_path is not None:
        uv_version_result = run([uv_path, "--version"], repo)
        uv_version = uv_version_result.stdout.strip()
        checks.append(
            make_check(
                "uv_version",
                uv_version_result.returncode == 0 and uv_version_matches(uv_version),
                uv_version if uv_version else command_detail(uv_version_result),
            )
        )
        lock_result = run([uv_path, "lock", "--check"], repo)
        checks.append(
            make_check(
                "uv_lock_current",
                lock_result.returncode == 0,
                command_detail(lock_result),
            )
        )
    else:
        checks.append(make_check("uv_version", False, REQUIRED_UV_VERSION + " required"))
        checks.append(make_check("uv_lock_current", False, "not checked because uv is absent"))

    compiler_command = shlex.split(os.environ.get("CC", "cc"))
    compiler_path = shutil.which(compiler_command[0]) if compiler_command else None
    checks.append(
        make_check(
            "c_compiler_available",
            compiler_path is not None,
            compiler_path or f"compiler not found: {compiler_command!r}",
        )
    )
    compiler_version = ""
    if compiler_path is not None:
        compiler_command[0] = compiler_path
        version_result = run([*compiler_command, "--version"], repo)
        compiler_version = command_detail(version_result).splitlines()[0]
        checks.append(
            make_check(
                "c_compiler_identity",
                version_result.returncode == 0,
                compiler_version,
            )
        )
        sources = ["upper_exact.c", "upper_graph_builder.c", "upper_state_builder.c"]
        compile_result = run(
            [
                *compiler_command,
                "-std=c11",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-fsyntax-only",
                *sources,
            ],
            repo,
        )
        checks.append(
            make_check(
                "c11_source_preflight",
                compile_result.returncode == 0,
                "strict syntax check passed for " + ", ".join(sources)
                if compile_result.returncode == 0
                else command_detail(compile_result),
            )
        )
    else:
        checks.append(make_check("c_compiler_identity", False, "compiler unavailable"))
        checks.append(make_check("c11_source_preflight", False, "compiler unavailable"))

    final_status_result = run(
        ["git", "status", "--porcelain", "--untracked-files=all"], repo
    )
    final_status = final_status_result.stdout
    checks.append(
        make_check(
            "preflight_left_worktree_unchanged",
            final_status_result.returncode == 0 and final_status == initial_status,
            "Git worktree status is byte-identical before and after preflight"
            if final_status_result.returncode == 0 and final_status == initial_status
            else command_detail(final_status_result),
        )
    )

    status = "PASS" if all(check.status == "PASS" for check in checks) else "FAIL"
    payload = {
        "status": status,
        "read_only": True,
        "candidate_commit": actual_commit,
        "expected_commit": expected_commit,
        "repository": str(repo),
        "output_root": str(output_root),
        "requirements": {
            "minimum_free_disk_bytes": MIN_FREE_DISK_BYTES,
            "minimum_ram_bytes": MIN_RAM_BYTES,
            "required_uv_version": REQUIRED_UV_VERSION,
        },
        "observed": {
            "free_disk_bytes": free_disk_bytes,
            "ram_bytes": memory_bytes,
            "uv_version": uv_version,
            "compiler": compiler_version,
            "python_running_preflight": sys.version,
            "platform": platform.platform(),
            "uv_lock_sha256": sha256_file(repo / "uv.lock"),
        },
        "checks": [asdict(check) for check in checks],
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
