# tests/test_sqlwool.py

import sqlite3
from pathlib import Path
from unittest import mock

import pytest

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


@pytest.fixture
def manager():
    with mock.patch("sqwool.PlatformInfo.get_platform_info") as mock_get_info:
        mock_get_info.return_value = {
            "system": "linux",
            "arch": "x86",
            "extensions_dir": "linux-x86",
        }
        return ExtensionsManager(base_dir=Path("/fake/extensions"))


@pytest.fixture
def manager_factory():
    """
    Fixture that returns a factory function to create ExtensionsManager instances
    with a specified allowlist.
    """
    with mock.patch("sqwool.PlatformInfo.get_platform_info") as mock_get_info:
        mock_get_info.return_value = {
            "system": "linux",
            "arch": "x86",
            "extensions_dir": "linux-x86",
        }

        def _create_manager(allowlist=None, base_dir=Path("/fake/extensions")):
            """
            Factory function to create an ExtensionsManager instance.

            Args:
                allowlist (List[str], optional): List of allowed extensions.
                base_dir (Path, optional): Base directory for extensions.

            Returns:
                ExtensionsManager: Configured ExtensionsManager instance.
            """
            return ExtensionsManager(base_dir=base_dir, allowlist=allowlist)

        return _create_manager


class TestExtensionsManager:
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
            Path("/fake/extensions"),
            Path("/fake/extensions/win-x64"),
            Path("/fake/extensions/linux-x86"),
            Path("/fake/extensions/linux-arm64"),
            Path("/fake/extensions/macos-x86"),
            Path("/fake/extensions/macos-arm64"),
        ]
        calls = [mock.call(dir, exist_ok=True) for dir in expected_dirs]
        mock_makedirs.assert_has_calls(calls, any_order=True)
        assert mock_makedirs.call_count == len(expected_dirs)

    def test_should_load_all_allowlist(self, manager_factory):
        # Define the allowlist to load all extensions
        allowlist = ["__ALL__"]

        # Initialize ExtensionsManager with the "__ALL__" allowlist
        manager = manager_factory(allowlist=allowlist)

        # Define a sample extension path
        ext = Path("uuid.so")

        # Assert that the extension should be loaded
        assert manager._should_load(ext) is True

    def test_should_load_allowed_extension(self, manager_factory):
        # Define the allowlist with a specific extension
        allowlist = ["UUID"]

        # Initialize ExtensionsManager with the specific allowlist
        manager = manager_factory(allowlist=allowlist)

        # Define a sample extension path
        ext = Path("uuid.so")

        # Assert that the extension should be loaded
        assert manager._should_load(ext) is True

    def test_should_load_allowed_extension_case_insensitive(self, manager_factory):
        # Define the allowlist with lowercase extension name
        allowlist = ["uuid"]

        # Initialize ExtensionsManager with the specific allowlist
        manager = manager_factory(allowlist=allowlist)

        # Define a sample extension path with uppercase name
        ext = Path("UUID.so")

        # Assert that the extension should be loaded (case-insensitive)
        assert manager._should_load(ext) is True

    def test_should_not_load_disallowed_extension(self, manager_factory):
        # Define an allowlist that does not include "malicious"
        allowlist = ["UUID"]

        # Initialize ExtensionsManager with the specific allowlist
        manager = manager_factory(allowlist=allowlist)

        # Define a sample extension path that is not allowed
        ext = Path("malicious.so")

        # Assert that the extension should NOT be loaded
        assert manager._should_load(ext) is False

    @mock.patch("sqwool.core.Path.exists", return_value=True)
    def test_validate_extension_valid(self, mock_exists, manager):
        ext = Path("uuid.so")
        assert manager.validate_extension(ext) is True

    def test_validate_extension_invalid_suffix(self, manager):
        ext = Path("uuid.dll")
        assert manager.validate_extension(ext) is False

    @mock.patch("sqwool.core.Path.exists", return_value=False)
    def test_validate_extension_nonexistent_file(self, mock_exists, manager):
        ext = Path("/nonexistent/uuid.so")
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
        # Patch sqlite3.connect to return a mock Connection
        with mock.patch("sqlite3.connect") as mock_sqlite_connect:
            mock_conn = mock.Mock(spec=Connection)
            mock_sqlite_connect.return_value = mock_conn
            conn = Connection(":memory:")
            return conn

    def test_init_extensions_enabled(self, connection, manager_factory):
        with mock.patch.object(connection, "enable_load_extension") as mock_enable:
            # Patch ExtensionsManager methods and os.makedirs
            with (
                mock.patch.object(
                    ExtensionsManager, "get_platform_extensions", return_value=[]
                ),
                mock.patch.object(
                    ExtensionsManager, "validate_extension", return_value=True
                ),
                mock.patch("os.makedirs") as mock_makedirs,
            ):
                # Initialize extensions with manager_factory
                manager = manager_factory(allowlist=["__ALL__"])
                connection.extensions_manager = manager
                connection.init_extensions(extensions_dir="/fake/extensions")

                # Assert that 'enable_load_extension' was called correctly
                mock_enable.assert_called_with(True)

                # Assert that extensions were enabled
                assert connection._extensions_enabled is True

                # Define expected calls to 'os.makedirs'
                expected_calls = [
                    mock.call(Path("/fake/extensions"), exist_ok=True),
                    mock.call(Path("/fake/extensions/win-x64"), exist_ok=True),
                    mock.call(Path("/fake/extensions/linux-x86"), exist_ok=True),
                    mock.call(Path("/fake/extensions/linux-arm64"), exist_ok=True),
                    mock.call(Path("/fake/extensions/macos-x86"), exist_ok=True),
                    mock.call(Path("/fake/extensions/macos-arm64"), exist_ok=True),
                ]

                # Assert that 'os.makedirs' was called with all expected directories
                mock_makedirs.assert_has_calls(expected_calls, any_order=True)

                # Optionally, assert that 'os.makedirs' was called the correct number of times
                assert mock_makedirs.call_count == len(expected_calls)

    def test_init_extensions_disabled(self, connection, manager_factory):
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
                with (
                    mock.patch("logging.warning") as mock_log,
                    mock.patch("os.makedirs") as mock_makedirs,
                ):
                    connection.init_extensions(extensions_dir="/fake/extensions")

                    # Assert that a warning was logged
                    mock_log.assert_called()

                    # Assert that extensions were not enabled
                    assert connection._extensions_enabled is False

                    # Define expected calls to 'os.makedirs'
                    expected_calls = [
                        mock.call(Path("/fake/extensions"), exist_ok=True),
                        mock.call(Path("/fake/extensions/win-x64"), exist_ok=True),
                        mock.call(Path("/fake/extensions/linux-x86"), exist_ok=True),
                        mock.call(Path("/fake/extensions/linux-arm64"), exist_ok=True),
                        mock.call(Path("/fake/extensions/macos-x86"), exist_ok=True),
                        mock.call(Path("/fake/extensions/macos-arm64"), exist_ok=True),
                    ]

                    # Assert that 'os.makedirs' was called with all expected directories
                    mock_makedirs.assert_has_calls(expected_calls, any_order=True)

                    # Optionally, assert that 'os.makedirs' was called the correct number of times
                    assert mock_makedirs.call_count == len(expected_calls)

    def test_load_platform_extensions_success(self, connection, manager_factory):
        with mock.patch.object(connection, "_extensions_enabled", True):
            with (
                mock.patch.object(
                    ExtensionsManager,
                    "get_platform_extensions",
                    return_value=[Path("uuid.so")],
                ),
                mock.patch.object(
                    ExtensionsManager, "validate_extension", return_value=True
                ),
                mock.patch.object(connection, "load_extension") as mock_load_ext,
            ):
                connection.extensions_manager = manager_factory(allowlist=["UUID"])
                connection._load_platform_extensions()
                mock_load_ext.assert_called_with("uuid.so")

    def test_load_platform_extensions_invalid_extension(
        self, connection, manager_factory
    ):
        with mock.patch.object(connection, "_extensions_enabled", True):
            with (
                mock.patch.object(
                    ExtensionsManager,
                    "get_platform_extensions",
                    return_value=[Path("malicious.dll")],
                ),
                mock.patch.object(
                    ExtensionsManager, "validate_extension", return_value=False
                ),
            ):
                with mock.patch("logging.warning") as mock_log:
                    connection.extensions_manager = manager_factory(
                        allowlist=["__ALL__"]
                    )
                    connection._load_platform_extensions()
                    mock_log.assert_called_with(
                        "Invalid extension for platform: malicious.dll"
                    )

    def test_load_platform_extensions_load_failure(self, connection, manager_factory):
        with mock.patch.object(connection, "_extensions_enabled", True):
            with (
                mock.patch.object(
                    ExtensionsManager,
                    "get_platform_extensions",
                    return_value=[Path("uuid.so")],
                ),
                mock.patch.object(
                    ExtensionsManager, "validate_extension", return_value=True
                ),
                mock.patch.object(
                    connection,
                    "load_extension",
                    side_effect=sqlite3.Error("Load failed"),
                ),
            ):
                with mock.patch("logging.warning") as mock_log:
                    connection.extensions_manager = manager_factory(allowlist=["UUID"])
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
        mock_custom_conn.init_extensions.assert_called_with(
            extensions_dir=None, allowlist=None
        )
        assert conn == mock_custom_conn

    @mock.patch("sqwool.Connection")
    @mock.patch("sqlite3.connect")
    def test_connect_with_extensions_dir(self, mock_sqlite_connect, mock_custom_conn):
        mock_sqlite_connect.return_value = mock_custom_conn
        conn = connect("test.db", extensions_dir="/fake/extensions")
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
        mock_custom_conn.init_extensions.assert_called_with(
            extensions_dir="/fake/extensions", allowlist=None
        )
        assert conn == mock_custom_conn
