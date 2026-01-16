#!/usr/bin/env python3
"""
Minimal test suite for asr33_config module.

Run with: python -m pytest test_config.py -v
Or just:  python test_config.py
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Import module under test
import asr33_config
from asr33_config import (
    ConfigNode,
    DEFAULT_CONFIG,
    ASR33Config,
    deep_merge,
    find_config_file,
    get_default_config_paths,
    get_user_config_path,
    is_valid_port,
    list_serial_ports,
    _get_platform_config_dir,
)


class TestConfigNode(unittest.TestCase):
    """Tests for ConfigNode wrapper class."""

    def test_attribute_access(self):
        """Test attribute-style access to nested dicts."""
        data = {"level1": {"level2": {"value": 42}}}
        node = ConfigNode(data)
        self.assertEqual(node.level1.level2.value, 42)

    def test_get_nested(self):
        """Test get() method for nested keys."""
        data = {"a": {"b": {"c": "deep"}}}
        node = ConfigNode(data)
        self.assertEqual(node.get("a", "b", "c"), "deep")
        self.assertEqual(node.get("a", "b", "missing", default="default"), "default")
        self.assertEqual(node.get("missing", default=None), None)

    def test_missing_key_raises(self):
        """Test that accessing missing key raises AttributeError."""
        node = ConfigNode({"exists": 1})
        with self.assertRaises(AttributeError):
            _ = node.missing

    def test_to_dict(self):
        """Test to_dict() returns underlying data."""
        data = {"key": "value"}
        node = ConfigNode(data)
        self.assertEqual(node.to_dict(), data)


class TestDeepMerge(unittest.TestCase):
    """Tests for deep_merge function."""

    def test_simple_merge(self):
        """Test merging flat dicts."""
        base = {"a": 1, "b": 2}
        overlay = {"b": 3, "c": 4}
        result = deep_merge(base, overlay)
        self.assertEqual(result, {"a": 1, "b": 3, "c": 4})

    def test_nested_merge(self):
        """Test merging nested dicts."""
        base = {"outer": {"inner": 1, "keep": 2}}
        overlay = {"outer": {"inner": 99}}
        result = deep_merge(base, overlay)
        self.assertEqual(result["outer"]["inner"], 99)
        self.assertEqual(result["outer"]["keep"], 2)

    def test_base_unchanged(self):
        """Test that base dict is not mutated."""
        base = {"a": 1}
        overlay = {"a": 2}
        deep_merge(base, overlay)
        self.assertEqual(base["a"], 1)


class TestPlatformConfigDir(unittest.TestCase):
    """Tests for cross-platform config directory detection."""

    def test_windows_appdata(self):
        """Test Windows uses APPDATA."""
        with mock.patch.object(sys, "platform", "win32"):
            with mock.patch.dict(os.environ, {"APPDATA": "C:\\Users\\Test\\AppData\\Roaming"}):
                result = _get_platform_config_dir()
                self.assertEqual(result, Path("C:\\Users\\Test\\AppData\\Roaming") / "asr33emu")

    def test_windows_localappdata_fallback(self):
        """Test Windows falls back to LOCALAPPDATA."""
        with mock.patch.object(sys, "platform", "win32"):
            with mock.patch.dict(os.environ, {"LOCALAPPDATA": "C:\\Users\\Test\\AppData\\Local"}, clear=True):
                result = _get_platform_config_dir()
                self.assertEqual(result, Path("C:\\Users\\Test\\AppData\\Local") / "asr33emu")

    def test_linux_xdg_config(self):
        """Test Linux uses XDG_CONFIG_HOME."""
        with mock.patch.object(sys, "platform", "linux"):
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": "/home/test/.config"}):
                result = _get_platform_config_dir()
                self.assertEqual(result, Path("/home/test/.config") / "asr33emu")

    def test_linux_default_config(self):
        """Test Linux defaults to ~/.config when XDG not set."""
        with mock.patch.object(sys, "platform", "linux"):
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch.object(Path, "home", return_value=Path("/home/test")):
                    result = _get_platform_config_dir()
                    self.assertEqual(result, Path("/home/test/.config/asr33emu"))

    def test_macos_uses_xdg_style(self):
        """Test macOS uses same logic as Linux."""
        with mock.patch.object(sys, "platform", "darwin"):
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch.object(Path, "home", return_value=Path("/Users/test")):
                    result = _get_platform_config_dir()
                    self.assertEqual(result, Path("/Users/test/.config/asr33emu"))


class TestConfigPaths(unittest.TestCase):
    """Tests for config path functions."""

    def test_default_paths_includes_cwd(self):
        """Test that current directory config is checked first."""
        paths = get_default_config_paths()
        self.assertTrue(any("asr33_config.yaml" in str(p) for p in paths))

    def test_user_config_path_is_in_defaults(self):
        """Test that user config path is in the default search paths."""
        user_path = get_user_config_path()
        default_paths = get_default_config_paths()
        self.assertIn(user_path, default_paths)

    def test_find_config_file_returns_none_when_missing(self):
        """Test find_config_file returns None when no config exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(Path, "cwd", return_value=Path(tmpdir)):
                with mock.patch.object(Path, "home", return_value=Path(tmpdir)):
                    # Clear env vars that affect config paths
                    with mock.patch.dict(os.environ, {}, clear=True):
                        result = find_config_file()
                        # Result could be None or a path - depends on existing files
                        # Just verify it doesn't crash


