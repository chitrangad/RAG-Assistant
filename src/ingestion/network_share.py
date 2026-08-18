"""Network share connector — discovers and reads documents from network drives.

Supports:
- Mounted network paths (Linux /mnt/share, macOS /Volumes/share, Windows drive letters)
- UNC paths (Windows \\\\server\\share\\folder, or //server/share/folder, smb://server/share/folder)
- Authenticated SMB/CIFS shares via smbclient (no mount required)
- Anonymous/guest SMB shares via smbclient (no mount, no credentials required)
- Any local or network-mounted directory accessible via the filesystem

Mode selection (resolved in ``validate()``):
1. **Filesystem mode** — used when the path is already accessible on this
   machine (a mounted share or local folder). Fast, no external tools.
2. **SMB mode** — used for UNC-style paths (with credentials, or as a guest)
   via ``smbclient``. Reach any remote share without mounting it. Requires
   ``smbclient`` to be installed on the machine running the app.

All blocking work (filesystem calls, ``smbclient`` subprocesses) runs in a
worker thread via ``asyncio.to_thread`` so a slow or unresponsive share never
blocks the event loop — otherwise one slow scan freezes the whole app.

Filesystem calls are also time-bounded: ``fs_timeout`` bounds discovery/validate
and ``fs_read_timeout`` bounds per-file reads. If a mounted share hangs, the
operation raises so the run is marked failed instead of sitting in ``running``
forever.

SMB traversal is bounded: recursion stops after ``max_depth`` levels or
``max_dirs`` visited directories, so a pathological tree (e.g. hundreds of
nested folders or a link loop) can't hang a scan forever.
"""

import asyncio
import os
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from src.ingestion.connector import SourceConnector, DocumentCandidate
from src.logging_config import get_logger

logger = get_logger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".epub", ".md", ".txt"}


