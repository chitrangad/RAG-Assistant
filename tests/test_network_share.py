"""Tests for the network share connector — UNC parsing, mode selection, SMB discovery."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.ingestion.network_share import NetworkShareConnector, _parse_unc


# ──────────────────────────────────────────────
# UNC path parsing
# ──────────────────────────────────────────────


class TestParseUnc:
    def test_backslash_unc(self):
        assert _parse_unc(r"\\server\share\folder") == ("server", "share/folder")

    def test_forward_slash_unc(self):
        assert _parse_unc("//server/share/folder") == ("server", "share/folder")

    def test_smb_url(self):
        assert _parse_unc("smb://server/share") == ("server", "share")
        assert _parse_unc("SMB://server/share/folder") == ("server", "share/folder")

    def test_root_share_no_subdir(self):
        assert _parse_unc(r"\\server\share") == ("server", "share")

    def test_trailing_slash(self):
        assert _parse_unc("//server/share/") == ("server", "share")

    def test_local_paths_are_not_unc(self):
        assert _parse_unc("/mnt/docs") is None
        assert _parse_unc("C:\\docs") is None
        assert _parse_unc("relative/path") is None
        assert _parse_unc("") is None


# ──────────────────────────────────────────────
# Auth args
# ──────────────────────────────────────────────


class TestAuthArgs:
    def test_no_credentials_uses_guest_session(self):
        c = NetworkShareConnector("//server/share")
        assert c._smb_auth_args() == ["-N"]

    def test_user_and_password(self):
        c = NetworkShareConnector("//server/share", username="alice", password="pw")
        assert c._smb_auth_args() == ["-U", "alice%pw"]

    def test_domain_prefixed_user(self):
        c = NetworkShareConnector(
            "//server/share", username="alice", password="pw", domain="CORP"
        )
        assert c._smb_auth_args() == ["-U", "CORP\\alice%pw"]


# ──────────────────────────────────────────────
# Mode resolution / validation
# ──────────────────────────────────────────────


class TestValidate:
    async def test_uses_filesystem_when_path_is_mounted(self, tmp_path):
        c = NetworkShareConnector(str(tmp_path))
        assert await c.validate() is True
        assert c.mode == "fs"

    async def test_falls_back_to_smb_for_remote_unc(self, monkeypatch):
        calls = []

        def fake_run(cmd, **_kwargs):
            calls.append(cmd)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr("src.ingestion.network_share.subprocess.run", fake_run)

        c = NetworkShareConnector("//nasrv/docs")
        assert await c.validate() is True
        assert c.mode == "smb"
        assert calls and calls[0][0] == "smbclient"

    async def test_guest_session_used_when_no_credentials(self, monkeypatch):
        calls = []

        def fake_run(cmd, **_kwargs):
            calls.append(cmd)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr("src.ingestion.network_share.subprocess.run", fake_run)

        c = NetworkShareConnector(r"\\nasrv\docs")
        assert await c.validate() is True
        assert "-N" in calls[0]

    async def test_missing_smbclient_has_clear_error(self, monkeypatch):
        def raise_not_found(*_args, **_kwargs):
            raise FileNotFoundError

        monkeypatch.setattr("src.ingestion.network_share.subprocess.run", raise_not_found)

        c = NetworkShareConnector(r"\\nasrv\docs")
        assert await c.validate() is False
        assert c.last_error and "smbclient is not installed" in c.last_error

    async def test_smb_connection_refused_error(self, monkeypatch):
        def refuse(*_args, **_kwargs):
            return SimpleNamespace(
                returncode=1, stdout="", stderr="NT_STATUS_LOGON_FAILURE"
            )

        monkeypatch.setattr("src.ingestion.network_share.subprocess.run", refuse)

        c = NetworkShareConnector(r"\\nasrv\docs", username="u", password="p")
        assert await c.validate() is False
        assert c.last_error and "NT_STATUS_LOGON_FAILURE" in c.last_error

    async def test_missing_local_path_has_clear_error(self):
        c = NetworkShareConnector("/nonexistent/definitely/missing")
        assert await c.validate() is False
        assert c.last_error and "does not exist" in c.last_error


# ──────────────────────────────────────────────
# smbclient ls output parsing
# ──────────────────────────────────────────────


class TestParseSmbLsLine:
    def test_regular_file(self):
        parsed = NetworkShareConnector._parse_smb_ls_line(
            "  spec.pdf                            A     12345  Sun Aug 17 12:00:00 2026"
        )
        assert parsed == ("spec.pdf", False, 12345)

    def test_directory(self):
        parsed = NetworkShareConnector._parse_smb_ls_line(
            "  Reports                             D        0  Sun Aug 17 10:00:00 2026"
        )
        assert parsed == ("Reports", True, 0)

    def test_name_with_spaces(self):
        parsed = NetworkShareConnector._parse_smb_ls_line(
            "  notes with spaces.txt               A       321  Sun Aug 17 12:00:00 2026"
        )
        assert parsed == ("notes with spaces.txt", False, 321)

    def test_header_line_ignored(self):
        assert (
            NetworkShareConnector._parse_smb_ls_line(
                "  Domain=[WORKGROUP] OS=[Unix] Server=[Samba 4.2]"
            )
            is None
        )

    def test_blank_line_ignored(self):
        assert NetworkShareConnector._parse_smb_ls_line("   ") is None


# ──────────────────────────────────────────────
# SMB discovery (recursive listing)
# ──────────────────────────────────────────────

_ROOT_LS = """  Domain=[WORKGROUP] OS=[Unix] Server=[Samba 4.2]

  .                                   D        0  Sun Aug 17 10:00:00 2026
  ..                                  D        0  Sun Aug 17 10:00:00 2026
  Reports                             D        0  Sun Aug 17 10:00:00 2026
  spec.pdf                            A     12345  Sun Aug 17 12:00:00 2026
  notes with spaces.txt               A       321  Sun Aug 17 12:00:00 2026
  readme.md                           A      2048  Sun Aug 17 12:00:00 2026
  image.png                           A        99  Sun Aug 17 12:00:00 2026
