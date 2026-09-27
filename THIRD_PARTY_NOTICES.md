# Third-party notices

## Protocol port

Native protocol code is based on **MacManley/gt7-udp**, copyright 2026 MacManley, MIT, commit `a768574ba809429ce0455b988794e028660f6b9b`. The complete upstream license and studied sources are preserved in `vendor/gt7-udp/`. Preserve these notices in redistributed copies. The upstream C++ files are references; the runtime does not import an Arduino library.

## Runtime and bundled UI

| Component | License / role |
|---|---|
| Python | Python Software Foundation license; installed separately |
| FastAPI | MIT; API framework |
| Uvicorn | BSD-3-Clause; HTTP/ASGI server |
| Pydantic / pydantic-core | MIT; configuration validation |
| Starlette | BSD-3-Clause; ASGI infrastructure |
| PyCryptodome | BSD/Public Domain portions; Salsa20 |
| wsproto / h11 | MIT; lightweight WebSocket/HTTP transport |
| React / React DOM | MIT; bundled UI |
| uPlot | MIT; bundled charts |
| Lucide | ISC plus documented icon portions; bundled icons |
| Vite / TypeScript / Rollup / esbuild | Build-time tools, respective MIT/Apache-2.0 licenses |
| pytest / Playwright | MIT / Apache-2.0; test tools |
| Vosk | Apache-2.0; optional offline recognizer |
| sounddevice | MIT; optional PortAudio wrapper |
| PortAudio | MIT-style; native audio dependency |
| eSpeak NG | GPL-3.0-or-later; separately installed optional system speech engine |
| Piper, current OHF-Voice/piper1-gpl | GPL-3.0; optional separately selected engine |

Exact Python packages are in requirements-lock.txt; frontend packages and integrity values in frontend/package-lock.json. License copies for directly bundled UI libraries are included in docs/licenses. Before distributing a binary image/appliance, audit **all transitive dependencies** and satisfy their source/notice obligations; this summary is not a legal determination.

## Speech models are separate works

The setup script offers `vosk-model-small-en-us-0.15` (~40 MB) from the official Vosk model catalog, labeled Apache-2.0 there. Model download is explicit; model files are not bundled in this repository. The download script stores the observed SHA256 and supports verification against a user-supplied trusted digest.

Piper voices have individual model-card licenses which can differ from the engine license. Review the exact voice terms before download/distribution. The app does not auto-download or bundle a Piper voice. A subprocess boundary does **not** automatically resolve GPL distribution obligations. eSpeak NG also has GPL obligations if redistributed. No promise of a proprietary-license exception is made.

## Attribution, branding and data

Gran Turismo and PlayStation are trademarks of their respective owners. This independent application is not affiliated with or endorsed by Sony or Polyphony Digital. Car and circuit identification artwork and the release Vosk model are included as documented below; no personal racing captures or proprietary track-boundary maps are bundled. Demo data and packet fixtures are synthetic; provenance is documented in PROTOCOL.md.

## Bundled offline speech model
Vosk small English US 0.15, published by Alpha Cephei: https://alphacephei.com/vosk/models. Apache-2.0; full license in docs/licenses/vosk-model-Apache-2.0.txt. Download provenance and observed hash are included in models/vosk-download.json in the desktop package. Python dependencies retain their license metadata inside bundled wheels. System GTK/WebKit and eSpeak are installed through Ubuntu apt.

## Car identity and manufacturer images
Car ID/name/manufacturer mapping: ddm999/gt7info (MIT-0), pinned in docs/car-assets-provenance.json; license preserved in docs/licenses/car-database-MIT-0.txt. Manufacturer thumbnails: filippofilip95/car-logos-dataset, repository states MIT with logos remaining the property of their respective owners; original source URLs and commit are preserved in docs/car-assets-provenance.json and repository README in docs/licenses/car-logos-README.md. These marks identify the car manufacturer; the application is not affiliated with those brands, Gran Turismo, or Formula One.


## Circuit catalogue and car thumbnails

Circuit venue/layout metadata is from ddm999/gt7info, pinned to b05de685c63c6df2eb86887c8929883e66f93956 (MIT-0; existing database license under docs/licenses). Circuit logos are identification artwork from that repository; missing logos use original SVG text badges. Car thumbnails are transparent PNGs from the official Gran Turismo 7 car list, keyed by the numeric car ID. These images and trademarks remain property of Sony Interactive Entertainment, Polyphony Digital, vehicle manufacturers and other respective rights holders; the database MIT-0 license does not grant ownership of that artwork. This application is not endorsed by them. Sources and checksums are recorded in docs/track-car-assets-provenance.json. Learned circuit maps are derived from the user's received positions, not game track-boundary artwork.

## Offline track references

Normalized vector outlines are derived from jbhoorasingh/gt7-datalogger-track-data at revision d8b769c6f2ead4d5390dc94831e20be93d7bf801 (CC0), including upstream zetetos/gt-telemetry captures (MIT). License notices: docs/licenses/track-reference-CC0.txt and docs/licenses/track-reference-upstream-MIT.txt. Per-layout attribution, exclusions and pinned source hashes: docs/TRACK_REFERENCE_COVERAGE.md and backend/app/data/track-references.json.
