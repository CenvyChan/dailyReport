"""Install the pinned official dws Linux release in the Docker image."""

import hashlib
import io
import platform
import tarfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

VERSION = "1.0.65"
# https://github.com/DingTalk-Real-AI/dingtalk-workspace-cli/releases/tag/v1.0.65
RELEASES = {
    "x86_64": ("amd64", "e712e01924935070ef0d313ef898bf90e5124c6c4ad9ef197c3647180b4be9cb"),
    "aarch64": ("arm64", "8858dbaaa9552c4028aaa23c621d4ab960e1eda8d5078e238e7ec216ac2a00d7"),
}


def main():
    architecture, expected = RELEASES[platform.machine()]
    url = (
        "https://github.com/DingTalk-Real-AI/dingtalk-workspace-cli/releases/download/"
        f"v{VERSION}/dws-linux-{architecture}.tar.gz"
    )
    cached = Path("/tmp") / f"install_dws-linux-{architecture}.tar.gz"
    if cached.is_file():
        archive_bytes = cached.read_bytes()
    else:
        request = Request(url, headers={"User-Agent": "daily-report-dws-installer"})
        for attempt in range(3):
            try:
                with urlopen(request, timeout=60) as response:
                    archive_bytes = response.read()
                break
            except (URLError, TimeoutError, OSError):
                if attempt == 2:
                    raise
                time.sleep(2)
    if hashlib.sha256(archive_bytes).hexdigest() != expected:
        raise RuntimeError("dws release checksum mismatch")
    # Only copy the expected files; do not extract arbitrary archive paths.
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as archive:
        for name, destination in (
            ("dws", Path("/usr/local/bin/dws")),
            ("LICENSE", Path("/usr/local/share/dws/LICENSE")),
            ("NOTICE", Path("/usr/local/share/dws/NOTICE")),
        ):
            source = archive.extractfile(f"./{name}")
            if source is None:
                raise RuntimeError(f"dws release is missing {name}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read())
    Path("/usr/local/bin/dws").chmod(0o755)
    print(f"Installed dws {VERSION} ({architecture}), SHA-256 verified")


if __name__ == "__main__":
    main()
