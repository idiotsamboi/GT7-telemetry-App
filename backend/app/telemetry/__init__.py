"""Telemetry package. The wire parser lives in `parser.py`; everything it exported is re-exported here,
so `from backend.app.telemetry import parse, Sample, ...` keeps working unchanged.

Other modules (import them explicitly, e.g. `from backend.app.telemetry import bus`):
  units    canonical units and conversions      frame    TelemetryFrame + channel catalogue (CHANNELS)
  derived  calculated channels + DerivedEngine   bus      in-process TelemetryBus and events
  sources  TelemetrySource protocol + ScenarioDemo
"""
from .parser import (UPSTREAM, PARSER_VERSION, LENGTHS, XOR, KEY, FIELDS, CAPABILITIES, UNSUPPORTED, MAGIC,
                     PacketError, Sample, Sequence, decrypt_datagram, parse, demo_sample, _LAYOUT)
from . import units
from .frame import CHANNELS, Channel, FrameMeta, TelemetryFrame, experimental_channel_ids, public_channels
from .derived import DERIVED, DerivedChannel, DerivedEngine, DerivedState
from .bus import TelemetryBus, TelemetryEvent, Subscription
from .sources import SCENARIOS, ReplayControls, ScenarioDemo, ScenarioItem, SourceKind, TelemetrySource
