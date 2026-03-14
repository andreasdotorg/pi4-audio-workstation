"""Mock CamillaClient replacement for testing without CamillaDSP.

Replaces ``camilladsp.CamillaClient`` so that the measurement script can
run on macOS without a running CamillaDSP instance.  All methods are
no-ops or return static values matching a production-like configuration.

Usage::

    if mock_mode:
        from mock.mock_camilladsp import MockCamillaClient as CamillaClient
        from mock.mock_camilladsp import MockProcessingState as ProcessingState
    else:
        from camilladsp import CamillaClient, ProcessingState
"""

import enum


class MockProcessingState(enum.Enum):
    """Mirror of ``camilladsp.ProcessingState``."""
    RUNNING = "Running"
    PAUSED = "Paused"
    INACTIVE = "Inactive"


class _MockConfigNamespace:
    """Namespace for ``client.config.*`` methods."""

    def __init__(self, measurement_mode=False):
        self._file_path = "/etc/camilladsp/active.yml"
        self._measurement_mode = measurement_mode

    def file_path(self):
        """Return the current config file path."""
        return self._file_path

    def set_file_path(self, path):
        """Store the config file path (no-op beyond storage)."""
        self._file_path = path

    def active(self):
        """Return the active config dict.

        If measurement_mode is True, returns a config containing the
        measurement attenuation filter (-20 dB gain).  Otherwise returns
        a production-like config without measurement attenuation.
        """
        base = {
            "devices": {
                "samplerate": 48000,
                "chunksize": 2048,
                "queuelimit": 4,
                "capture": {
                    "type": "Alsa",
                    "channels": 8,
                    "device": "hw:Loopback,1,0",
                    "format": "S32LE",
                },
                "playback": {
                    "type": "Alsa",
                    "channels": 8,
                    "device": "hw:USBStreamer,0",
                    "format": "S32LE",
                },
            },
        }
        if self._measurement_mode:
            base["filters"] = {
                "ch0_gain": {
                    "type": "Gain",
                    "parameters": {"gain": -20.0},
                },
            }
        return base


class _MockGeneralNamespace:
    """Namespace for ``client.general.*`` methods."""

    def reload(self):
        """No-op reload."""
        pass

    def state(self):
        """Return RUNNING state."""
        return MockProcessingState.RUNNING


class MockCamillaClient:
    """Drop-in replacement for ``camilladsp.CamillaClient``.

    Parameters
    ----------
    host : str
        Ignored in mock mode.
    port : int
        Ignored in mock mode.
    measurement_mode : bool
        If True, ``config.active()`` returns a measurement config with
        -20 dB attenuation filter.  Default False (production config).
    """

    def __init__(self, host="localhost", port=1234, measurement_mode=False):
        self._host = host
        self._port = port
        self.config = _MockConfigNamespace(measurement_mode=measurement_mode)
        self.general = _MockGeneralNamespace()

    def connect(self):
        """No-op connect."""
        pass

    def disconnect(self):
        """No-op disconnect."""
        pass
