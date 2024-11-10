import logging
import os
import platform
import sqlite3
import subprocess
import sys
from pathlib import Path
from sqlite3 import DatabaseError as DatabaseError
from sqlite3 import DataError as DataError
from sqlite3 import Error as Error
from sqlite3 import IntegrityError as IntegrityError
from sqlite3 import InterfaceError as InterfaceError
from sqlite3 import InternalError as InternalError
from sqlite3 import NotSupportedError as NotSupportedError
from sqlite3 import OperationalError as OperationalError
from sqlite3 import ProgrammingError as ProgrammingError
from sqlite3 import Warning as Warning
from typing import Any, Dict, List, Optional

# Re-export all sqlite3 constants and types
PARSE_DECLTYPES = sqlite3.PARSE_DECLTYPES
PARSE_COLNAMES = sqlite3.PARSE_COLNAMES
SQLITE_OK = sqlite3.SQLITE_OK
SQLITE_DENY = sqlite3.SQLITE_DENY
SQLITE_IGNORE = sqlite3.SQLITE_IGNORE
SQLITE_CREATE_INDEX = sqlite3.SQLITE_CREATE_INDEX
SQLITE_CREATE_TABLE = sqlite3.SQLITE_CREATE_TABLE
SQLITE_CREATE_TEMP_INDEX = sqlite3.SQLITE_CREATE_TEMP_INDEX
SQLITE_CREATE_TEMP_TABLE = sqlite3.SQLITE_CREATE_TEMP_TABLE
SQLITE_CREATE_TEMP_TRIGGER = sqlite3.SQLITE_CREATE_TEMP_TRIGGER
SQLITE_CREATE_TEMP_VIEW = sqlite3.SQLITE_CREATE_TEMP_VIEW
SQLITE_CREATE_TRIGGER = sqlite3.SQLITE_CREATE_TRIGGER
SQLITE_CREATE_VIEW = sqlite3.SQLITE_CREATE_VIEW
SQLITE_DELETE = sqlite3.SQLITE_DELETE
SQLITE_DROP_INDEX = sqlite3.SQLITE_DROP_INDEX
SQLITE_DROP_TABLE = sqlite3.SQLITE_DROP_TABLE
SQLITE_DROP_TEMP_INDEX = sqlite3.SQLITE_DROP_TEMP_INDEX
SQLITE_DROP_TEMP_TABLE = sqlite3.SQLITE_DROP_TEMP_TABLE
SQLITE_DROP_TEMP_TRIGGER = sqlite3.SQLITE_DROP_TEMP_TRIGGER
SQLITE_DROP_TEMP_VIEW = sqlite3.SQLITE_DROP_TEMP_VIEW
SQLITE_DROP_TRIGGER = sqlite3.SQLITE_DROP_TRIGGER
SQLITE_DROP_VIEW = sqlite3.SQLITE_DROP_VIEW
SQLITE_INSERT = sqlite3.SQLITE_INSERT
SQLITE_PRAGMA = sqlite3.SQLITE_PRAGMA
SQLITE_READ = sqlite3.SQLITE_READ
SQLITE_SELECT = sqlite3.SQLITE_SELECT
SQLITE_TRANSACTION = sqlite3.SQLITE_TRANSACTION
SQLITE_UPDATE = sqlite3.SQLITE_UPDATE
SQLITE_ATTACH = sqlite3.SQLITE_ATTACH
SQLITE_DETACH = sqlite3.SQLITE_DETACH
SQLITE_ALTER_TABLE = sqlite3.SQLITE_ALTER_TABLE
SQLITE_REINDEX = sqlite3.SQLITE_REINDEX
SQLITE_ANALYZE = sqlite3.SQLITE_ANALYZE
SQLITE_CREATE_VTABLE = sqlite3.SQLITE_CREATE_VTABLE
SQLITE_DROP_VTABLE = sqlite3.SQLITE_DROP_VTABLE
SQLITE_FUNCTION = sqlite3.SQLITE_FUNCTION
SQLITE_SAVEPOINT = sqlite3.SQLITE_SAVEPOINT
SQLITE_COPY = getattr(sqlite3, "SQLITE_COPY", None)
SQLITE_RECURSIVE = getattr(sqlite3, "SQLITE_RECURSIVE", None)

SEARCH_RECURSIVE = True
ALLOWLIST = ["uuid"]


class Cursor(sqlite3.Cursor):
    """Drop-in replacement for sqlite3.Cursor that maintains identical API"""

    pass


