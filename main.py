import os, sys, shutil, tempfile, subprocess, threading, time, asyncio, base64, platform
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from starlette.staticfiles import StaticFiles
import uvicorn

APP_XML = """<?xml version="1.0" encoding="utf-8"?>
<application xmlns="http://ns.adobe.com/air/application/33.1">
  <id>MovieStarPlanet.MacShell.CPU</id>
  <filename>MovieStarPlanet</filename>
  <name>MovieStarPlanet</name>
  <versionNumber>1.0.0</versionNumber>
  <supportedProfiles>extendedDesktop desktop</supportedProfiles>
  <initialWindow>
    <content>MovieStarPlanet.swf</content>
    <visible>true</visible>
    <systemChrome>standard</systemChrome>
    <transparent>false</transparent>
    <autoOrients>false</autoOrients>
    <renderMode>cpu</renderMode>
  </initialWindow>
</application>
"""

STATE = {"running": False, "pid": None, "tmp": None}
LOCK = threading.Lock()
PROCS = {"xvfb": None, "wm": None, "vnc": None}

def novnc_dir():
    d = "/opt/novnc"
    return d if os.path.isdir(d) else ("./novnc" if os.path.isdir("./novnc") else None)

def start_x_stack():
    if PROCS["xvfb"] and PROCS["xvfb"].poll() is None:
        return
    xvfb = subprocess.Popen(["Xvfb", ":99", "-screen", "0", "1280x800x24", "-ac"])
    time.sleep(0.6)
    env = {**os.environ, "DISPLAY": ":99"}
    wm = subprocess.Popen(["fluxbox"], env=env)
    vnc = subprocess.Popen(["x11vnc", "-display", ":99", "-localhost", "-forever",
                            "-shared", "-nopw", "-rfbport", "5900"])
    PROCS.update({"xvfb": xvfb, "wm": wm, "vnc": vnc})

def _ensure_exec(p):
    try:
        st = os.stat(p)
        if not (st.st_mode & 0o111):
            os.chmod(p, st.st_mode | 0o111)
    except Exception:
        pass

def find_adl():
    base = os.path.dirname(os.path.abspath(__file__))
    sdk = os.environ.get("AIRSDK_HOME", "").strip() or os.path.join(base, "AIRSDK_51.2.2")
    if not os.path.isdir(sdk): return None, False
    b = os.path.join(sdk, "bin")
    mach = platform.machine().lower()
    linux_cands = []
    if sys.platform.startswith("linux"):
        if "arm" in mach or "aarch64" in mach:
            linux_cands = ["adl_linux_arm64", "adl"]
        else:
            linux_cands = ["adl_linux64", "adl", "adl64"]
    for n in linux_cands:
        p = os.path.join(b, n)
        if os.path.exists(p):
            _ensure_exec(p)
            return p, False
    for n in ["adl.exe", "adl64.exe"]:
        p = os.path.join(b, n)
        if os.path.exists(p):
            return p, True
    p = os.path.join(b, "adl")
    if os.path.exists(p):
        _ensure_exec(p)
        return p, False
    return None, False

def preflight():
    base = os.path.dirname(os.path.abspath(__file__))
    adl, use_wine = find_adl()
    if not adl:
        return False, "AIRSDK/ADL not found"
    res = os.path.join(base, "Resources")
    if not os.path.isdir(res) or not os.path.exists(os.path.join(res, "MovieStarPlanet.swf")):
        return False, "Resources/MovieStarPlanet.swf missing"
    return True, {"adl": adl, "use_wine": use_wine, "resources": res}

def build_cmd(adl_path, use_wine, appxml, tmpdir):
    screensize = os.environ.get("SCREENSIZE", "1280x800:1280x800")
    if use_wine and sys.platform.startswith("linux"):
        return ["wine", adl_path, "-nodebug", "-screensize", screensize, appxml, tmpdir]
    return [adl_path, "-nodebug", "-screensize", screensize, appxml, tmpdir]

def sweep_tmp_later(path):
    def f():
        try: shutil.rmtree(path, ignore_errors=True)
        except: pass
    threading.Timer(60, f).start()