def _parse_unc(raw: str) -> tuple[str, str] | None:
    """Parse a UNC-style path into (server, share_path).

    Accepts:
        \\\\server\\share\\folder     (Windows UNC)
        //server/share/folder      (forward-slash UNC)
        smb://server/share/folder  (explicit SMB URL)

    Returns ``None`` for anything that is not clearly a UNC path (e.g. local
    paths like ``/mnt/docs`` or ``C:\\docs``). ``share_path`` is everything
    after the share name (may be empty).
    """
    s = raw.strip()
    lowered = s.lower()
    if lowered.startswith("smb://"):
        s = s[len("smb://"):]
    elif s.startswith("\\\\"):
        s = s[2:]
    elif s.startswith("//"):
        s = s[2:]
    else:
        return None

    s = s.replace("\\", "/").strip("/")
    parts = [p for p in s.split("/") if p]
    if len(parts) < 2:
        return None
    host = parts[0]
    share_path = "/".join(parts[1:])
    return host, share_path


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
    1. **Filesystem mode** (no credentials, path already mounted): The share
       must be accessible on this machine (e.g., Windows UNC, Linux/macOS
       mount point). Uses pathlib directly.
    2. **SMB client mode** (UNC path, with or without credentials): Uses
       ``smbclient`` to list and read files without requiring a mount. Works
       on Linux/macOS with smbclient installed. Without credentials it
       connects as a guest/anonymous user.
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
        max_depth: int = 20,
        max_dirs: int = 20000,
        fs_timeout: float = 300.0,
        fs_read_timeout: float = 60.0,
    ):
        self.share_path = _normalise_path(share_path)
        self.share_raw = share_path  # Keep original for smbclient
        self.recursive = recursive
        self.include_patterns = include_patterns
        self.exclude_patterns = exclude_patterns or []
        self.username = username
        self.password = password
        self.domain = domain
        self.max_depth = max(max_depth, 1)
        self.max_dirs = max(max_dirs, 1)
        # Bound filesystem work so a hung mount fails the scan rather than
        # hanging the run forever. Discovery/validate walk the whole tree, so
        # they get the longer timeout; per-file reads get the shorter one.
        self.fs_timeout = max(fs_timeout, 1.0)
        self.fs_read_timeout = max(fs_read_timeout, 1.0)

        # (host, share_path) when the path is UNC-style; None otherwise.
        self._unc = _parse_unc(share_path)

        # Resolved access mode after validate(): "fs" or "smb".
        self.mode: str | None = None
        # Human-readable reason when validate() fails (surfaced in the UI).
        self.last_error: str | None = None

    # ── Auth helpers ────────────────────────────────────────────────────

    @property
    def has_credentials(self) -> bool:
        """Whether explicit SMB credentials are configured."""
        return bool(self.username and self.password)

    @property
    def is_unc(self) -> bool:
        """Whether the configured path is a UNC-style network path."""
        return self._unc is not None

    def _smb_auth_args(self) -> list[str]:
        """Build the auth args for smbclient.

        Returns ``["-U", "user%pass"]`` when a username/password is given
        (domain-qualified if requested), otherwise ``["-N"]`` for an
        anonymous/guest session.
        """
        if self.username or self.password:
            user = self.username or ""
            if self.domain and user:
                user = f"{self.domain}\\{user}"
            pw = self.password or ""
            return ["-U", f"{user}%{pw}"]
        return ["-N"]

    def _use_smb(self) -> bool:
        """Whether the connector should use smbclient for discovery/reads."""
        if self.mode is not None:
            return self.mode == "smb"
        # Fall back to SMB for UNC paths even if validate() wasn't called.
        return self._unc is not None

    # ── Blocking helpers (run off the event loop) ───────────────────────

    async def _run_smbclient(
        self, cmd: list[str], timeout: int
    ) -> subprocess.CompletedProcess[str] | None:
        """Run an smbclient command in a worker thread.

        Returns the CompletedProcess on success, or ``None`` after setting
        ``self.last_error`` on failure (missing binary / timeout / error).
        """
        try:
            return await asyncio.to_thread(
                subprocess.run,
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError:
            self.last_error = (
                "smbclient is not installed on this machine. Install it "
                "(e.g. `apt install smbclient`) to connect to remote network "
                "shares without mounting them."
            )
            logger.error("smbclient_not_installed")
            return None
        except subprocess.TimeoutExpired:
            self.last_error = (
                f"Timed out after {timeout}s contacting the SMB share."
            )
            logger.warning("smb_timeout", command=cmd[0:2], timeout=timeout)
            return None
        except Exception as e:  # noqa: BLE001 - surface anything from subprocess
            self.last_error = f"SMB error: {e}"
            logger.error("smb_error", error=str(e))
            return None

    # ── Validation ──────────────────────────────────────────────────────

    async def validate(self) -> bool:
        """Check that the path exists and is readable.

        Resolves the access mode: filesystem first (works for mounted shares
        without smbclient), then SMB for UNC paths (no mount required).
        All work happens in worker threads so validation never blocks the
        event loop.
        """
        self.last_error = None

        # 1. Filesystem mode — covers mounted/local paths, needs no smbclient.
        if await self._validate_fs():
            self.mode = "fs"
            return True

        # 2. SMB mode — reaches remote UNC shares without a mount.
        if self._unc is not None and await self._validate_smb():
            self.mode = "smb"
            return True

        # 3. Diagnostics for the failure.
        if self._unc is None:
            self.last_error = (
                self.last_error
                or f"Path not found or not accessible: {self.share_raw}"
            )
        else:
            self.last_error = (
                self.last_error
                or f"Cannot reach {self.share_raw} over SMB. Check the path and "
                "credentials; smbclient must be installed on this machine."
            )
        return False

    async def _validate_fs(self) -> bool:
        """Filesystem-based validation (for mounted shares), off the loop."""
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._validate_fs_sync), timeout=self.fs_timeout
            )
        except asyncio.TimeoutError:
            self.last_error = (
                f"Timed out after {self.fs_timeout:.0f}s accessing "
                f"{self.share_path}. The share may be hung or unresponsive."
            )
            logger.warning("fs_validate_timeout", path=str(self.share_path))
            return False

    def _validate_fs_sync(self) -> bool:
        """Synchronous filesystem validation (runs in a worker thread)."""
        try:
            if not self.share_path.exists():
                self.last_error = f"Path does not exist: {self.share_path}"
                logger.warning("share_path_not_found", path=str(self.share_path))
                return False
            if not self.share_path.is_dir():
                self.last_error = f"Path is not a directory: {self.share_path}"
                logger.warning("share_path_not_directory", path=str(self.share_path))
                return False
            next(self.share_path.iterdir(), None)
            return True
        except PermissionError:
            self.last_error = f"Permission denied reading: {self.share_path}"
            logger.warning("share_path_permission_denied", path=str(self.share_path))
            return False
        except OSError as e:
            self.last_error = f"Error accessing {self.share_path}: {e}"
            logger.warning("share_path_os_error", path=str(self.share_path), error=str(e))
            return False

    async def _validate_smb(self) -> bool:
        """SMB-based validation using smbclient."""
        if self._unc is None:
            self.last_error = "Not a UNC network path; cannot use SMB."
            return False

        host, share_path = self._unc
        share_name = share_path.split("/")[0]
        cmd = [
            "smbclient",
            f"//{host}/{share_name}",
            *self._smb_auth_args(),
            "-c", "ls",
        ]

        result = await self._run_smbclient(cmd, timeout=15)
        if result is None:
            return False

        if result.returncode == 0:
            logger.info("smb_validate_success", host=host, share=share_name)
            return True

        err = result.stderr.strip()[:300]
        self.last_error = f"SMB connection to {host} failed: {err or 'unknown error'}"
        logger.warning(
            "smb_validate_failed",
            host=host, share=share_name, stderr=err,
        )
        return False

    # ── Discovery ───────────────────────────────────────────────────────

    async def discover_documents(self) -> list[DocumentCandidate]:
        """Scan the network share for supported document types."""
        if self._use_smb():
            return await self._discover_smb()
        return await self._discover_fs()

    async def _discover_fs(self) -> list[DocumentCandidate]:
        """Filesystem-based discovery (for mounted shares), off the loop."""
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._discover_fs_sync), timeout=self.fs_timeout
            )
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"Filesystem scan timed out after {self.fs_timeout:.0f}s on "
                f"{self.share_path}. The share may be hung or unresponsive."
            ) from None

    def _discover_fs_sync(self) -> list[DocumentCandidate]:
        """Synchronous filesystem discovery (runs in a worker thread)."""
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
        """SMB-based discovery using smbclient (bounded traversal)."""
        if self._unc is None:
            return []

        host, share_path = self._unc
        share_name = share_path.split("/")[0]
        subdir = "/".join(share_path.split("/")[1:]) if "/" in share_path else ""

        candidates: list[DocumentCandidate] = []
        stats = {"dirs_visited": 0}
        await self._smb_list_recursive(
            host, share_name, subdir, candidates, depth=0, stats=stats
        )
        return candidates

    async def _smb_list_recursive(
        self,
        host: str,
        share: str,
        subdir: str,
        results: list[DocumentCandidate],
        depth: int = 0,
        stats: dict | None = None,
    ) -> None:
        """Recursively list files via smbclient, bounded by depth and dir count."""
        if stats is None:
            stats = {"dirs_visited": 0}

        if depth > self.max_depth:
            logger.warning(
                "smb_scan_depth_limit", max_depth=self.max_depth, path=subdir
            )
            return
        stats["dirs_visited"] += 1
        if stats["dirs_visited"] > self.max_dirs:
            logger.warning("smb_scan_dir_limit", max_dirs=self.max_dirs)
            return

        # IMPORTANT: `cd` only takes effect when followed by the next command
        # in the SAME smbclient -c string (separated by ";"). Passing them as
        # separate -c args silently ignores the cd and lists the share root.
        # Names containing ";" (rare) can't be traversed by smbclient at all.
        base_path = f"//{host}/{share}"
        if subdir:
            cmd = [
                "smbclient", base_path,
                *self._smb_auth_args(),
                "-c", f'cd "{subdir}"; ls',
            ]
        else:
            cmd = [
                "smbclient", base_path,
                *self._smb_auth_args(),
                "-c", "ls",
            ]

        result = await self._run_smbclient(cmd, timeout=30)
        if result is None or result.returncode != 0:
            if result is not None:
                logger.warning(
                    "smb_list_failed",
                    path=subdir,
                    stderr=result.stderr.strip()[:200],
                )
            return

        for line in result.stdout.splitlines():
            entry = self._parse_smb_ls_line(line)
            if entry is None:
                continue
            name, is_dir, size = entry

            if is_dir:
                if self.recursive and name not in (".", ".."):
                    next_dir = f"{subdir}/{name}" if subdir else name
                    await self._smb_list_recursive(
                        host, share, next_dir, results, depth + 1, stats
                    )
                continue

            # Check extension
            ext = os.path.splitext(name)[1].lower()
            if ext not in SUPPORTED_EXTENSIONS:
                continue

            # Build a virtual file path
            virt_path = f"{subdir}/{name}" if subdir else name
            if self._should_skip(virt_path):
                continue

            results.append(
                DocumentCandidate(
                    file_name=name,
                    file_path=f"smb://{host}/{share}/{virt_path}",
                    file_type=ext.lstrip("."),
                    file_size_bytes=size,
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

    @staticmethod
    def _parse_smb_ls_line(line: str) -> tuple[str, bool, int] | None:
        """Parse one ``smbclient ls`` output line.

        Format:  <name>  <attrs>  <size>  <weekday> <month> <day> <time> <year>
        e.g.     spec.pdf  A     12345  Sun Aug 17 12:00:00 2026

        Names may contain spaces, so parse from the right: the last five
        tokens are the date/time, the token before that is the size column,
        and the token before that is the attribute column. Everything before
        the attribute column is the file name.
        """
        line = line.strip()
        if not line:
            return None
        tokens = line.split()
        # Minimum: name, attr, size, weekday, month, day, time, year (8 tokens).
        if len(tokens) < 8:
            return None
        year = tokens[-1]
        if not (year.isdigit() and len(year) == 4):
            return None
        size_tok = tokens[-6]
        if not size_tok.isdigit():
            return None
        attr = tokens[-7]
        name = " ".join(tokens[:-7])
        if not name:
            return None
        return name, attr.upper().startswith("D"), int(size_tok)

    # ── Reading ─────────────────────────────────────────────────────────

    async def read_content(self, file_path: str) -> bytes:
        """Read raw bytes of a file."""
        if self._use_smb() and file_path.startswith("smb://"):
            return await self._read_smb(file_path)

        # Filesystem mode (off the event loop so a hung mount can't freeze
        # the app; a timeout or OSError surfaces to the orchestrator per
        # document so the run fails instead of hanging).
        fp = Path(file_path)
        if not fp.is_absolute():
            fp = self.share_path / fp
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(fp.read_bytes), timeout=self.fs_read_timeout
            )
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"Timed out after {self.fs_read_timeout:.0f}s reading "
                f"{fp}. The share may be hung or unresponsive."
            ) from None

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
            cmd = ["smbclient", base, *self._smb_auth_args()]
            if parent_dir:
                # Same as listing: cd + get must share one -c string or the
                # cd is silently ignored.
                cmd.extend(["-c", f'cd "{parent_dir}"; get "{fname}" "{tmp_path}"'])
            else:
                cmd.extend(["-c", f'get "{fname}" "{tmp_path}"'])

            result = await self._run_smbclient(cmd, timeout=30)
            if result is None:
                raise IOError(self.last_error or "smbclient failed")

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