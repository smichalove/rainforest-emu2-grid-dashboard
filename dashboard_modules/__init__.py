"""Dashboard modules package.

Provides central configs, file IO, serial telemetry parsing, solar Edge/Chillicon clients,
Open-Meteo weather integrations, FFT spectral models, and Gemini AI wrappers.
"""

from . import config
from . import io
from . import telemetry
from . import solar
from . import weather
from . import spectral
from . import ai
