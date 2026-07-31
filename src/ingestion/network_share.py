"""Network share connector — discovers and reads documents from network drives.

Supports:
- Mounted network paths (Linux /mnt/share, macOS /Volumes/share)
- UNC paths (Windows \\\\server\\share\\folder)
- Authenticated SMB/CIFS shares via smbclient (no mount required)
- Any local or network-mounted directory accessible via the filesystem
"""

import os
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from src.ingestion.connector import SourceConnector, DocumentCandidate
from src.logging_config import get_logger

logger = get_logger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".md", ".txt"}


def _parse_unc(raw: str) -> tuple[str, str]:
    """Parse a UNC path like \\\\server\\share\\folder into (server, share/path).

    Returns (host, share_path) where share_path is everything after the share name.
    Example: \\\\fileserver\\projects\\docs → ('fileserver', 'projects/docs')
    """
    stripped = raw.lstrip("\\")
    parts = stripped.split("\\", 2)
    if len(parts) >= 2:
        host = parts[0]
        share_and_path = "/".join(parts[1:])
        return host, share_and_path
    return stripped, ""


def _normalise_path(raw: str) -> Path:
    """Normalise a path without resolving symlinks (safe for FUSE/GVFS/NFS mounts).

    Uses expanduser() for ~ support and absolute() to make the path absolute
    without attempting symlink resolution which can hang on network filesystems.
    """
    if raw.startswith("\\\\"):
        return Path(raw)
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = p.absolute()
    return p


