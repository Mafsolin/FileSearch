from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def project_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as stream:
        return tomllib.load(stream)["project"]["version"]


def test_frozen_executable_has_matching_windows_version_metadata():
    version = project_version()
    numeric_version = f"{version}.0"
    resource = (ROOT / "assets/version_info.txt").read_text(encoding="utf-8")
    spec = (ROOT / "FileSearch.spec").read_text(encoding="utf-8")

    assert f"filevers=({numeric_version.replace('.', ', ')})" in resource
    assert f"prodvers=({numeric_version.replace('.', ', ')})" in resource
    assert f"StringStruct('FileVersion', '{numeric_version}')" in resource
    assert f"StringStruct('ProductVersion', '{numeric_version}')" in resource
    assert r"version='assets\\version_info.txt'" in spec


def test_inno_setup_contract_is_a_normal_all_users_installation():
    script = (ROOT / "installer/FileSearch.iss").read_text(encoding="utf-8")

    assert "AppId={{B26AF219-A6F3-4D8F-BB03-447F11098539}" in script
    assert "PrivilegesRequired=admin" in script
    assert "PrivilegesRequiredOverridesAllowed" not in script
    assert "DefaultDirName={autopf}\\FileSearch" in script
    assert "UninstallDisplayIcon={app}\\app\\FileSearch.exe" in script
    assert "CloseApplications=yes" in script
    assert "OutputBaseFilename=FileSearch-Setup-{#AppVersion}" in script
    assert 'Name: "{group}\\FileSearch"' in script
    assert 'Name: "{autodesktop}\\FileSearch"' in script
    assert "postinstall" in script
    assert "%LOCALAPPDATA%" not in script
    assert "[UninstallDelete]" not in script
    assert "[InstallDelete]" in script
    assert 'Name: "{app}\\app\\*"' in script
    assert 'DestDir: "{app}\\app"' in script
    assert '#if Ver < EncodeVer(6, 3, 0)' in script


def test_installer_build_script_builds_pyinstaller_and_inno_setup():
    script = (ROOT / "scripts/build-installer.ps1").read_text(encoding="utf-8")
    wrapper = (ROOT / "scripts/build-installer.cmd").read_text(encoding="utf-8")

    assert "pyproject.toml" in script
    assert "FileSearch.spec" in script
    assert "ISCC.exe" in script
    assert "/DAppVersion=" in script
    assert "dist\\installer" in script
    assert "Stop-Process" in script
    assert "requirements-release.lock" in script
    assert "--require-hashes" in script
    assert "0x8664" in script
    assert "6.7.3" in script
    assert "build-installer.ps1" in wrapper


def test_release_dependencies_are_versioned_and_hash_locked():
    lock = (ROOT / "requirements-release.lock").read_text(encoding="utf-8")
    requirements = [line for line in lock.splitlines() if line and not line.startswith(("#", " ", "--"))]

    assert requirements
    assert all("==" in line for line in requirements)
    assert "--hash=sha256:" in lock


def test_release_uses_patched_image_and_build_dependencies():
    with (ROOT / "pyproject.toml").open("rb") as stream:
        dependencies = tomllib.load(stream)["project"]["dependencies"]
    release_input = (ROOT / "requirements-release.in").read_text(encoding="utf-8").casefold()

    assert "Pillow>=12.3,<13" in dependencies
    assert "pillow==12.3.0" in release_input
    assert "setuptools==83.0.0" in release_input
