// KWin script: raise and focus the GTA IV window. The game freezes its simulation while
// unfocused, which stalls a scripted route. Loaded and run by route.py over D-Bus.
// Match the window's identity, not its caption: a terminal titled after this harness
// ("gtaiv-precompile-test") must never be the one that gets focused. Under Proton's
// native Wayland driver the identity is the app_id (the exe name or steam_app_<id>);
// under Xwayland it is the WM_CLASS, which Proton sets to steam_app_<id>.
var ids = ["gtaiv.exe", "steam_app_12210"];
var ws = workspace.windowList ? workspace.windowList() : workspace.clientList();
for (var i = 0; i < ws.length; i++) {
    var w = ws[i];
    var keys = [w.resourceClass, w.resourceName, w.desktopFileName];
    for (var k = 0; k < keys.length; k++) {
        if (ids.indexOf(String(keys[k] || "").toLowerCase()) >= 0) {
            w.minimized = false;
            workspace.activeWindow = w;
            break;
        }
    }
}
