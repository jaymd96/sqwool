import sqlite3
from pathlib import Path
from unittest import mock

import pytest

from sqwool import ALLOWLIST  # Replace 'sqwool' with the actual module name
from sqwool import (
    Connection,
    ExtensionsManager,
    PlatformInfo,
    SQLiteSystemInfo,
    connect,
)


class TestPlatformInfo:
    @mock.patch("platform.system")
    @mock.patch("platform.machine")
    def test_get_platform_info_macos_arm(self, mock_machine, mock_system):
        mock_system.return_value = "Darwin"
        mock_machine.return_value = "arm64"
        expected = {"system": "macos", "arch": "arm64", "extensions_dir": "macos-arm64"}
        assert PlatformInfo.get_platform_info() == expected

    @mock.patch("platform.system")
    @mock.patch("platform.machine")
    def test_get_platform_info_windows_x64(self, mock_machine, mock_system):
        mock_system.return_value = "Windows"
        mock_machine.return_value = "AMD64"
        expected = {"system": "windows", "arch": "x64", "extensions_dir": "win-x64"}
        assert PlatformInfo.get_platform_info() == expected

    @mock.patch("platform.system")
    @mock.patch("platform.machine")
    def test_get_platform_info_linux_arm64(self, mock_machine, mock_system):
        mock_system.return_value = "Linux"
        mock_machine.return_value = "aarch64"
        expected = {"system": "linux", "arch": "arm64", "extensions_dir": "linux-arm64"}
        assert PlatformInfo.get_platform_info() == expected

    @mock.patch("platform.system")
    @mock.patch("platform.machine")
    def test_get_platform_info_unsupported(self, mock_machine, mock_system):
        mock_system.return_value = "UnknownOS"
        mock_machine.return_value = "unknown"
        with pytest.raises(RuntimeError) as excinfo:
            PlatformInfo.get_platform_info()
        assert "Unsupported platform" in str(excinfo.value)

    @mock.patch.object(PlatformInfo, "get_platform_info")
    def test_is_supported_platform_true(self, mock_get_info):
        mock_get_info.return_value = {
            "system": "linux",
            "arch": "x86",
            "extensions_dir": "linux-x86",
        }
        assert PlatformInfo.is_supported_platform() is True

    @mock.patch.object(
        PlatformInfo, "get_platform_info", side_effect=RuntimeError("Unsupported")
    )
    def test_is_supported_platform_false(self, mock_get_info):
        assert PlatformInfo.is_supported_platform() is False


class TestExtensionsManager:
    @pytest.fixture
    def manager(self):
        with mock.patch("sqwool.PlatformInfo.get_platform_info") as mock_get_info:
            mock_get_info.return_value = {
                "system": "linux",
                "arch": "x86",
                "extensions_dir": "linux-x86",
            }
            return ExtensionsManager(base_dir=Path("/fake/extensions"))

    def test_initialization(self, manager):
        assert manager.platform_info["system"] == "linux"
        assert manager.platform_info["arch"] == "x86"
        assert manager.platform_info["extensions_dir"] == "linux-x86"
        assert manager.base_dir == Path("/fake/extensions")
        assert manager.platform_dir == Path("/fake/extensions/linux-x86")
        assert manager.extension_patterns["linux"] == ".so"

    @mock.patch("os.makedirs")
    def test_setup_directories(self, mock_makedirs, manager):
        manager.setup_directories()
        expected_dirs = [
            Path("/fake/extensions/win-x64"),
            Path("/fake/extensions/linux-x86"),
            Path("/fake/extensions/linux-arm64"),
            Path("/fake/extensions/macos-x86"),
            Path("/fake/extensions/macos-arm64"),
        ]
        calls = [mock.call(dir, exist_ok=True) for dir in expected_dirs]
        mock_makedirs.assert_has_calls(calls, any_order=True)

    def test_should_load_all_allowlist(self, manager):
        global ALLOWLIST
        original_allowlist = ALLOWLIST.copy()
        ALLOWLIST.append("__ALL__")
        ext = Path("uuid.so")
        assert manager._should_load(ext) is True
        ALLOWLIST.remove("__ALL__")
        # Restore original allowlist
        ALLOWLIST[:] = original_allowlist

    def test_should_load_allowed_extension(self, manager):
        ALLOWLIST.append("UUID")
        ext = Path("uuid.so")
        assert manager._should_load(ext) is True
        ALLOWLIST.remove("UUID")

    def test_should_not_load_disallowed_extension(self, manager):
        ext = Path("malicious.so")
        assert manager._should_load(ext) is False

    @mock.patch.object(ExtensionsManager, "_should_load", return_value=True)
    @mock.patch("pathlib.Path.glob")
    @mock.patch("pathlib.Path.exists")
    def test_get_platform_extensions(
        self, mock_exists, mock_glob, mock_should_load, manager
    ):
        mock_glob.return_value = [Path("uuid.so"), Path("test.so")]
        mock_exists.return_value = True
        extensions = manager.get_platform_extensions()
        assert extensions == [Path("uuid.so"), Path("test.so")]
        mock_glob.assert_called_with("*/*.so")

    @mock.patch("pathlib.Path.exists")
    def test_validate_extension_valid(self, mock_exists, manager):
        mock_exists.return_value = True
        ext = Path("uuid.so")
        assert manager.validate_extension(ext) is True

    def test_validate_extension_invalid_suffix(self, manager):
        ext = Path("uuid.dll")
        assert manager.validate_extension(ext) is False

    def test_validate_extension_nonexistent_file(self, manager):
        ext = Path("/nonexistent/uuid.so")
        with mock.patch.object(Path, "exists", return_value=False):
            assert manager.validate_extension(ext) is False


