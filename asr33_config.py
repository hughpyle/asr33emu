"""ASR-33 Configuration Loader

Handles configuration from YAML files and command-line arguments.
CLI arguments always override config file settings.
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Any

import yaml

# Optional serial port enumeration
try:
    import serial.tools.list_ports
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False


# --- Configuration file locations ---

def _get_platform_config_dir() -> Path:
    """Return the platform-appropriate user config directory."""
    if sys.platform == "win32":
        # Windows: use APPDATA (roaming) or LOCALAPPDATA
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "asr33emu"
        localappdata = os.environ.get("LOCALAPPDATA")
        if localappdata:
            return Path(localappdata) / "asr33emu"
        # Fallback to home directory
        return Path.home() / "asr33emu"
    else:
        # Linux/macOS: use XDG_CONFIG_HOME or ~/.config
        xdg_config = os.environ.get("XDG_CONFIG_HOME")
        if xdg_config:
            return Path(xdg_config) / "asr33emu"
        return Path.home() / ".config" / "asr33emu"


def get_default_config_paths() -> list[Path]:
    """Return list of config file paths to search, in priority order."""
    paths = []

    # 1. Current directory (highest priority)
    paths.append(Path.cwd() / "asr33_config.yaml")

    # 2. Platform-specific user config directory
    paths.append(_get_platform_config_dir() / "config.yaml")

    # 3. Home directory dotfile (works on all platforms)
    paths.append(Path.home() / ".asr33emu.yaml")

    return paths


def get_user_config_path() -> Path:
    """Return the path where user config should be saved."""
    return _get_platform_config_dir() / "config.yaml"


def find_config_file() -> Path | None:
    """Find the first existing config file from default paths."""
    for path in get_default_config_paths():
        if path.exists():
            return path
    return None


# --- Serial port utilities ---

def list_serial_ports() -> list[dict[str, str]]:
    """Return list of available serial ports with descriptions."""
    if not HAS_SERIAL:
        return []

    ports = []
    for port in serial.tools.list_ports.comports():
        ports.append({
            "device": port.device,
            "description": port.description,
            "hwid": port.hwid,
        })
    return ports


def print_available_ports(file=None) -> None:
    """Print available serial ports."""
    if file is None:
        file = sys.stdout
    ports = list_serial_ports()

    if not ports:
        print("No serial ports found.", file=file)
        return

    print("Available serial ports:", file=file)
    for port in ports:
        desc = port["description"]
        if desc and desc != port["device"] and desc != "n/a":
            print(f"  {port['device']:30s} {desc}", file=file)
        else:
            print(f"  {port['device']}", file=file)


def is_valid_port(port: str) -> bool:
    """Check if a port exists in the list of available ports."""
    if not HAS_SERIAL:
        return True  # Can't check, assume valid

    available = [p["device"] for p in list_serial_ports()]
    return port in available


# --- Config node wrapper ---

class ConfigNode:
    """
    Lightweight wrapper that allows attribute-style access to dictionaries.
    Example:
        config.sound.config.lid.upper()
    """
    def __init__(self, data):
        self._data = data

    def __getattr__(self, key: str) -> Any:
        if isinstance(self._data, dict) and key in self._data:
            value = self._data[key]
            # Wrap nested dicts so chaining continues
            return ConfigNode(value) if isinstance(value, dict) else value
        raise AttributeError(f"No such config key: {key}")

    def get(self, *keys, default=None):
        """
        Optional nested getter: config.get("sound", "config", "lid")
        """
        current = self._data
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return default
        return current

    def to_dict(self) -> dict:
        """Return the underlying dictionary."""
        return self._data


# --- Default configuration ---

DEFAULT_CONFIG = {
    "frontend": {
        "type": "tkinter",
    },
    "sound": {
        "config": {
            "lid": "up",
            "mute_state": "unmuted",
        }
    },
    "terminal": {
        "config": {
            "mode": "line",
            "columns": 72,
            "rows": 24,
            "scrollback": 200,
            "autowrap": True,
            "keyboard_uppercase_only": False,
            "keyboard_parity_mode": "space",
            "send_cr_at_startup": False,
            "no_print": False,
            "font_path": None,
            "font_size": 20,
        }
    },
    "backend": {
        "type": "serial",
        "serial_config": {
            "port": None,  # No default - must be configured
            "baudrate": 9600,
            "databits": 8,
            "parity": "N",
            "stopbits": 1,
        },
        "ssh_config": {
            "username": None,
            "host": None,
            "port": 22,
            "key_filename": "~/.ssh/id_ed25519",
            "password": None,
            "use_agent": True,
            "expected_fingerprint": None,
            "host_key_policy": "accept-new",
            "known_hosts_file": "~/.ssh/known_hosts",
            "tofu_prompt": True,
        }
    },
    "data_throttle": {
        "config": {
            "mode": "throttled",
            "send_rate_cps": 10,
            "receive_rate_cps": 10,
        }
    },
    "tape_reader": {
        "config": {
            "max_rows": 200,
            "initial_file_path": ".",
            "skip_leading_nulls": True,
            "auto_stop": True,
            "set_msb": False,
            "ghost_outline": True,
            "bit_label_base": 1,
            "ascii_char_mask_msb": True,
        }
    },
    "tape_punch": {
        "config": {
            "max_rows": 200,
            "initial_file_path": ".",
            "mode": "overwrite",
            "ghost_outline": True,
            "bit_label_base": 1,
            "ascii_char_mask_msb": True,
        }
    },
}


def deep_merge(base: dict, overlay: dict) -> dict:
    """Deep merge overlay into base, returning a new dict."""
    result = base.copy()
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


# --- Main config class ---

class ASR33Config:
    """Class to load and manage ASR-33 configuration."""

    def __init__(self, description: str = "ASR-33 Teletype Emulator"):
        self.args = self._parse_args(description)
        self.config_path = None
        self._raw_config = {}
        self._merged_config = {}

        # Handle --list-ports early exit
        if self.args.list_ports:
            print_available_ports()
            sys.exit(0)

        # Load configuration
        self._load_config()

        # Merge CLI args over config file
        self._merged_config = self._merge_with_args(self._raw_config)

        # Handle --save
        if self.args.save:
            self._save_config()

        # Wrap configs for attribute access
        self.config = ConfigNode(self._raw_config)
        self.merged_config = ConfigNode(self._merged_config)

    def _parse_args(self, description: str) -> argparse.Namespace:
        """Parse command-line arguments."""
        parser = argparse.ArgumentParser(
            description=description,
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  %(prog)s --list-ports
  %(prog)s --port /dev/cu.usbserial-A50285BI
  %(prog)s --port COM3 --baud 110 --save
  %(prog)s --port pty                         # local shell (Unix/macOS)
  %(prog)s --port none                        # local loopback
  %(prog)s --backend ssh --config my_config.yaml
"""
        )

        # Config file
        parser.add_argument(
            "--config", "-c", type=str, metavar="FILE",
            help="Path to YAML config file"
        )
        parser.add_argument(
            "--save", "-s", action="store_true",
            help="Save current settings to user config file"
        )

        # Port management
        parser.add_argument(
            "--list-ports", "-l", action="store_true",
            help="List available serial ports and exit"
        )
        parser.add_argument(
            "--port", "-p", type=str, metavar="DEVICE",
            help="Serial port (e.g., COM3, /dev/ttyUSB0), 'pty' for local shell (Unix/macOS only), or 'none' for loopback"
        )

        # Frontend/backend selection
        parser.add_argument(
            "--frontend", "-f", choices=["pygame", "tkinter"],
            help="Frontend type"
        )
        parser.add_argument(
            "--backend", "-b", choices=["serial", "ssh"],
            help="Backend type"
        )

        # Terminal settings
        parser.add_argument(
            "--term_mode", choices=["line", "local"],
            help="Terminal mode: line or local (loopback)"
        )
        parser.add_argument(
            "--columns", type=int, metavar="N",
            help="Number of terminal columns"
        )
        parser.add_argument(
            "--rows", type=int, metavar="N",
            help="Number of terminal rows"
        )
        parser.add_argument(
            "--scrollback", type=int, metavar="N",
            help="Number of scrollback lines"
        )

        # Serial settings
        parser.add_argument(
            "--baud", "--baudrate", type=int, metavar="RATE",
            help="Serial baud rate (e.g., 110, 9600, 19200)"
        )
        parser.add_argument(
            "--databits", type=int, choices=[5, 6, 7, 8],
            help="Serial data bits"
        )
        parser.add_argument(
            "--parity", choices=["N", "E", "O", "M", "S"],
            help="Serial parity: N=None, E=Even, O=Odd, M=Mark, S=Space"
        )
        parser.add_argument(
            "--stopbits", type=int, choices=[1, 2],
            help="Serial stop bits"
        )

        # Other settings
        parser.add_argument(
            "--throttle_rate", type=int, metavar="CPS",
            help="Data throttle rate in characters per second"
        )
        parser.add_argument(
            "--mute", action="store_true",
            help="Start with sound muted"
        )

        return parser.parse_args()

    def _load_config(self) -> None:
        """Load configuration from file."""
        # Start with defaults
        self._raw_config = deep_merge({}, DEFAULT_CONFIG)

        # Find config file
        if self.args.config:
            # Explicit config file specified
            self.config_path = Path(self.args.config)
            if not self.config_path.exists():
                print(f"Config file not found: {self.config_path}", file=sys.stderr)
                sys.exit(1)
        else:
            # Search default locations
            self.config_path = find_config_file()

        # Load and merge config file if found
        if self.config_path and self.config_path.exists():
            with open(self.config_path, "r", encoding="utf-8") as f:
                file_config = yaml.safe_load(f) or {}
            self._raw_config = deep_merge(self._raw_config, file_config)

    def _merge_with_args(self, config: dict) -> dict:
        """Merge command-line arguments over config file settings."""
        merged = deep_merge({}, config)

        # Handle special --port values
        port_arg = getattr(self.args, "port", None)
        if port_arg and port_arg.lower() == "none":
            # Local loopback mode - no backend needed
            self._set_nested(merged, ["terminal", "config", "mode"], "local")
        elif port_arg and port_arg.lower() in ("pty", "shell"):
            # PTY mode - spawn a shell
            self._set_nested(merged, ["backend", "type"], "pty")
        elif port_arg:
            self._set_nested(merged, ["backend", "serial_config", "port"], port_arg)

        # CLI argument to config path mappings
        cli_mappings = {
            "frontend": ["frontend", "type"],
            "backend": ["backend", "type"],
            "baud": ["backend", "serial_config", "baudrate"],
            "databits": ["backend", "serial_config", "databits"],
            "parity": ["backend", "serial_config", "parity"],
            "stopbits": ["backend", "serial_config", "stopbits"],
            "term_mode": ["terminal", "config", "mode"],
            "columns": ["terminal", "config", "columns"],
            "rows": ["terminal", "config", "rows"],
            "scrollback": ["terminal", "config", "scrollback"],
        }

        # Multi-target mappings (one CLI arg sets multiple config values)
        multi_mappings = {
            "throttle_rate": [
                ["data_throttle", "config", "send_rate_cps"],
                ["data_throttle", "config", "receive_rate_cps"],
            ],
        }

        # Apply single mappings
        for arg_name, path in cli_mappings.items():
            value = getattr(self.args, arg_name, None)
            if value is not None:
                self._set_nested(merged, path, value)

        # Apply multi mappings
        for arg_name, paths in multi_mappings.items():
            value = getattr(self.args, arg_name, None)
            if value is not None:
                for path in paths:
                    self._set_nested(merged, path, value)

        # Boolean flags with fixed values
        if self.args.mute:
            self._set_nested(merged, ["sound", "config", "mute_state"], "muted")

        return merged

    def _set_nested(self, d: dict, path: list[str], value: Any) -> None:
        """Set a nested dictionary value by path."""
        for key in path[:-1]:
            if key not in d:
                d[key] = {}
            d = d[key]
        d[path[-1]] = value

    def _save_config(self) -> None:
        """Save merged configuration to user config file."""
        save_path = get_user_config_path()

        # Create directory if needed
        save_path.parent.mkdir(parents=True, exist_ok=True)

        # Write config
        with open(save_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(self._merged_config, f, default_flow_style=False, sort_keys=False)

        print(f"Configuration saved to: {save_path}")

    def get_merged_config(self) -> ConfigNode:
        """Return merged config as a ConfigNode."""
        return self.merged_config

    def get_yaml_config(self) -> ConfigNode:
        """Return raw YAML config as a ConfigNode."""
        return self.config

    def get_key(self, *keys, default=None, merged: bool = True) -> Any:
        """
        Nested key getter.
        Example:
            self.get_key("sound", "config", "lid", default="up")
        """
        node = self.merged_config if merged else self.config
        return node.get(*keys, default=default)

    def validate_serial_port(self) -> tuple[bool, str | None]:
        """
        Validate the configured serial port.

        Returns:
            (is_valid, error_message)
        """
        # Skip validation for non-serial backends (ssh, pty)
        backend_type = self._merged_config.get("backend", {}).get("type", "serial")
        if backend_type in ("ssh", "pty"):
            return True, None

        # Skip validation for local loopback mode
        term_mode = self._merged_config.get("terminal", {}).get("config", {}).get("mode", "line")
        if term_mode == "local":
            return True, None

        port = self._merged_config.get("backend", {}).get("serial_config", {}).get("port")

        if not port:
            return False, "No serial port configured"

        if not is_valid_port(port):
            return False, f"Serial port not found: {port}"

        return True, None

    def print_port_help(self) -> None:
        """Print helpful message about port configuration."""
        port = self._merged_config.get("backend", {}).get("serial_config", {}).get("port")

        print("=" * 60, file=sys.stderr)
        if port:
            print(f"Serial port not found: {port}", file=sys.stderr)
        else:
            print("No serial port configured.", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        print(file=sys.stderr)

        print_available_ports(file=sys.stderr)

        ports = list_serial_ports()
        print(file=sys.stderr)

        prog = Path(sys.argv[0]).name

        if ports:
            example_port = ports[0]["device"]
            print("To start with a serial port:", file=sys.stderr)
            print(f"  {prog} --port {example_port}", file=sys.stderr)
            print(file=sys.stderr)
            print("To start and save as default:", file=sys.stderr)
            print(f"  {prog} --port {example_port} --save", file=sys.stderr)
        else:
            print("No serial ports found.", file=sys.stderr)

        if sys.platform != "win32":
            print(file=sys.stderr)
            print("To start with a local shell (PTY, Unix/macOS only):", file=sys.stderr)
            print(f"  {prog} --port pty", file=sys.stderr)

        print(file=sys.stderr)
        print("To start in local loopback mode (no connection):", file=sys.stderr)
        print(f"  {prog} --port none", file=sys.stderr)

        print(file=sys.stderr)
        print(f"For more options: {prog} --help", file=sys.stderr)