class PlatformInfo:
    """Platform detection and information"""

    @classmethod
    def get_platform_info(cls) -> Dict[str, str]:
        system = platform.system().lower()
        machine = platform.machine().lower()

        if system == "darwin":  # macOS
            is_arm = machine in ("arm64", "aarch64")
            return {
                "system": "macos",
                "arch": "arm64" if is_arm else "x86",
                "extensions_dir": "macos-arm64" if is_arm else "macos-x86",
            }
        elif system == "windows":
            return {
                "system": "windows",
                "arch": "x64" if machine in ("amd64", "x86_64") else machine,
                "extensions_dir": "win-x64",  # Add more Windows architectures if needed
            }
        elif system == "linux":
            is_arm = machine in ("arm64", "aarch64")
            return {
                "system": "linux",
                "arch": "arm64" if is_arm else "x86",
                "extensions_dir": "linux-arm64" if is_arm else "linux-x86",
            }
        else:
            raise RuntimeError(f"Unsupported platform: {system} {machine}")

    @classmethod
    def is_supported_platform(cls) -> bool:
        """Check if current platform is supported"""
        try:
            cls.get_platform_info()
            return True
        except RuntimeError:
            return False


class ExtensionsManager:
    """Manage SQLite extensions for different platforms"""

    def __init__(self, base_dir: Optional[Path] = None):
        self.platform_info = PlatformInfo.get_platform_info()
        self.base_dir = base_dir or Path(
            os.environ.get("SQWOOL_EXTENSIONS_DIR", DEFAULT_EXTENSIONS_DIR)
        )
        self.platform_dir = self.base_dir / self.platform_info["extensions_dir"]

        # Extension patterns by platform
        self.extension_patterns = {"windows": ".dll", "linux": ".so", "macos": ".dylib"}

    def setup_directories(self):
        """Ensure all necessary directories exist"""
        # Create base extensions directory
        os.makedirs(self.base_dir, exist_ok=True)

        # Create platform-specific directories
        for platform_dir in [
            "win-x64",
            "linux-x86",
            "linux-arm64",
            "macos-x86",
            "macos-arm64",
        ]:
            os.makedirs(self.base_dir / platform_dir, exist_ok=True)

    @staticmethod
    def _should_load(ext: str):
        if "__ALL__" in ALLOWLIST:
            return True  # signal to load everything
        return ext.stem.upper() in ",".join(ALLOWLIST).upper()

    def get_platform_extensions(self) -> List[Path]:
        """Get list of extensions for current platform"""
        if not self.platform_dir.exists():
            return []

        pattern = self.extension_patterns.get(self.platform_info["system"], ".so")
        if SEARCH_RECURSIVE:
            pattern = f"/*{pattern}"

        all_ext = list(self.platform_dir.glob(f"*{pattern}"))
        to_load_ext = [ext for ext in all_ext if self._should_load(ext)]
        return to_load_ext

    def validate_extension(self, path: Path) -> bool:
        """Validate that an extension file is appropriate for current platform"""
        if not path.exists():
            return False

        expected_suffix = self.extension_patterns.get(
            self.platform_info["system"], ".so"
        )
        return path.suffix.lower() == expected_suffix

    @property
    def platform_extensions_dir(self) -> Path:
        """Get the platform-specific extensions directory"""
        return self.platform_dir