class TestSQLiteSystemInfo:
    @mock.patch("platform.system")
    def test_get_sqlite_info_macos(self, mock_system):
        mock_system.return_value = "Darwin"
        info = SQLiteSystemInfo.get_sqlite_info()
        assert info["system"] == "darwin"
        assert info["can_load_extensions"] is False
        assert info["reason"] == "Default macOS SQLite3 build has extensions disabled"
        assert info["solution"] == "Use homebrew sqlite: brew install sqlite3"

    @mock.patch("platform.system")
    def test_get_sqlite_info_linux(self, mock_system):
        mock_system.return_value = "Linux"
        info = SQLiteSystemInfo.get_sqlite_info()
        assert info["system"] == "linux"
        assert info["can_load_extensions"] is True
        assert info["reason"] == "System SQLite build supports extensions"
        assert info["solution"] is None

    @mock.patch("platform.system")
    @mock.patch("os.path.exists")
    @mock.patch("subprocess.run")
    def test_find_sqlite_binary_homebrew(self, mock_run, mock_exists, mock_system):
        mock_system.return_value = "Darwin"

        # Mock Homebrew paths
        def side_effect(path):
            return path in ["/opt/homebrew/opt/sqlite/bin/sqlite3"]

        mock_exists.side_effect = side_effect
        binary = SQLiteSystemInfo.find_sqlite_binary()
        assert binary == "/opt/homebrew/opt/sqlite/bin/sqlite3"

    @mock.patch("platform.system")
    @mock.patch("os.path.exists", return_value=False)
    @mock.patch("subprocess.run")
    def test_find_sqlite_binary_which(self, mock_run, mock_exists, mock_system):
        mock_system.return_value = "Linux"
        mock_run.return_value = mock.Mock(returncode=0, stdout="/usr/bin/sqlite3\n")
        binary = SQLiteSystemInfo.find_sqlite_binary()
        assert binary == "/usr/bin/sqlite3"

    @mock.patch("platform.system")
    @mock.patch("os.path.exists", return_value=False)
    @mock.patch("subprocess.run", side_effect=Exception("Error"))
    def test_find_sqlite_binary_not_found(self, mock_run, mock_exists, mock_system):
        mock_system.return_value = "Linux"
        binary = SQLiteSystemInfo.find_sqlite_binary()
        assert binary is None