class NetworkShareConnector(SourceConnector):
    """Discovers documents from a network share.

    Two modes:
    1. **Filesystem mode** (no credentials): The share must already be mounted
       (e.g., Windows UNC, Linux/macOS mount point). Uses pathlib directly.
    2. **SMB client mode** (with credentials): Uses `smbclient` to list and read
       files without requiring a mount. Works on Linux/macOS with smbclient installed.
    """

    def __init__(
        self,
        share_path: str,
        recursive: bool = True,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
        username: str | None = None,
        password: str | None = None,
        domain: str | None = None,
    ):
        self.share_path = _normalise_path(share_path)
        self.share_raw = share_path  # Keep original for smbclient
        self.recursive = recursive
        self.include_patterns = include_patterns
        self.exclude_patterns = exclude_patterns or []
        self.username = username
        self.password = password
        self.domain = domain

    @property
    def has_credentials(self) -> bool:
        """Whether explicit SMB credentials are configured."""
        return bool(self.username and self.password)

    def _smb_auth_flag(self) -> str:
        """Build the -U flag for smbclient."""
        user = self.username or ""
        if self.domain:
            user = f"{self.domain}\\{user}"
        pw = self.password or ""
        return f"{user}%{pw}"

    def _smb_server_share(self) -> tuple[str, str] | None:
        """Parse the UNC path into (server, share_path) for smbclient usage."""
        raw = self.share_raw
        if raw.startswith("\\\\"):
            return _parse_unc(raw)
        # Mounted path — try to guess from the path components
        # /mnt/fileserver/share/folder → server = fileserver? Too fragile.
        # For mounted paths, filesystem mode is better.
        return None

    async def validate(self) -> bool:
        """Check that the path exists and is readable."""
        if self.has_credentials:
            return await self._validate_smb()
        return await self._validate_fs()

    async def _validate_fs(self) -> bool:
        """Filesystem-based validation (for mounted shares)."""
        try:
            if not self.share_path.exists():
                logger.warning("share_path_not_found", path=str(self.share_path))
                return False
            if not self.share_path.is_dir():
                logger.warning("share_path_not_directory", path=str(self.share_path))
                return False
            next(self.share_path.iterdir(), None)
            return True
        except PermissionError:
            logger.warning("share_path_permission_denied", path=str(self.share_path))
            return False
        except OSError as e:
            logger.warning("share_path_os_error", path=str(self.share_path), error=str(e))
            return False

    async def _validate_smb(self) -> bool:
        """SMB-based validation using smbclient."""
        parsed = self._smb_server_share()
        if not parsed:
            logger.warning("smb_cannot_parse_unc", path=self.share_raw)
            return False

        host, share_path = parsed
        share_name = share_path.split("/")[0]
        cmd = [
            "smbclient",
            f"//{host}/{share_name}",
            "-U", self._smb_auth_flag(),
            "-c", "ls",
        ]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                logger.info("smb_validate_success", host=host, share=share_name)
                return True
            logger.warning(
                "smb_validate_failed",
                host=host, share=share_name,
                stderr=result.stderr.strip()[:200],
            )
            return False
        except FileNotFoundError:
            logger.error("smbclient_not_installed")
            return False
        except Exception as e:
            logger.error("smb_validate_error", error=str(e))
            return False

    async def discover_documents(self) -> list[DocumentCandidate]:
        """Scan the network share for supported document types."""
        if self.has_credentials:
            return await self._discover_smb()
        return await self._discover_fs()

    async def _discover_fs(self) -> list[DocumentCandidate]:
        """Filesystem-based discovery (for mounted shares)."""
        candidates: list[DocumentCandidate] = []
        pattern = "**/*" if self.recursive else "*"

        for file_path in self.share_path.glob(pattern):
            if not file_path.is_file():
                continue

            ext = file_path.suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                continue

            rel = str(file_path.relative_to(self.share_path))
            if self._should_skip(rel):
                continue

            try:
                stat = file_path.stat()
            except OSError:
                continue

            candidates.append(
                DocumentCandidate(
                    file_name=file_path.name,
                    file_path=str(file_path),
                    file_type=ext.lstrip("."),
                    file_size_bytes=stat.st_size,
                    last_modified=datetime.fromtimestamp(stat.st_mtime),
                    source_metadata={
                        "source_type": "network_share",
                        "root_path": str(self.share_path),
                        "relative_path": str(file_path.relative_to(self.share_path)),
                    },
                )
            )

        logger.info(
            "network_share_scan_complete",
            share=str(self.share_path),
            file_count=len(candidates),
        )
        return candidates

    async def _discover_smb(self) -> list[DocumentCandidate]:
        """SMB-based discovery using smbclient."""
        parsed = self._smb_server_share()
        if not parsed:
            return []

        host, share_path = parsed
        share_name = share_path.split("/")[0]
        subdir = "/".join(share_path.split("/")[1:]) if "/" in share_path else ""

        candidates: list[DocumentCandidate] = []
        await self._smb_list_recursive(host, share_name, subdir, candidates)
        return candidates

    async def _smb_list_recursive(
        self, host: str, share: str, subdir: str, results: list[DocumentCandidate]
    ) -> None:
        """Recursively list files via smbclient."""
        base_path = f"//{host}/{share}"
        current_dir = f"{subdir}" if subdir else ""

        cmd = [
            "smbclient", base_path,
            "-U", self._smb_auth_flag(),
            "-c", f'cd "{current_dir}"; ls',
        ] if current_dir else [
            "smbclient", base_path,
            "-U", self._smb_auth_flag(),
            "-c", "ls",
        ]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30
            )
            if result.returncode != 0:
                logger.warning("smb_list_failed", path=current_dir, stderr=result.stderr.strip()[:200])
                return

            for line in result.stdout.splitlines():
                line = line.strip()
                if not line or line.startswith("."):
                    continue

                # smbclient "ls" output format: "  block_size   Mon Day  Year|Time  filename"
                # Directories have a 'D' attribute, files don't
                parts = line.rsplit(None, 1)
                if len(parts) < 2:
                    continue
                name = parts[1].strip()

                is_dir = line.strip().startswith("  D")
                if is_dir:
                    if self.recursive:
                        next_dir = f"{current_dir}/{name}" if current_dir else name
                        await self._smb_list_recursive(host, share, next_dir, results)
                    continue

                # Check extension
                ext = os.path.splitext(name)[1].lower()
                if ext not in SUPPORTED_EXTENSIONS:
                    continue

                # Build a virtual file path
                virt_path = f"{current_dir}/{name}" if current_dir else name
                if self._should_skip(virt_path):
                    continue

                try:
                    size_bytes = int(parts[0]) if parts[0].isdigit() else 0
                except ValueError:
                    size_bytes = 0

                results.append(
                    DocumentCandidate(
                        file_name=name,
                        file_path=f"smb://{host}/{share}/{virt_path}",
                        file_type=ext.lstrip("."),
                        file_size_bytes=size_bytes,
                        last_modified=datetime.now(),
                        source_metadata={
                            "source_type": "network_share",
                            "host": host,
                            "share": share,
                            "relative_path": virt_path,
                            "auth": "smbclient",
                        },
                    )
                )

        except subprocess.TimeoutExpired:
            logger.warning("smb_list_timeout", path=current_dir)
        except Exception as e:
            logger.error("smb_list_error", path=current_dir, error=str(e))

    async def read_content(self, file_path: str) -> bytes:
        """Read raw bytes of a file."""
        if self.has_credentials and file_path.startswith("smb://"):
            return await self._read_smb(file_path)

        # Filesystem mode
        fp = Path(file_path)
        if not fp.is_absolute():
            fp = self.share_path / fp
        return fp.read_bytes()

    async def _read_smb(self, smb_url: str) -> bytes:
        """Read a file via smbclient get."""
        # smb://host/share/relative/path
        parts = smb_url.replace("smb://", "").split("/", 2)
        if len(parts) < 3:
            raise ValueError(f"Invalid SMB URL: {smb_url}")

        host, share, rel_path = parts
        base = f"//{host}/{share}"
        parent_dir = "/".join(rel_path.split("/")[:-1])
        fname = rel_path.split("/")[-1]

        with tempfile.NamedTemporaryFile(suffix=f".{fname}", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            cmd_parts = ["smbclient", base, "-U", self._smb_auth_flag()]
            if parent_dir:
                cmd_parts.extend(["-c", f'cd "{parent_dir}"; get "{fname}" "{tmp_path}"'])
            else:
                cmd_parts.extend(["-c", f'get "{fname}" "{tmp_path}"'])

            result = subprocess.run(
                cmd_parts, capture_output=True, text=True, timeout=30
            )
            if result.returncode != 0:
                raise IOError(f"smbclient get failed: {result.stderr.strip()[:200]}")

            with open(tmp_path, "rb") as f:
                return f.read()
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def _should_skip(self, relative_path: str) -> bool:
        """Check exclude patterns against a relative path."""
        for pattern in self.exclude_patterns:
            if re.search(pattern, relative_path):
                return True
        return False