class SQLiteSystemInfo:
    """Detect and manage system SQLite configuration"""

    @staticmethod
    def get_sqlite_info():
        system = platform.system().lower()
        if system == "darwin":  # macOS
            return {
                "system": "darwin",
                "can_load_extensions": False,
                "reason": "Default macOS SQLite3 build has extensions disabled",
                "solution": "Use homebrew sqlite: brew install sqlite3",
            }
        return {
            "system": system,
            "can_load_extensions": True,
            "reason": "System SQLite build supports extensions",
            "solution": None,
        }

    @staticmethod
    def find_sqlite_binary():
        """Find a SQLite binary that supports extensions"""
        # Check for Homebrew SQLite first on macOS
        if platform.system().lower() == "darwin":
            homebrew_paths = [
                "/opt/homebrew/opt/sqlite/bin/sqlite3",
                "/usr/local/opt/sqlite/bin/sqlite3",
            ]
            for path in homebrew_paths:
                if os.path.exists(path):
                    return path

        # Check PATH for sqlite3
        try:
            result = subprocess.run(
                ["which", "sqlite3"], capture_output=True, text=True
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass

        return None


class Connection(sqlite3.Connection):
    """Enhanced Connection class with platform-specific extension loading"""

    def __init__(self, *args, **kwargs):
        self._extensions_enabled = False
        super().__init__(*args, **kwargs)

    def init_extensions(self, extensions_dir: Optional[str] = None):
        """Initialize extensions after creating the connection."""
        self._extensions_dir = Path(extensions_dir) if extensions_dir else None
        self.extensions_manager = ExtensionsManager(self._extensions_dir)
        self._try_enable_extensions()
        if self._extensions_enabled:
            self._load_platform_extensions()

    def _try_enable_extensions(self):
        """Attempt to enable extension loading"""
        try:
            self.enable_load_extension(True)
            self._extensions_enabled = True
        except (sqlite3.OperationalError, AttributeError) as e:
            platform_info = PlatformInfo.get_platform_info()
            logging.warning(
                f"SQLite extensions not available: {e}\n"
                f"Platform: {platform_info['system']}-{platform_info['arch']}"
            )
            self._extensions_enabled = False

    def _load_platform_extensions(self):
        """Load extensions specific to current platform"""
        if not self._extensions_enabled:
            return

        for ext_path in self.extensions_manager.get_platform_extensions():
            if self.extensions_manager.validate_extension(ext_path):
                try:
                    self.load_extension(str(ext_path))
                    logging.info(f"Loaded extension: {ext_path.name}")
                except sqlite3.Error as e:
                    logging.warning(f"Failed to load extension {ext_path.name}: {e}")
            else:
                logging.warning(f"Invalid extension for platform: {ext_path}")

    @property
    def extensions_supported(self) -> bool:
        """Check if extensions are supported"""
        return self._extensions_enabled

    @property
    def platform_extensions_dir(self) -> Path:
        """Get platform-specific extensions directory"""
        return self.extensions_manager.platform_extensions_dir


def connect(
    database: str,
    timeout: float = 5.0,
    detect_types: int = 0,
    isolation_level: Optional[str] = None,
    check_same_thread: bool = True,
    factory: Optional[Any] = None,
    cached_statements: int = 128,
    uri: bool = False,
    extensions_dir: Optional[str] = None,
    **kwargs,
) -> Connection:
    """Drop-in replacement for sqlite3.connect() that automatically loads extensions"""

    if factory is None:
        factory = Connection

    conn: Connection = sqlite3.connect(
        database=database,
        timeout=timeout,
        detect_types=detect_types,
        isolation_level=isolation_level,
        check_same_thread=check_same_thread,
        factory=factory,
        cached_statements=cached_statements,
        uri=uri,
        **kwargs,
    )
    conn.init_extensions(extensions_dir=extensions_dir)
    return conn


def setup_extension_directories(base_dir: Optional[str] = None):
    """
    Set up all platform-specific extension directories

    Args:
        base_dir: Optional base directory for extensions
    """
    manager = ExtensionsManager(Path(base_dir) if base_dir else None)
    manager.setup_directories()
    return manager.base_dir


def get_platform_info() -> Dict[str, Any]:
    """Get detailed platform information"""
    platform_info = PlatformInfo.get_platform_info()
    manager = ExtensionsManager()

    return {
        **platform_info,
        "extensions_dir": str(manager.platform_extensions_dir),
        "extension_pattern": manager.extension_patterns.get(
            platform_info["system"], ".so"
        ),
        "sqlite_version": sqlite3.sqlite_version,
        "python_version": sys.version,
        "extensions_supported": hasattr(sqlite3.Connection, "enable_load_extension"),
    }


# Re-export all sqlite3 functions
register_adapter = sqlite3.register_adapter
register_converter = sqlite3.register_converter
complete_statement = sqlite3.complete_statement
enable_callback_tracebacks = sqlite3.enable_callback_tracebacks
register_adapter = sqlite3.register_adapter
adapt = sqlite3.adapt

# Version information
version = sqlite3.version
version_info = sqlite3.version_info
sqlite_version = sqlite3.sqlite_version
sqlite_version_info = sqlite3.sqlite_version_info

# Default row factory
Row = sqlite3.Row


def _set_extension_path():
    """Set up the extensions directory if it doesn't exist"""
    default_path = os.path.join(os.path.dirname(__file__), "extensions")
    os.makedirs(default_path, exist_ok=True)
    return default_path


def get_sqlite_build_info() -> Dict[str, Any]:
    """Get information about the SQLite build and extension support"""
    sqlite_info = SQLiteSystemInfo.get_sqlite_info()
    sqlite_binary = SQLiteSystemInfo.find_sqlite_binary()

    return {
        **sqlite_info,
        "binary_path": sqlite_binary,
        "version": sqlite_version,
        "python_version": version,
        "build_date": getattr(sqlite3, "__build_date__", None),
        "has_loadable_extensions": hasattr(sqlite3.Connection, "enable_load_extension"),
    }


# Create extensions directory on import
DEFAULT_EXTENSIONS_DIR = _set_extension_path()