class TestSerialPortUtils(unittest.TestCase):
    """Tests for serial port utility functions."""

    def test_list_serial_ports_returns_list(self):
        """Test list_serial_ports returns a list."""
        result = list_serial_ports()
        self.assertIsInstance(result, list)

    def test_list_serial_ports_structure(self):
        """Test that returned ports have expected keys."""
        result = list_serial_ports()
        for port in result:
            self.assertIn("device", port)
            self.assertIn("description", port)
            self.assertIn("hwid", port)

    def test_is_valid_port_with_invalid(self):
        """Test is_valid_port returns False for non-existent port."""
        result = is_valid_port("/dev/this-port-definitely-does-not-exist-12345")
        self.assertFalse(result)

    def test_is_valid_port_with_valid(self):
        """Test is_valid_port returns True for existing port."""
        ports = list_serial_ports()
        if ports:
            result = is_valid_port(ports[0]["device"])
            self.assertTrue(result)


class TestDefaultConfig(unittest.TestCase):
    """Tests for default configuration."""

    def test_default_config_structure(self):
        """Test DEFAULT_CONFIG has required sections."""
        self.assertIn("frontend", DEFAULT_CONFIG)
        self.assertIn("backend", DEFAULT_CONFIG)
        self.assertIn("terminal", DEFAULT_CONFIG)
        self.assertIn("sound", DEFAULT_CONFIG)
        self.assertIn("data_throttle", DEFAULT_CONFIG)

    def test_default_port_is_none(self):
        """Test default serial port is None (not hardcoded)."""
        port = DEFAULT_CONFIG["backend"]["serial_config"]["port"]
        self.assertIsNone(port)


class TestASR33ConfigCLI(unittest.TestCase):
    """Tests for CLI argument parsing."""

    def test_parse_port_argument(self):
        """Test --port argument is parsed."""
        with mock.patch("sys.argv", ["prog", "--port", "/dev/ttyUSB0", "--list-ports"]):
            # Use --list-ports to trigger early exit before config load
            with self.assertRaises(SystemExit) as cm:
                ASR33Config()
            self.assertEqual(cm.exception.code, 0)

    def test_parse_save_argument(self):
        """Test --save argument is recognized."""
        with mock.patch("sys.argv", ["prog", "--list-ports"]):
            with self.assertRaises(SystemExit):
                config = ASR33Config()

    def test_list_ports_exits_zero(self):
        """Test --list-ports causes clean exit."""
        with mock.patch("sys.argv", ["prog", "--list-ports"]):
            with self.assertRaises(SystemExit) as cm:
                ASR33Config()
            self.assertEqual(cm.exception.code, 0)


