# GT7 Race Engineer — Windows beta 1.4

## Before you start: requirements and one-time setup

Everything the app itself needs is inside the ZIP (Python runtime, interface, offline speech model). You only need Windows and the items below.

| Need | Required? | How to get it |
|---|---|---|
| Windows 10 or 11, 64-bit | Yes | Nothing to install. Windows 7/8 and 32-bit are not supported. |
| A PS5 running Gran Turismo 7 on the **same home network** as this PC | Yes, for live data | PS5 → Settings → Network → View Connection Status → note the IP address. Enter it in the app under Settings, then Save. The Demo mode works without a PS5. |
| Microsoft Edge **WebView2 Runtime** | Only for "Open desktop app" | Already on Windows 11 and up-to-date Windows 10. If the desktop window will not open, install the "Evergreen Standalone Installer" from https://developer.microsoft.com/microsoft-edge/webview2/ or choose **Open in my browser** instead (no install needed). |
| Any modern browser (Edge, Chrome, Firefox) | Only for "Open in my browser" | Already installed on Windows. |
| **OBS Studio** | Only for stream overlays | Free from https://obsproject.com/. In OBS add a **Browser** source and paste an address from the app's **OBS Overlays** page (the page has a step-by-step tutorial). |
| Microphone and speakers/headset | Only for the voice engineer | Windows default devices are used. Allow microphone access when Windows asks (Settings → Privacy → Microphone). |
| Local AI model + `llama-server` | Optional, off by default | Not included. The app works fully without it. |

No Python, Node.js, Visual Studio runtimes, admin rights or internet connection are needed to run the app.

### Install in 4 steps
1. Download the ZIP and check it: in PowerShell run `Get-FileHash .\GT7-Race-Engineer-*-windows-x64.zip` and compare with the `.sha256` file.
2. **Extract the whole ZIP** (right-click → Extract All) to a normal folder such as `C:\GT7 Race Engineer` or your Documents. Do not run it from inside the ZIP, and do not move the EXE out of its folder.
3. Double-click **Create desktop shortcut.vbs** for a Desktop shortcut (optional), then double-click **GT7 Race Engineer.exe**. If Windows says "Windows protected your PC", choose **More info → Run anyway** (the beta is unsigned).
4. When Windows Firewall asks, tick **Private networks** and Allow, so the PS5's telemetry can reach the app. In Settings enter the PS5 IP, Save, start GT7, and run **Test telemetry - 15 seconds**.

### If something does not work
- Nothing happens when launching: extract the full ZIP first (not just the EXE), and check `%LOCALAPPDATA%\GT7 Race Engineer\desktop.log`.
- No live data: PS5 and PC must be on the same network, the PS5 IP must be right, and only one telemetry program can use UDP port 33740 at a time.
- Overlay blank in OBS: GT7 must be sending data, and the address must be copied from this PC's app. OBS on a different PC needs the LAN-address steps shown on the OBS Overlays page.
- Uninstall: delete the extracted folder. Your settings and recordings are in `%LOCALAPPDATA%\GT7 Race Engineer` (delete it too for a clean removal).

Privacy: the app is local-first. Telemetry, recordings and settings stay on your PC; nothing is uploaded unless you host or join a group event.


Windows 10/11, 64-bit. Extract the **entire ZIP**, then double-click **GT7 Race Engineer.exe**. Choose **Open desktop app** or **Open in my browser**. Python, Node and a console are not required. The executable stays alongside its `_internal` folder; do not move the EXE out on its own. Double-click **Create desktop shortcut.vbs** to put a normal shortcut on your Desktop. The optional VBS shortcuts directly select either mode.

Desktop mode uses Microsoft Edge WebView2, which must be installed on the computer. If unavailable, the launcher offers browser mode. Both modes use the same local application and data. Desktop mode is a native Windows application window rendering the local interface; it does not open a browser tab. Browser mode keeps a small controller window open so you can stop the receiver without a console.

The beta is unsigned; Windows may display an unknown-publisher notice. Verify the supplied SHA256 before running. No administrator privileges are required. The local backend binds to loopback only. If Windows Firewall asks, allow the app on your private LAN to receive the PS5's UDP packets. Do not open it to public networks.

Settings and recordings are in `%LOCALAPPDATA%\GT7 Race Engineer`. Set the PS5 address in Settings, save, then drive and run **Test telemetry - 15 seconds**. Only one telemetry receiver can own UDP 33740. If an existing GT7 application is already serving the configured local port, this launcher attaches to it and does not stop that other receiver when closed. New desktop/browser instances which start their own backend stop it on exit.

The Vosk small English model is bundled for offline push-to-talk. Input/output use Windows' default devices. Set your preferred devices in Windows Sound settings. Initialize the microphone and enable speech in Engineer. Windows uses installed system speech when eSpeak is absent; Linux uses eSpeak NG. No cloud speech account is needed.

Broadcast colors: throttle green, brake red, clutch baby blue, personal best green, ordinary laps yellow, overall fastest purple. GT7's player stream does not provide race-wide fastest laps, sector splits or race-control flags: these remain explicitly unavailable. Brand images are looked up locally from the received car ID. Unknown brands have a labeled fallback. Delta-colored driving lines require a complete clean reference lap after the opening partial lap; they show estimated time gained/lost relative to that reference, not an ideal racing line.

Logs: `desktop.log` and `runtime.log` in the user data folder. This is a beta: Windows executable, native renderer and local model are smoke-tested on the build PC; other PCs, audio hardware and long sessions still require testing. Orange Pi/Linux is a separate ARM64 release with its own installation guide.

## Engineer and sound update
The Engineer page contains 100 distinct requests, each with three rotating answer forms. Search the library or speak its exact requests with push-to-talk. Use Enable and test speaker to enable speech and clear mute. Settings lists output devices by name; the test uses that selection and does not need microphone input. Playback status distinguishes synthesis, playback, completion and failure. Windows system speech is rendered to PCM and played through the same selected-device path as eSpeak/Piper. If the software reports completion but nothing is audible, check that the named Windows device is the intended speaker/headset and that its hardware volume is on.


Hands-free update: the offline microphone starts automatically. Speak a request and pause; use Pause listening for manual PTT. Recognition briefly pauses during engineer speech to prevent feedback. Heartbeat defaults to 1 second; subsecond settings down to 0.25 seconds are available but do not increase the 60 Hz telemetry stream.

For current source features and a step-by-step introduction, read [README](../README.md) and the [new-user guide](../docs/USER_GUIDE.md). 

## 1.4 update
**OBS Overlays** replaces Studio: every overlay has a fixed local address (Browser Source URL), no league needed, adjustable width/height, and one driver focus for all overlays; see the tutorial on that page. **Settings → Image pack folder** lets you choose a folder with `cars/`, `brands/` and `tracks/` images named by ID; bundled images are the fallback.