"""

_SUBDIR_LS = """  .                                   D        0  Sun Aug 17 10:00:00 2026
  ..                                  D        0  Sun Aug 17 10:00:00 2026
  deep-document.pdf                    A     54321  Sun Aug 17 12:00:00 2026
"""


class TestSmbDiscovery:
    @staticmethod
    def _make_fake_run(root_ls=_ROOT_LS, subdir_ls=_SUBDIR_LS):
        """Return a fake subprocess.run that switches on the cd command."""

        def fake_run(cmd, **_kwargs):
            dash_c = cmd.index("-c")
            payload = cmd[dash_c + 1]
            if 'cd "' in payload:
                return SimpleNamespace(returncode=0, stdout=subdir_ls, stderr="")
            return SimpleNamespace(returncode=0, stdout=root_ls, stderr="")

        return fake_run

    async def test_depth_limit_stops_pathological_nesting(self, monkeypatch):
        """A deeply nested tree (e.g. hundreds of nested folders) is bounded."""
        nest_ls = (
            "  .                                   D        0  Sun Aug 17 10:00:00 2026\n"
            "  ..                                  D        0  Sun Aug 17 10:00:00 2026\n"
            "  x                                   D        0  Sun Aug 17 10:00:00 2026\n"
        )
        calls = []

        def fake_run(cmd, **_kwargs):
            calls.append(cmd)
            return SimpleNamespace(returncode=0, stdout=nest_ls, stderr="")

        monkeypatch.setattr("src.ingestion.network_share.subprocess.run", fake_run)

        c = NetworkShareConnector("//nasrv/docs", max_depth=3)
        c.mode = "smb"
        docs = await c.discover_documents()

        assert docs == []
        # Root + one visit per depth level — never falls into an unbounded loop.
        assert len(calls) == 4

    async def test_max_dirs_stops_wide_trees(self, monkeypatch):
        nest_ls = (
            "      .                                   D        0  Sun Aug 17 10:00:00 2026\n"
            "      ..                                  D        0  Sun Aug 17 10:00:00 2026\n"
            "      x                                   D        0  Sun Aug 17 10:00:00 2026\n"
        )
        calls = []

        def fake_run(cmd, **_kwargs):
            calls.append(cmd)
            return SimpleNamespace(returncode=0, stdout=nest_ls, stderr="")

        monkeypatch.setattr("src.ingestion.network_share.subprocess.run", fake_run)

        c = NetworkShareConnector("//nasrv/docs", max_dirs=3)
        c.mode = "smb"
        await c.discover_documents()
        assert len(calls) == 3

    async def test_traversal_uses_single_c_command(self, monkeypatch):
        """cd and ls must share one -c string, or smbclient ignores the cd.

        regression guard: separate -c args silently leave the session at the
        share root, so every "level" re-lists the same root and scans find
        nothing (or loop forever into a recursion cap).
        """

        root_ls = (
            "      .                                   D        0  Sun Aug 17 10:00:00 2026\n"
            "      ..                                  D        0  Sun Aug 17 10:00:00 2026\n"
            "      Reports                             D        0  Sun Aug 17 10:00:00 2026\n"
            "      spec.pdf         A     1234  Sun Aug 17 12:00:00 2026\n"
        )
        sub_ls = (
            "      .                                   D        0  Sun Aug 17 10:00:00 2026\n"
            "      ..                                  D        0  Sun Aug 17 10:00:00 2026\n"
            "      deep.pdf          A     9999  Sun Aug 17 12:00:00 2026\n"
        )

        def fake_run(cmd, **_kwargs):
            dash_c = cmd.index("-c")
            payload = cmd[dash_c + 1]
            if 'cd "' in payload:
                # cd must be in the SAME -c string as ls (separated by ";").
                assert payload == 'cd "Reports"; ls'
                assert cmd.count("-c") == 1
                return SimpleNamespace(returncode=0, stdout=sub_ls, stderr="")
            assert payload == "ls"
            assert cmd.count("-c") == 1
            return SimpleNamespace(returncode=0, stdout=root_ls, stderr="")

        monkeypatch.setattr("src.ingestion.network_share.subprocess.run", fake_run)

        c = NetworkShareConnector("//nasrv/docs")
        c.mode = "smb"
        docs = await c.discover_documents()
        assert {d.file_name for d in docs} == {"spec.pdf", "deep.pdf"}
        deep = next(d for d in docs if d.file_name == "deep.pdf")
        assert deep.file_path == "smb://nasrv/docs/Reports/deep.pdf"

    async def test_recursive_discovery_lists_files_and_filters_extensions(self, monkeypatch):
        monkeypatch.setattr(
            "src.ingestion.network_share.subprocess.run", self._make_fake_run()
        )
        c = NetworkShareConnector("//nasrv/docs")
        c.mode = "smb"  # resolved by validate() in real flows
        docs = await c.discover_documents()

        # Only supported extensions, recursively, in both root and subdir.
        assert {d.file_name for d in docs} == {
            "spec.pdf",
            "notes with spaces.txt",
            "readme.md",
            "deep-document.pdf",
        }
        assert {d.file_type for d in docs} == {"pdf", "txt", "md"}

    async def test_smb_candidates_use_smb_urls(self, monkeypatch):
        monkeypatch.setattr(
            "src.ingestion.network_share.subprocess.run", self._make_fake_run()
        )
        c = NetworkShareConnector("smb://nasrv/docs")
        c.mode = "smb"
        docs = await c.discover_documents()
        spec = next(d for d in docs if d.file_name == "spec.pdf")
        assert spec.file_path == "smb://nasrv/docs/spec.pdf"
        deep = next(d for d in docs if d.file_name == "deep-document.pdf")
        assert deep.file_path == "smb://nasrv/docs/Reports/deep-document.pdf"


# ──────────────────────────────────────────────
# Filesystem discovery
# ──────────────────────────────────────────────


class TestFilesystemDiscovery:
    async def test_discovers_supported_files_recursively(self, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4")
        (tmp_path / "b.txt").write_text("hello")
        (tmp_path / "book.epub").write_bytes(b"PK\x03\x04")
        (tmp_path / "sub" / "c.md").write_text("# doc")
        (tmp_path / "skip.png").write_bytes(b"\x89PNG")

        c = NetworkShareConnector(str(tmp_path))
        c.mode = "fs"
        docs = await c.discover_documents()

        assert {d.file_name for d in docs} == {"a.pdf", "b.txt", "book.epub", "c.md"}
        assert all(not d.file_name.endswith(".png") for d in docs)

    async def test_reads_content_from_disk(self, tmp_path):
        (tmp_path / "hello.txt").write_text("hello world")
        c = NetworkShareConnector(str(tmp_path))
        c.mode = "fs"
        content = await c.read_content(str(tmp_path / "hello.txt"))
        assert content == b"hello world"


# ──────────────────────────────────────────────
# Filesystem timeouts (hung mounts fail instead of hanging)
# ──────────────────────────────────────────────


class TestFilesystemTimeout:
    async def test_validate_times_out_and_returns_false(self, monkeypatch):
        """A hung mount during validation returns False instead of hanging."""
        import time

        def slow():
            time.sleep(1.0)
            return True

        c = NetworkShareConnector("/mnt/hung", fs_timeout=0.1)
        monkeypatch.setattr(c, "_validate_fs_sync", slow)

        assert await c.validate() is False
        assert c.last_error and "Timed out" in c.last_error

    async def test_discovery_times_out_and_raises(self, monkeypatch):
        """A hung mount during discovery raises so the run can be marked failed."""
        import time

        def slow():
            time.sleep(1.0)
            return []

        c = NetworkShareConnector("/mnt/hung", fs_timeout=0.1)
        monkeypatch.setattr(c, "_discover_fs_sync", slow)

        with pytest.raises(TimeoutError):
            await c.discover_documents()

    async def test_read_times_out_and_raises(self, monkeypatch):
        """A hung mount during a per-file read raises TimeoutError."""
        import time

        def slow_read(self):
            time.sleep(1.0)
            return b""

        monkeypatch.setattr(Path, "read_bytes", slow_read)

        c = NetworkShareConnector("/mnt/hung", fs_read_timeout=0.1)
        with pytest.raises(TimeoutError):
            await c.read_content("/mnt/hung/file.txt")


# ──────────────────────────────────────────────
# File-type exclusion
# ──────────────────────────────────────────────


class TestExcludeExtensions:
    async def test_filesystem_excludes_extensions(self, tmp_path):
        (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4")
        (tmp_path / "b.txt").write_text("hello")
        (tmp_path / "book.epub").write_bytes(b"PK\x03\x04")

        c = NetworkShareConnector(
            str(tmp_path), exclude_extensions=["epub", ".TXT", "  md "]
        )
        c.mode = "fs"
        docs = await c.discover_documents()

        assert {d.file_name for d in docs} == {"a.pdf"}

    async def test_smb_excludes_extensions(self, monkeypatch):
        monkeypatch.setattr(
            "src.ingestion.network_share.subprocess.run",
            TestSmbDiscovery._make_fake_run(),
        )
        c = NetworkShareConnector("//nasrv/docs", exclude_extensions=["pdf"])
        c.mode = "smb"
        docs = await c.discover_documents()

        # spec.pdf + deep-document.pdf excluded; txt + md remain.
        assert {d.file_name for d in docs} == {"notes with spaces.txt", "readme.md"}

    async def test_local_folder_excludes_extensions(self, tmp_path):
        from src.ingestion.local_folder import LocalFolderConnector

        (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4")
        (tmp_path / "b.txt").write_text("hello")
        (tmp_path / "book.epub").write_bytes(b"PK\x03\x04")

        c = LocalFolderConnector(str(tmp_path), exclude_extensions=["EPUB"])
        docs = await c.discover_documents()

        assert {d.file_name for d in docs} == {"a.pdf", "b.txt"}