def launch_once():
    with LOCK:
        if STATE["running"]:
            return
        STATE.update({"running": True, "pid": None, "tmp": None})
    ok, data = preflight()
    if not ok:
        with LOCK:
            STATE.update({"running": False})
        return
    start_x_stack()
    adl, use_wine, resources = data["adl"], data["use_wine"], data["resources"]
    tmp = tempfile.mkdtemp(prefix="msp_")
    try:
        for n in os.listdir(resources):
            s = os.path.join(resources, n); d = os.path.join(tmp, n)
            shutil.copytree(s, d) if os.path.isdir(s) else shutil.copy2(s, d)
        with open(os.path.join(tmp, "application.xml"), "w", encoding="utf-8") as f:
            f.write(APP_XML)  # IMPORTANT: no query string in <content>
        cmd = build_cmd(adl, use_wine, os.path.join(tmp, "application.xml"), tmp)
        env = {**os.environ, "DISPLAY": ":99", "WINEDEBUG": "-all", "LIBGL_ALWAYS_SOFTWARE": "1"}
        p = subprocess.Popen(cmd, cwd=tmp, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
        with LOCK:
            STATE.update({"pid": p.pid, "tmp": tmp})
    except Exception:
        with LOCK:
            STATE.update({"running": False})
        sweep_tmp_later(tmp)
        return
    # leave tmp for a bit so ADL can read assets; clean later
    sweep_tmp_later(tmp)

# --------------------- FastAPI app ---------------------
app = FastAPI()

NDIR = novnc_dir()
if NDIR:
    app.mount("/novnc", StaticFiles(directory=NDIR, html=True), name="novnc")

@app.on_event("startup")
def boot():
    start_x_stack()

# Auto-launch and immediately go to the viewer
@app.get("/", response_class=HTMLResponse)
def index():
    return """<!DOCTYPE html><meta charset="utf-8"><title>Launching…</title>
<script>
fetch('/launch', {method:'POST'}).finally(()=>{ location.replace('/play'); });
</script>
<body style="margin:0;background:#000;color:#fff;font:14px system-ui;display:flex;align-items:center;justify-content:center;height:100vh">
Launching…</body>"""

@app.post("/launch")
def launch():
    threading.Thread(target=launch_once, daemon=True).start()
    return {"ok": True}

@app.get("/play", response_class=HTMLResponse)
def play():
    if not NDIR:
        return HTMLResponse("<!DOCTYPE html><meta charset='utf-8'><body style='margin:0;background:#000;color:#fff;font:14px system-ui;padding:16px'>noVNC not found in image.</body>")
    # NOTE: 'path=ws' (no leading slash) so the URL is /ws, not //ws
    u = "/novnc/vnc_lite.html?path=ws&autoconnect=true&resize=scale&reconnect=1&quality=6&title=MovieStarPlanet"
    return f"<!DOCTYPE html><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>MovieStarPlanet</title><style>html,body{{height:100%;margin:0;background:#000}}</style><script>location.href='{u}';</script><a href='{u}' style='color:#8cf'>Open Viewer</a>"

# WebSocket bridge for noVNC → x11vnc
@app.websocket("/ws")
async def ws_proxy(ws: WebSocket):
    req = (ws.headers.get("sec-websocket-protocol") or "").replace(" ","").split(",")
    sub = "binary" if "binary" in req else ("base64" if "base64" in req else None)
    if sub: await ws.accept(subprotocol=sub)
    else:   await ws.accept()
    use_b64 = (sub == "base64")
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", 5900)
    except:
        await ws.close(code=1011); return

    async def ws_to_tcp():
        try:
            while True:
                msg = await ws.receive()
                t = msg.get("type")
                if t == "websocket.receive":
                    if msg.get("bytes") is not None:
                        data = msg["bytes"]
                    else:
                        txt = msg.get("text") or ""
                        data = base64.b64decode(txt) if use_b64 else txt.encode("latin1","ignore")
                    if data:
                        writer.write(data); await writer.drain()
                elif t == "websocket.disconnect":
                    break
        finally:
            try: writer.close()
            except: pass

    async def tcp_to_ws():
        try:
            while True:
                data = await reader.read(32768)
                if not data: break
                if use_b64: await ws.send_text(base64.b64encode(data).decode("ascii"))
                else:       await ws.send_bytes(data)
        finally:
            try: await ws.close()
            except: pass

    await asyncio.gather(ws_to_tcp(), tcp_to_ws())

def main():
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")

if __name__ == "__main__":
    main()
