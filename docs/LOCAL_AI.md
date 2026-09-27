# Local AI: Orange Pi 4 Pro 4GB

The first implementation uses Qwen2.5-0.5B-Instruct Q4_K_M through a separate llama.cpp CPU process. It selects up to three observations from at most eight calculated facts; the displayed numbers and advice come from validated telemetry, not generated claims. Fuel and data-quality priorities cannot be removed by the model. The Engineer page has a briefing and refresh button; Settings enables the model and selects its files. Calculated summaries work without the model.

## Resource settings

Two CPU threads, one inference at a time, 1536-token context, 48 output tokens, zero GPU layers and disabled extra RAM cache. Requests default to every 45 seconds. No raw 60 Hz telemetry is sent to the model. Linux starts the model at nice 10, checks available memory and temperature, and falls back when telemetry processing is under pressure. Startup requires 1100 MB available; running inference stops below 512 MB available, above 75 C, or above 1200 MB model RSS. These are monitored limits, not hard OS memory reservations. Inactive telemetry unloads the model after 120 seconds. No cloud service is used.

## ARM64 setup

Use a 64-bit Linux installation and Python 3.12 or later. From this source folder:

```sh
python3 scripts/install-local-ai.py --platform arm64 --directory "$HOME/.local/share/gt7-race-engineer/local-ai"
find "$HOME/.local/share/gt7-race-engineer/local-ai/arm64" -name llama-server
```

In Settings, select the downloaded GGUF and the exact llama-server path printed by find, enable Local AI, and retain the 45-second interval initially. For the 4GB board, start with a 6 Hz UI refresh rate and close other memory-heavy applications. The installer verifies pinned SHA-256 hashes before extraction. It requires internet access once; inference then runs offline. ARM64 runtime compatibility and performance must be tested on the board. No NPU acceleration is implemented.

For source-checkout verification, install to the default data/local-ai folder and run `python3 scripts/verify-local-ai.py`. This uses synthetic evidence and writes docs/local-ai-validation.json. The current validation was performed on the Windows development computer, not Orange Pi hardware. Existing 1.3.0 release archives predate this AI implementation.

## Sources

- [Official Orange Pi board definition (A733)](https://github.com/orangepi-xunlong/orangepi-build/blob/next/external/config/boards/orangepi4pro.conf)
- [Official Qwen GGUF model and Apache 2.0 license](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF)
- [llama.cpp b11201 runtime](https://github.com/ggml-org/llama.cpp/releases/tag/b11201)
