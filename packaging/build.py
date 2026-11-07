"""Build and check the Windows x64 installer from a clean staging directory."""

import argparse
import hashlib
import json
import os
import platform
import re
import runpy
import shutil
import struct
import subprocess
import sys
from importlib.metadata import distribution
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage


ROOT = Path(__file__).resolve().parents[1]
AVATAR = "assets/branding/poppy-avatar.png"
RESOURCES = ("config.json", AVATAR, "assets/sounds/chime.wav")
RUNTIME_PACKAGES = (
    "PySide6-Essentials", "PySide6-Pdf", "shiboken6", "winsdk",
    "pypresence", "psutil", "pywin32", "nvidia-ml-py", "PyInstaller",
)


def make_icon(path):
    avatar = QImage(str(ROOT / AVATAR))
    if avatar.isNull():
        raise ValueError("Poppy's avatar could not be decoded.")
    sizes = (16, 32, 48, 256)
    directory = bytearray(struct.pack("<HHH", 0, 1, len(sizes)))
    images = bytearray()
    for size in sizes:
        png = QBuffer()
        png.open(QIODevice.OpenModeFlag.WriteOnly)
        image = avatar.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        if not image.save(png, "PNG"):
            raise OSError("Poppy's icon could not be encoded.")
        data = bytes(png.data())
        offset = 6 + 16 * len(sizes) + len(images)
        directory.extend(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset))
        images.extend(data)
    path.write_bytes(directory + images)


def write_notices(folder):
    folder.mkdir()
    versions = [f"Python {platform.python_version()}"]
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.is_file():
        shutil.copyfile(python_license, folder / "Python-LICENSE.txt")
    for name in RUNTIME_PACKAGES:
        package = distribution(name)
        versions.append(f"{name} {package.version}")
        for file in package.files or ():
            if "licenses" not in file.parts and not file.name.lower().startswith(("license", "copying", "notice")):
                continue
            if not file.parts[0].endswith(".dist-info"):
                continue
            target = folder / name / Path(*file.parts[1:])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file.locate(), target)
    (folder / "versions.txt").write_text("\n".join(versions) + "\n", encoding="utf-8")


def sign_file(path, args):
    if args.signtool is None:
        return
    tool = str(args.signtool.resolve(strict=True))
    subprocess.run([
        tool, "sign", "/sha1", args.signer_thumbprint, "/fd", "SHA256",
        "/tr", args.timestamp_url, "/td", "SHA256", str(path),
    ], check=True)
    subprocess.run([tool, "verify", "/pa", "/all", str(path)], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iscc", type=Path, required=True, help="Path to the Inno Setup compiler")
    parser.add_argument("--signtool", type=Path, help="Path to the Windows SDK signing tool")
    parser.add_argument("--signer-thumbprint", help="Thumbprint of a code-signing certificate in your certificate store")
    parser.add_argument("--timestamp-url", help="HTTPS RFC 3161 timestamp service")
    args = parser.parse_args()
    signing = (args.signtool, args.signer_thumbprint, args.timestamp_url)
    if any(signing):
        if not all(signing):
            parser.error("Signing requires --signtool, --signer-thumbprint and --timestamp-url.")
        timestamp = urlsplit(args.timestamp_url)
        if not re.fullmatch(r"[A-Fa-f0-9]{40}", args.signer_thumbprint) or timestamp.scheme != "https" or not timestamp.hostname:
            parser.error("Use a 40-digit hexadecimal thumbprint and an HTTPS timestamp URL.")
    if sys.platform != "win32" or sys.version_info[:2] != (3, 11) or platform.machine() != "AMD64" or sys.maxsize <= 2**32:
        parser.error("Build with 64-bit Python 3.11 on Windows x64.")
    compiler = args.iscc.resolve(strict=True)
    version = runpy.run_path(str(ROOT / "core" / "__init__.py"))["APP_VERSION"]
    media = json.loads((ROOT / "config.json").read_text(encoding="utf-8")).get("media", {})
    if media.get("spotify_sp_dc") or media.get("spotify_sp_dc_protected"):
        raise ValueError("The bundled defaults contain a Spotify credential.")

    build_dir = ROOT / "build"
    dist = ROOT / "dist"
    for directory in (build_dir, dist):
        if directory.resolve().parent != ROOT:
            raise ValueError(f"Build path is outside the checkout: {directory}")
        directory.mkdir(exist_ok=True)

    with TemporaryDirectory(prefix="release-", dir=build_dir) as temporary:
        work = Path(temporary)
        package = work / "source" / "poppy"
        package.mkdir(parents=True)
        (package / "__init__.py").touch()
        shutil.copyfile(ROOT / "main.py", package / "main.py")
        for name in ("core", "ui"):
            shutil.copytree(ROOT / name, package / name, ignore=shutil.ignore_patterns("__pycache__"))

        icon = work / "poppy.ico"
        make_icon(icon)
        command = [
            sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", "--noupx",
            "--onedir", "--windowed", "--name", "Poppy", "--log-level", "WARN",
            "--icon", str(icon), "--paths", str(package.parent),
            "--distpath", str(work / "bundle"), "--workpath", str(work / "freeze"),
            "--specpath", str(work),
        ]
        for name in RESOURCES:
            target = (Path("poppy") / name).parent.as_posix()
            command.extend(("--add-data", f"{ROOT / name}:{target}"))
        # Dependency discovery must not pick up DLLs from developer tools on PATH.
        windows = Path(os.environ["SystemRoot"])
        build_env = dict(os.environ, PATH=os.pathsep.join(map(str, (Path(sys.executable).parent, windows / "System32", windows))))
        subprocess.run([*command, str(package / "main.py")], check=True, cwd=work, env=build_env)

        bundle = work / "bundle" / "Poppy"
        write_notices(bundle / "Third-party")
        shutil.copyfile(ROOT / "LICENSE", bundle / "LICENSE")
        shutil.copyfile(ROOT / "README.md", bundle / "README.md")
        sign_file(bundle / "Poppy.exe", args)
        subprocess.run([str(bundle / "Poppy.exe"), "--check-install"], check=True, timeout=30, cwd=work)
        subprocess.run([
            str(compiler), "/Q", f"/DVersion={version}", f"/DIconPath={icon}",
            f"/DPayloadPath={bundle}", f"/DOutputPath={work}", str(ROOT / "packaging" / "poppy.iss"),
        ], check=True, cwd=work)

        installer = work / f"Poppy-Setup-{version}-x64.exe"
        sign_file(installer, args)
        with installer.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        digest = installer.with_suffix(".exe.sha256")
        digest.write_text(f"{checksum}  {installer.name}\n", encoding="ascii")
        os.replace(installer, dist / installer.name)
        os.replace(digest, dist / digest.name)
    print(dist / installer.name)
    print(f"SHA-256 {checksum}")


if __name__ == "__main__":
    main()