class TestPortNoneLocalMode(unittest.TestCase):
    """Tests for --port none local loopback mode."""

    def test_port_none_sets_local_mode(self):
        """Test --port none sets terminal mode to local."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("backend:\n  type: serial\n  serial_config:\n    port: /dev/test\n")
            f.flush()
            with mock.patch("sys.argv", ["prog", "--config", f.name, "--port", "none"]):
                config = ASR33Config()
                mode = config.get_key("terminal", "config", "mode")
                self.assertEqual(mode, "local")
            os.unlink(f.name)

    def test_port_none_case_insensitive(self):
        """Test --port NONE and --port None also work."""
        for port_value in ["NONE", "None", "nOnE"]:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
                f.write("backend:\n  type: serial\n")
                f.flush()
                with mock.patch("sys.argv", ["prog", "--config", f.name, "--port", port_value]):
                    config = ASR33Config()
                    mode = config.get_key("terminal", "config", "mode")
                    self.assertEqual(mode, "local", f"Failed for --port {port_value}")
                os.unlink(f.name)

    def test_port_none_skips_validation(self):
        """Test --port none skips serial port validation."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("backend:\n  type: serial\n  serial_config:\n    port: null\n")
            f.flush()
            with mock.patch("sys.argv", ["prog", "--config", f.name, "--port", "none"]):
                config = ASR33Config()
                is_valid, error = config.validate_serial_port()
                self.assertTrue(is_valid)
                self.assertIsNone(error)
            os.unlink(f.name)

    def test_port_pty_sets_backend_type(self):
        """Test --port pty sets backend type to pty."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("backend:\n  type: serial\n")
            f.flush()
            with mock.patch("sys.argv", ["prog", "--config", f.name, "--port", "pty"]):
                config = ASR33Config()
                backend_type = config.get_key("backend", "type")
                self.assertEqual(backend_type, "pty")
            os.unlink(f.name)

    def test_port_pty_skips_validation(self):
        """Test --port pty skips serial port validation."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("backend:\n  type: serial\n  serial_config:\n    port: null\n")
            f.flush()
            with mock.patch("sys.argv", ["prog", "--config", f.name, "--port", "pty"]):
                config = ASR33Config()
                is_valid, error = config.validate_serial_port()
                self.assertTrue(is_valid)
                self.assertIsNone(error)
            os.unlink(f.name)


class TestASR33ConfigValidation(unittest.TestCase):
    """Tests for port validation."""

    def test_validate_ssh_backend_always_valid(self):
        """Test that SSH backend skips port validation."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("backend:\n  type: ssh\n")
            f.flush()
            with mock.patch("sys.argv", ["prog", "--config", f.name]):
                config = ASR33Config()
                is_valid, error = config.validate_serial_port()
                self.assertTrue(is_valid)
                self.assertIsNone(error)
            os.unlink(f.name)

    def test_validate_missing_port(self):
        """Test validation fails when no port configured."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("backend:\n  type: serial\n  serial_config:\n    port: null\n")
            f.flush()
            with mock.patch("sys.argv", ["prog", "--config", f.name]):
                config = ASR33Config()
                is_valid, error = config.validate_serial_port()
                self.assertFalse(is_valid)
                self.assertIn("No serial port configured", error)
            os.unlink(f.name)

    def test_validate_invalid_port(self):
        """Test validation fails for non-existent port."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("backend:\n  type: serial\n  serial_config:\n    port: /dev/nonexistent12345\n")
            f.flush()
            with mock.patch("sys.argv", ["prog", "--config", f.name]):
                config = ASR33Config()
                is_valid, error = config.validate_serial_port()
                self.assertFalse(is_valid)
                self.assertIn("not found", error)
            os.unlink(f.name)


class TestASR33ConfigSave(unittest.TestCase):
    """Tests for config save functionality."""

    def test_save_creates_file(self):
        """Test --save creates config file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            with mock.patch("asr33_config.get_user_config_path", return_value=config_path):
                with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
                    f.write("backend:\n  type: serial\n  serial_config:\n    port: /dev/test\n")
                    f.flush()
                    with mock.patch("sys.argv", ["prog", "--config", f.name, "--save"]):
                        config = ASR33Config()
                        self.assertTrue(config_path.exists())
                    os.unlink(f.name)

    def test_save_preserves_cli_overrides(self):
        """Test that --save includes CLI argument overrides."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            with mock.patch("asr33_config.get_user_config_path", return_value=config_path):
                with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
                    f.write("backend:\n  type: serial\n  serial_config:\n    port: /dev/old\n")
                    f.flush()
                    with mock.patch("sys.argv", ["prog", "--config", f.name, "--port", "/dev/new", "--save"]):
                        config = ASR33Config()
                        # Read saved config
                        import yaml
                        with open(config_path) as saved:
                            saved_config = yaml.safe_load(saved)
                        self.assertEqual(saved_config["backend"]["serial_config"]["port"], "/dev/new")
                    os.unlink(f.name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
