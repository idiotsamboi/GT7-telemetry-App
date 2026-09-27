# GT7 Race Engineer — Windows beta 1.2

Windows 10/11, 64-bit. Extract the **entire ZIP**, then double-click **GT7 Race Engineer.exe**. Choose **Open desktop app** or **Open in my browser**. Python, Node and a console are not required. The executable stays alongside its `_internal` folder; do not move the EXE out on its own. You can create an ordinary Windows desktop shortcut to it. The optional VBS shortcuts directly select either mode.

Desktop mode uses Microsoft Edge WebView2, which must be installed on the computer. If unavailable, the launcher offers browser mode. Both modes use the same local application and data. Desktop mode is a native Windows application window rendering the local interface; it does not open a browser tab. Browser mode keeps a small controller window open so you can stop the receiver without a console.

The beta is unsigned; Windows may display an unknown-publisher notice. Verify the supplied SHA256 before running. No administrator privileges are required. The local backend binds to loopback only. If Windows Firewall asks, allow the app on your private LAN to receive the PS5's UDP packets. Do not open it to public networks.

Settings and recordings are in `%LOCALAPPDATA%\GT7 Race Engineer`. Set the PS5 address in Settings, save, then drive and run **Test telemetry - 15 seconds**. Only one telemetry receiver can own UDP 33740. If an existing GT7 application is already serving the configured local port, this launcher attaches to it and does not stop that other receiver when closed. New desktop/browser instances which start their own backend stop it on exit.

The Vosk small English model is bundled for offline push-to-talk. Input/output use Windows' default devices. Set your preferred devices in Windows Sound settings. Initialize the microphone and enable speech in Engineer. Windows uses installed system speech when eSpeak is absent; Linux uses eSpeak NG. No cloud speech account is needed.

Broadcast colors: throttle green, brake red, clutch baby blue, personal best green, ordinary laps yellow, overall fastest purple. GT7's player stream does not provide race-wide fastest laps, sector splits or race-control flags: these remain explicitly unavailable. Brand images are looked up locally from the received car ID. Unknown brands have a labeled fallback. Delta-colored driving lines require a complete clean reference lap after the opening partial lap; they show estimated time gained/lost relative to that reference, not an ideal racing line.

Logs: `desktop.log` and `runtime.log` in the user data folder. This is a beta: Windows executable, native renderer and local model are smoke-tested on the build PC; other PCs, audio hardware and long sessions still require testing. Orange Pi/Linux is a separate ARM64 release with its own installation guide.

## Engineer and sound update
The Engineer page contains 100 distinct requests, each with three rotating answer forms. Search the library or speak its exact requests with push-to-talk. Use Enable and test speaker to enable speech and clear mute. Settings lists output devices by name; the test uses that selection and does not need microphone input. Playback status distinguishes synthesis, playback, completion and failure. Windows system speech is rendered to PCM and played through the same selected-device path as eSpeak/Piper. If the software reports completion but nothing is audible, check that the named Windows device is the intended speaker/headset and that its hardware volume is on.