class TestConnection:
    @pytest.fixture
    def connection(self):
        # Create a mock connection object
        with mock.patch("sqwool.connect") as mock_connect:
            mock_conn = mock.Mock(spec=Connection)
            mock_connect.return_value = mock_conn
            conn = Connection(":memory:")
            return conn

    def test_init_extensions_enabled(self, connection):
        with mock.patch.object(connection, "enable_load_extension") as mock_enable:
            with mock.patch.object(
                ExtensionsManager, "get_platform_extensions", return_value=[]
            ):
                with mock.patch.object(
                    ExtensionsManager, "validate_extension", return_value=True
                ):
                    connection.init_extensions(extensions_dir="/fake/extensions")
                    mock_enable.assert_called_with(True)
                    assert connection._extensions_enabled is True

    def test_init_extensions_disabled(self, connection):
        with mock.patch.object(
            connection,
            "enable_load_extension",
            side_effect=sqlite3.OperationalError("Disabled"),
        ):
            with mock.patch(
                "sqwool.PlatformInfo.get_platform_info",
                return_value={
                    "system": "linux",
                    "arch": "x86",
                    "extensions_dir": "linux-x86",
                },
            ):
                with mock.patch("logging.warning") as mock_log:
                    connection.init_extensions(extensions_dir="/fake/extensions")
                    mock_log.assert_called()
                    assert connection._extensions_enabled is False

    def test_load_platform_extensions_success(self, connection):
        with mock.patch.object(connection, "_extensions_enabled", True):
            with mock.patch.object(
                connection, "extensions_manager", create=True
            ) as mock_manager:
                mock_manager.get_platform_extensions.return_value = [Path("uuid.so")]
                mock_manager.validate_extension.return_value = True
                with mock.patch.object(connection, "load_extension") as mock_load_ext:
                    connection._load_platform_extensions()
                    mock_load_ext.assert_called_with("uuid.so")

    def test_load_platform_extensions_invalid_extension(self, connection):
        with mock.patch.object(connection, "_extensions_enabled", True):
            with mock.patch.object(
                connection, "extensions_manager", create=True
            ) as mock_manager:
                mock_manager.get_platform_extensions.return_value = [
                    Path("malicious.dll")
                ]
                mock_manager.validate_extension.return_value = False
                with mock.patch("logging.warning") as mock_log:
                    connection._load_platform_extensions()
                    mock_log.assert_called_with(
                        "Invalid extension for platform: malicious.dll"
                    )

    def test_load_platform_extensions_load_failure(self, connection):
        with mock.patch.object(connection, "_extensions_enabled", True):
            with mock.patch.object(
                connection, "extensions_manager", create=True
            ) as mock_manager:
                mock_manager.get_platform_extensions.return_value = [Path("uuid.so")]
                mock_manager.validate_extension.return_value = True
                with mock.patch.object(
                    connection,
                    "load_extension",
                    side_effect=sqlite3.Error("Load failed"),
                ):
                    with mock.patch("logging.warning") as mock_log:
                        connection._load_platform_extensions()
                        mock_log.assert_called_with(
                            "Failed to load extension uuid.so: Load failed"
                        )

    def test_extensions_supported_true(self, connection):
        connection._extensions_enabled = True
        assert connection.extensions_supported is True

    def test_extensions_supported_false(self, connection):
        connection._extensions_enabled = False
        assert connection.extensions_supported is False


class TestConnectFunction:
    @mock.patch("sqwool.Connection")
    @mock.patch("sqlite3.connect")
    def test_connect_returns_custom_connection(
        self, mock_sqlite_connect, mock_custom_conn
    ):
        mock_sqlite_connect.return_value = mock_custom_conn
        conn = connect("test.db")
        mock_sqlite_connect.assert_called_with(
            database="test.db",
            timeout=5.0,
            detect_types=0,
            isolation_level=None,
            check_same_thread=True,
            factory=Connection,
            cached_statements=128,
            uri=False,
        )
        mock_custom_conn.init_extensions.assert_called_with(extensions_dir=None)
        assert conn == mock_custom_conn

    @mock.patch("sqwool.Connection")
    @mock.patch("sqlite3.connect")
    def test_connect_with_extensions_dir(self, mock_sqlite_connect, mock_custom_conn):
        mock_sqlite_connect.return_value = mock_custom_conn
        conn = connect("test.db", extensions_dir="/fake/extensions")  # noqa: F841
        mock_custom_conn.init_extensions.assert_called_with(
            extensions_dir="/fake/extensions"
        )
