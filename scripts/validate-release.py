#!/usr/bin/env python3
"""Validate a PermeantOS release candidate or tag artifact set."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tarfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "permeantos-release-validation-v0"
ROOT = Path(__file__).resolve().parents[1]
VERSION_RE = re.compile(r"^v\d+\.\d+\.\d+(?:-[A-Za-z0-9][A-Za-z0-9._-]*)?$")
REQUIRED_ARCHIVE_MEMBERS = {
    "bin/permeant-cli",
    "LICENSE",
    "README.md",
    "INSTALL.md",
}


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str

    def to_json(self) -> dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "detail": self.detail}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_changelog(version: str, *, allow_unreleased: bool) -> Check:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    promoted_heading = re.compile(rf"^## \[{re.escape(version.removeprefix('v'))}\] - \d{{4}}-\d{{2}}-\d{{2}}$", re.MULTILINE)
    literal_heading = re.compile(rf"^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}$", re.MULTILINE)
    if promoted_heading.search(changelog) or literal_heading.search(changelog):
        return Check("changelog-promoted", True, f"CHANGELOG.md contains a dated section for {version}")
    if allow_unreleased and "## [Unreleased]" in changelog:
        return Check(
            "changelog-promoted",
            True,
            f"candidate mode accepted because {version} is not promoted and [Unreleased] exists",
        )
    return Check(
        "changelog-promoted",
        False,
        f"CHANGELOG.md must contain a dated section for {version}, or candidate validation must allow [Unreleased]",
    )


def read_checksums(path: Path) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, filename = line.split(maxsplit=1)
        checksums[filename.strip()] = digest
    return checksums


def validate_archive_members(archive: Path) -> tuple[bool, str]:
    if archive.name.endswith(".tar.gz"):
        with tarfile.open(archive, "r:gz") as tar:
            names = tar.getnames()
    elif archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as zip_file:
            names = zip_file.namelist()
    else:
        return False, f"unsupported archive format for {archive.name}"
    unsafe = [name for name in names if name.startswith("/") or ".." in Path(name).parts]
    if unsafe:
        return False, f"archive contains unsafe member paths: {unsafe}"
    stripped_members = {str(Path(*Path(name).parts[1:])) for name in names if len(Path(name).parts) > 1}
    missing = sorted(REQUIRED_ARCHIVE_MEMBERS - stripped_members)
    if missing:
        return False, f"archive is missing required members: {missing}"
    return True, "archive contains required install members and no unsafe paths"


def validate_artifacts(version: str, artifact_dir: Path) -> list[Check]:
    checks: list[Check] = []
    manifest_path = artifact_dir / "release-manifest.json"
    checksum_path = artifact_dir / "checksums.txt"
    if not manifest_path.is_file():
        return [Check("release-manifest", False, f"missing {manifest_path}")]
    if not checksum_path.is_file():
        return [Check("checksums", False, f"missing {checksum_path}")]

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    checks.append(
        Check(
            "release-manifest-schema",
            manifest.get("schema_version") == "permeantos-release-artifacts-v0",
            f"manifest schema is {manifest.get('schema_version')!r}",
        )
    )
    checks.append(Check("release-manifest-version", manifest.get("version") == version, f"manifest version is {manifest.get('version')!r}"))
    publishing = manifest.get("publishing", {})
    checks.append(
        Check(
            "real-publishing-disabled",
            publishing.get("github_release_created") is False and publishing.get("crates_published") is False,
            "manifest keeps GitHub Release and crate publishing disabled",
        )
    )

    checksums = read_checksums(checksum_path)
    artifacts = manifest.get("artifacts", [])
    checks.append(Check("release-artifact-count", bool(artifacts), f"manifest lists {len(artifacts)} artifact(s)"))
    for artifact in artifacts:
        archive = artifact_dir / artifact["archive"]
        if not archive.is_file():
            checks.append(Check(f"archive-exists:{artifact['archive']}", False, f"missing archive {archive}"))
            continue
        actual_sha = sha256_file(archive)
        expected_sha = artifact.get("archive_sha256")
        checks.append(Check(f"archive-manifest-sha:{archive.name}", actual_sha == expected_sha, f"manifest sha={expected_sha}, actual sha={actual_sha}"))
        checksum_sha = checksums.get(archive.name)
        checks.append(Check(f"archive-checksum-sha:{archive.name}", actual_sha == checksum_sha, f"checksums.txt sha={checksum_sha}, actual sha={actual_sha}"))
        members_ok, members_detail = validate_archive_members(archive)
        checks.append(Check(f"archive-members:{archive.name}", members_ok, members_detail))
    return checks


def validate_package_readiness(package_readiness: Path | None) -> list[Check]:
    if package_readiness is None:
        return []
    if not package_readiness.is_file():
        return [Check("package-readiness-report", False, f"missing {package_readiness}")]
    report = json.loads(package_readiness.read_text(encoding="utf-8"))
    return [
        Check("package-readiness-schema", report.get("schema_version") == "permeantos-package-readiness-v0", f"schema is {report.get('schema_version')!r}"),
        Check("package-readiness-ok", report.get("status") == "ready-gated", f"status is {report.get('status')!r}"),
        Check(
            "package-publishing-disabled",
            report.get("publishing", {}).get("crates_published") is False
            and report.get("publishing", {}).get("python_packages_published") is False,
            "package readiness report keeps registry publication disabled",
        ),
    ]


def validate_crate_packaging(crate_packaging: Path | None) -> list[Check]:
    if crate_packaging is None:
        return []
    if not crate_packaging.is_file():
        return [Check("crate-packaging-report", False, f"missing {crate_packaging}")]
    report = json.loads(crate_packaging.read_text(encoding="utf-8"))
    return [
        Check("crate-packaging-schema", report.get("schema_version") == "permeantos-crate-packaging-v0", f"schema is {report.get('schema_version')!r}"),
        Check("crate-packaging-ok", report.get("ok") is True, f"ok is {report.get('ok')!r}"),
        Check(
            "crate-packaging-publishing-disabled",
            report.get("publishing_enabled") is False,
            f"publishing_enabled is {report.get('publishing_enabled')!r}",
        ),
    ]


def validate_release_version_consistency(release_version_consistency: Path | None) -> list[Check]:
    if release_version_consistency is None:
        return []
    if not release_version_consistency.is_file():
        return [Check("release-version-consistency-report", False, f"missing {release_version_consistency}")]
    report = json.loads(release_version_consistency.read_text(encoding="utf-8"))
    return [
        Check(
            "release-version-consistency-schema",
            report.get("schema_version") == "permeantos-release-version-consistency-v0",
            f"schema is {report.get('schema_version')!r}",
        ),
        Check("release-version-consistency-ok", report.get("ok") is True, f"ok is {report.get('ok')!r}"),
        Check(
            "release-version-publishing-disabled",
            report.get("publishing_enabled") is False,
            f"publishing_enabled is {report.get('publishing_enabled')!r}",
        ),
    ]


def validate(
    version: str,
    artifact_dir: Path,
    *,
    allow_unreleased_changelog: bool,
    package_readiness: Path | None,
    crate_packaging: Path | None,
    release_version_consistency: Path | None,
) -> dict[str, Any]:
    checks = [
        Check("version-format", VERSION_RE.fullmatch(version) is not None, f"version is {version!r}"),
        validate_changelog(version, allow_unreleased=allow_unreleased_changelog),
        *validate_artifacts(version, artifact_dir),
        *validate_package_readiness(package_readiness),
        *validate_crate_packaging(crate_packaging),
        *validate_release_version_consistency(release_version_consistency),
    ]
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "version": version,
        "mode": "candidate" if allow_unreleased_changelog else "tag",
        "artifact_dir": str(artifact_dir),
        "package_readiness": str(package_readiness) if package_readiness else None,
        "crate_packaging": str(crate_packaging) if crate_packaging else None,
        "release_version_consistency": str(release_version_consistency) if release_version_consistency else None,
        "checks": [check.to_json() for check in checks],
    }
    report["ok"] = all(check["ok"] for check in report["checks"])
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--package-readiness", type=Path)
    parser.add_argument("--crate-packaging", type=Path)
    parser.add_argument("--release-version-consistency", type=Path)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument(
        "--allow-unreleased-changelog",
        action="store_true",
        help="Allow candidate validation before CHANGELOG.md is promoted to a dated release section.",
    )
    args = parser.parse_args()

    report = validate(
        args.version,
        args.artifact_dir,
        allow_unreleased_changelog=args.allow_unreleased_changelog,
        package_readiness=args.package_readiness,
        crate_packaging=args.crate_packaging,
        release_version_consistency=args.release_version_consistency,
    )
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
