"""Dashboard modules package.

Provides central configs, file IO, serial telemetry parsing, solar Edge/Chillicon clients,
Open-Meteo weather integrations, FFT spectral models, and Gemini AI wrappers.

Module Map:
1. config: Styling defaults, layouts, colors, coordinates, fonts, and global constants.
2. io: Thread-safe file handling, atomic file writes, null-byte stripping for corrupted CSV lines.
3. telemetry: Parses raw hex XML payloads from EMU-2 USB serial, manages 24h usage queues.
4. solar: SolarEdge currentPowerFlow API and Chillicon session cookie authentication managers.
5. weather: Forecast and historical Open-Meteo API query integration.
6. spectral: Headless math library for Discrete Fourier Transforms (DFT), curve derivatives/slopes, and SNR calculations.
7. ai: Interfaces with Vertex AI GenAI SDK for Gemini 2.5 Flash batch prediction and GCS pipeline uploads.
"""

from . import config
from . import io
from . import telemetry
from . import solar
from . import weather
from . import spectral
from . import ai
