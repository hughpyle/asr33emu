#!/usr/bin/env python3

"""
ASR-33 Teletype Emulator

Usage examples:
    python asr33emu.py --list-ports
    python asr33emu.py --port /dev/cu.usbserial-A50285BI
    python asr33emu.py --port COM3 --baud 110 --save
    python asr33emu.py --backend ssh --config my_config.yaml
"""

import sys

from asr33_config import ASR33Config
from asr33_backend_serial import SerialBackend
from asr33_backend_ssh import SSHV2Backend
from asr33_shim_throttle import DataThrottle
from asr33_terminal import Terminal
from asr33_sounds_sm import ASR33AudioModule as ASR33_Sounds
from asr33_frontend_pygame import ASR33PygameFrontend as PygameFrontend
from asr33_frontend_tk import ASR33TkFrontend as TkFrontend


DEFAULT_FRONTEND = "tkinter"
DEFAULT_BACKEND = "serial"


class NullBackend:
    """Null backend for local loopback mode - does nothing."""

    def __init__(self, upper_layer=None):
        self.upper_layer = upper_layer

    def send_data(self, data: bytes) -> None:
        """Discard sent data."""
        pass

    def receive_data(self, data: bytes) -> None:
        """No data to receive."""
        pass

    def get_info_string(self) -> str:
        """Return info string."""
        return "local"

    def close(self) -> None:
        """Nothing to close."""
        pass


class EmulatorWrapper:
    """ASR-33 Emulator Wrapper Class"""

    def __init__(self, config: ASR33Config):
        """
        Initialize the emulator with the given configuration.

        Args:
            config: ASR33Config instance (already loaded and validated)
        """
        self.comm_backend = None
        self.data_throttle = None
        self.term = None
        self.frontend = None

        cfg_data = config.get_merged_config()

        # Extract relevant config sections
        frontend_cfg = cfg_data.frontend
        backend_cfg = cfg_data.backend
        data_throttle_cfg = cfg_data.data_throttle
        terminal_cfg = cfg_data.terminal

        # Check if we're in local loopback mode
        term_mode = terminal_cfg.config.get("mode", default="line")

        # Backend
        if term_mode == "local":
            # Local loopback mode - use null backend
            self.comm_backend = NullBackend(upper_layer=None)
        else:
            backend_type = backend_cfg.get("type", default=DEFAULT_BACKEND)
            if backend_type == "serial":
                cfg = backend_cfg.serial_config
                self.comm_backend = SerialBackend(
                    upper_layer=None,  # Forward reference set later
                    config=cfg
                )
            elif backend_type == "ssh":
                cfg = backend_cfg.ssh_config
                self.comm_backend = SSHV2Backend(
                    upper_layer=None,
                    config=cfg
                )
            else:
                raise ValueError(f"Unsupported backend type: {backend_type}")

        # Comm backend feeds data to DataThrottle, which feeds data to Terminal
        cfg = data_throttle_cfg.config
        self.data_throttle = DataThrottle(
            lower_layer=self.comm_backend,
            upper_layer=None,  # Forward reference set later
            config=cfg
        )

        # Terminal
        cfg = terminal_cfg.config
        self.term = Terminal(
            comm_interface=self.data_throttle,
            frontend=None,  # Forward reference set later
            config=cfg
        )

        # ASR-33 sound support
        self.sound = ASR33_Sounds()

        # Frontend
        frontend_type = frontend_cfg.get("type", default=DEFAULT_FRONTEND)
        if frontend_type == "pygame":
            self.frontend = PygameFrontend(
                terminal=self.term,
                backend=self.data_throttle,
                config=cfg_data,
                sound=self.sound
            )
        elif frontend_type == "tkinter":
            self.frontend = TkFrontend(
                terminal=self.term,
                backend=self.data_throttle,
                config=cfg_data,
                sound=self.sound,
            )
        else:
            raise ValueError(f"Unsupported frontend: {frontend_type}")

        # Assign layers that were forward referenced earlier
        if self.comm_backend is not None:
            self.comm_backend.upper_layer = self.data_throttle
        self.data_throttle.upper_layer = self.term
        self.term.frontend = self.frontend

    def run(self):
        """Run the emulator main loop."""
        if self.frontend is None:
            raise RuntimeError("Frontend not initialized")
        self.frontend.run()


def main():
    """Main entry point for the ASR-33 emulator."""
    # Load and parse configuration (handles --list-ports, --help internally)
    config = ASR33Config(description="ASR-33 Teletype Emulator")

    # Validate serial port if using serial backend
    is_valid, error = config.validate_serial_port()
    if not is_valid:
        config.print_port_help()
        sys.exit(1)

    # Create and run emulator
    emulator = EmulatorWrapper(config)
    emulator.run()


if __name__ == "__main__":
    main()
