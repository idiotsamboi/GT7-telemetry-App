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

Gran Turismo and PlayStation are trademarks of their respective owners. This independent application is not affiliated with or endorsed by Sony or Polyphony Digital. No game artwork, car-logo pack, proprietary track maps, personal racing captures or pretrained speech models are bundled. Demo data and packet fixtures are synthetic; provenance is documented in PROTOCOL.md.

## Bundled offline speech model
Vosk small English US 0.15, published by Alpha Cephei: https://alphacephei.com/vosk/models. Apache-2.0; full license in docs/licenses/vosk-model-Apache-2.0.txt. Download provenance and observed hash are included in models/vosk-download.json in the desktop package. Python dependencies retain their license metadata inside bundled wheels. System GTK/WebKit and eSpeak are installed through Ubuntu apt.

## Car identity and manufacturer images
Car ID/name/manufacturer mapping: ddm999/gt7info (MIT-0), pinned in docs/car-assets-provenance.json; license preserved in docs/licenses/car-database-MIT-0.txt. Manufacturer thumbnails: filippofilip95/car-logos-dataset, repository states MIT with logos remaining the property of their respective owners; original source URLs and commit are preserved in docs/car-assets-provenance.json and repository README in docs/licenses/car-logos-README.md. These marks identify the car manufacturer; the application is not affiliated with those brands, Gran Turismo, or Formula One.
