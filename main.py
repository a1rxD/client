import os, sys, shutil, tempfile, subprocess, threading, time, asyncio, base64, struct, platform
from fastapi import FastAPI, Query, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, FileResponse
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
    <content>{content}</content>
    <visible>true</visible>
    <systemChrome>standard</systemChrome>
    <transparent>false</transparent>
    <autoOrients>false</autoOrients>
    <renderMode>cpu</renderMode>
  </initialWindow>
</application>
"""

HTML_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MSP</title>
<style>
html,body{height:100%;margin:0;color:#fff;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Ubuntu,Helvetica,Arial,sans-serif}
body{background-image:linear-gradient(rgba(0,0,0,.55),rgba(0,0,0,.55)),url('/background.jpg');background-position:center;background-size:cover;background-attachment:fixed;background-repeat:no-repeat}
.wrap{display:flex;align-items:center;justify-content:center;height:100%}
.card{background:rgba(255,255,255,.08);backdrop-filter:blur(8px);padding:24px 20px;border-radius:16px;box-shadow:0 10px 30px rgba(0,0,0,.35);width:360px}
select,button{appearance:none;background:rgba(0,0,0,.35);color:#fff;border:1px solid rgba(255,255,255,.18);border-radius:12px;padding:12px 16px;font-size:16px;outline:none;width:100%}
button{margin-top:10px;cursor:pointer}
#status{margin-top:10px;font-size:12px;opacity:.95;white-space:pre-wrap}
a{color:#9ddcff;text-decoration:none}
</style></head>
<body>
<div class="wrap"><div class="card">
  <h1 style="margin:0 0 12px 0;font-size:18px">Choose country</h1>
  <form id="f">
    <select name="code">
      <option value="gb">United Kingdom</option><option value="au">Australia</option><option value="ca">Canada</option>
      <option value="de">Deutschland</option><option value="dk">Danmark</option><option value="es">España</option>
      <option value="fr">France</option><option value="ie">Ireland</option><option value="nl">Nederland</option>
      <option value="nz">New Zealand</option><option value="no">Norge</option><option value="pl">Polska</option>
      <option value="fi">Suomi</option><option value="se">Sverige</option><option value="tr">Türkiye</option>
      <option value="us">United States</option>
    </select>
    <button type="submit">Play MovieStarPlanet</button>
  </form>
  <div id="status"></div>
  <div style="margin-top:8px">
    <a href="/logs?type=out" target="_blank">stdout</a> · <a href="/logs?type=err" target="_blank">stderr</a> · <a href="/diag" target="_blank">diag</a> · <a href="/test-gui" target="_blank">test-gui</a>
  </div>
</div></div>
<script>
const s=document.getElementById("status"); let poll=null;
document.getElementById("f").addEventListener("submit",async e=>{
  e.preventDefault();
  s.textContent="Launching...";
  if(poll){clearInterval(poll);poll=null}
  const code=new FormData(e.target).get("code");
  const r=await fetch("/launch?code="+encodeURIComponent(code),{method:"POST"});
  const j=await r.json();
  if(!j.ok){s.textContent=j.message;return}
  poll=setInterval(async()=>{
    const rs=await fetch("/status"); const js=await rs.json();
    s.textContent=js.phase.toUpperCase()+": "+js.message;
    if(js.phase==="running"){clearInterval(poll);poll=null;location.href="/play"}
    if(js.phase==="error"){clearInterval(poll);poll=null}
  },600);
});
</script>
</body></html>"""

STATE={"phase":"idle","message":"","pid":None,"code":None,"tmp":None}
LOCK=threading.Lock()
PROCS={"xvfb":None,"wm":None,"vnc":None}

def resolve_novnc_dir():
    d=os.path.join("/opt","novnc")
    return d if os.path.isdir(d) else ("./novnc" if os.path.isdir("./novnc") else None)

def start_x_stack():
    if PROCS["xvfb"] and PROCS["xvfb"].poll() is None:
        return
    xvfb=subprocess.Popen(["Xvfb",":99","-screen","0","1280x800x24","-ac"])
    time.sleep(0.7)
    env=dict(os.environ); env["DISPLAY"]=":99"
    wm=subprocess.Popen(["fluxbox"],env=env)
    vnc=subprocess.Popen(["x11vnc","-display",":99","-localhost","-forever","-shared","-nopw","-rfbport","5900"])
    PROCS.update({"xvfb":xvfb,"wm":wm,"vnc":vnc})

def _ensure_exec(path):
    try:
        st=os.stat(path)
        if not (st.st_mode & 0o111):
            os.chmod(path, st.st_mode | 0o111)
    except Exception:
        pass

def detect_pe_arch(path):
    try:
        with open(path,"rb") as f:
            mz=f.read(64)
            if mz[:2]!=b'MZ': return None
            f.seek(int.from_bytes(mz[0x3C:0x40], "little"))
            if f.read(4)!=b'PE\x00\x00': return None
            f.read(20)  # COFF
            magic=int.from_bytes(f.read(2),"little")
            return "win64" if magic==0x20B else ("win32" if magic==0x10B else None)
    except Exception:
        return None

def find_adl(base):
    sdk=os.environ.get("AIRSDK_HOME","").strip() or os.path.join(base,"AIRSDK_51.2.2")
    if not os.path.isdir(sdk): return None, False
    b=os.path.join(sdk,"bin")
    mach=platform.machine().lower()
    linux_cands=[]
    if sys.platform.startswith("linux"):
        if "arm" in mach or "aarch64" in mach:
            linux_cands=["adl_linux_arm64","adl"]
        else:
            linux_cands=["adl_linux64","adl","adl64"]
    # prefer native first
    for name in linux_cands:
        p=os.path.join(b,name)
        if os.path.exists(p):
            _ensure_exec(p)
            return p, False  # not wine
    # fallback to Windows launchers with Wine
    for name in ["adl.exe","adl64.exe"]:
        p=os.path.join(b,name)
        if os.path.exists(p):
            return p, True
    # final fallback: generic 'adl'
    p=os.path.join(b,"adl")
    if os.path.exists(p):
        _ensure_exec(p)
        return p, False
    return None, False

def ensure_wine_prefix_for(adl_path, env):
    arch = detect_pe_arch(adl_path) or os.environ.get("WINEARCH") or "win32"
    prefix = "/wine64" if arch=="win64" else "/wine32"
    env["WINEARCH"]=arch
    env["WINEPREFIX"]=os.environ.get("WINEPREFIX", prefix)
    try: subprocess.run(["wineboot","-u"], env=env, timeout=40)
    except Exception: pass
    return arch, env["WINEPREFIX"]

def preflight():
    base=os.path.dirname(os.path.abspath(__file__))
    adl, use_wine = find_adl(base)
    if not adl: return False,"AIRSDK/ADL not found"
    resources=os.path.join(base,"Resources")
    if not os.path.isdir(resources): return False,"Resources folder not found"
    if not os.path.exists(os.path.join(resources,"MovieStarPlanet.swf")): return False,"MovieStarPlanet.swf missing"
    return True,{"adl":adl,"use_wine":use_wine,"resources":resources}

def build_cmd(adl_path, use_wine, appxml, tmpdir):
    screensize=os.environ.get("SCREENSIZE","1280x800:1280x800")
    if use_wine and sys.platform.startswith("linux"):
        return ["wine", adl_path, "-nodebug", "-screensize", screensize, appxml, tmpdir]
    return [adl_path, "-nodebug", "-screensize", screensize, appxml, tmpdir]

def sweep_tmp_later(path):
    def f():
        try: shutil.rmtree(path, ignore_errors=True)
        except: pass
    threading.Timer(60.0,f).start()

def run_swf(country):
    ok,data=preflight()
    if not ok:
        with LOCK: STATE.update({"phase":"error","message":data,"pid":None,"code":1,"tmp":None}); return
    start_x_stack()
    adl=data["adl"]; use_wine=data["use_wine"]; resources=data["resources"]
    tmp=tempfile.mkdtemp(prefix="msp_vnc_")
    try:
        for n in os.listdir(resources):
            s=os.path.join(resources,n); d=os.path.join(tmp,n)
            shutil.copytree(s,d) if os.path.isdir(s) else shutil.copy2(s,d)
        swf="MovieStarPlanet.swf"+(f"?country={country}" if country else "")
        appxml=os.path.join(tmp,"application.xml")
        with open(appxml,"w",encoding="utf-8") as f: f.write(APP_XML.format(content=swf))
        out=os.path.join(tmp,"adl.out"); err=os.path.join(tmp,"adl.err")
        cmd=build_cmd(adl,use_wine,appxml,tmp)

        env=dict(os.environ); env["DISPLAY"]=":99"; env["WINEDEBUG"]="-all"
        if use_wine: ensure_wine_prefix_for(adl, env)

        with open(out,"wb") as so, open(err,"wb") as se:
            p=subprocess.Popen(cmd,cwd=tmp,stdout=so,stderr=se,env=env)

        with LOCK: STATE.update({"phase":"starting","message":("ADL (linux)" if not use_wine else "ADL (wine)")+" starting", "pid":p.pid,"code":None,"tmp":tmp})

        t0=time.time()
        while time.time()-t0<7:
            if p.poll() is None: time.sleep(0.2)
            else: break

        if p.poll() is None:
            with LOCK: STATE.update({"phase":"running","message":"SWF launched (browser stream)","pid":p.pid,"code":None})
            return

        rc=p.returncode
        try:
            with open(err,"r",encoding="utf-8",errors="ignore") as se: em=se.read()[-3000:]
        except Exception:
            em=""
        with LOCK: STATE.update({"phase":"error","message":f"ADL exited {rc}. {em}".strip(),"pid":None,"code":rc})
    except Exception as e:
        with LOCK: STATE.update({"phase":"error","message":str(e),"pid":None,"code":1})
    finally:
        sweep_tmp_later(tmp)

app=FastAPI()
NOVNC_DIR=resolve_novnc_dir()
if NOVNC_DIR:
    app.mount("/novnc", StaticFiles(directory=NOVNC_DIR, html=True), name="novnc")

@app.on_event("startup")
def boot():
    start_x_stack()

@app.get("/", response_class=HTMLResponse)
def index(): return HTML_PAGE

@app.get("/play", response_class=HTMLResponse)
def play():
    if not NOVNC_DIR:
        return HTMLResponse("<!DOCTYPE html><meta charset='utf-8'><body style='margin:0;background:#000;color:#fff;font:14px system-ui;padding:16px'>noVNC not found.</body>")
    u="/novnc/vnc_lite.html?path=ws&autoconnect=true&resize=scale&reconnect=1&quality=6&title=MovieStarPlanet"
    return ("<!DOCTYPE html><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>MovieStarPlanet</title><style>html,body{height:100%;margin:0;background:#000}</style>"
            f"<script>location.href='{u}';</script><a href='{u}' style='color:#8cf'>Open Viewer</a>")

@app.get("/background.jpg")
def bg():
    if os.path.exists("background.jpg"): return FileResponse("background.jpg", media_type="image/jpeg")
    return PlainTextResponse("not found", status_code=404)

@app.get("/status")
def status():
    with LOCK: return JSONResponse(STATE.copy())

@app.get("/logs", response_class=PlainTextResponse)
def logs(type: str = Query("out")):
    with LOCK: tmp=STATE.get("tmp")
    if not tmp: return PlainTextResponse("no run", status_code=404)
    path=os.path.join(tmp, "adl.out" if type!="err" else "adl.err")
    if not os.path.exists(path): return PlainTextResponse("no logs", status_code=404)
    try:
        with open(path, "rb") as f: data=f.read()
        return data.decode(errors="ignore")[-12000:]
    except: return PlainTextResponse("unreadable", status_code=500)

@app.get("/diag", response_class=PlainTextResponse)
def diag():
    base=os.path.dirname(os.path.abspath(__file__))
    adl,use_wine=find_adl(base)
    lines=[
        f"ADL: {adl or 'NOT FOUND'}",
        f"mode: {'wine' if use_wine else 'linux-native'}",
        f"DISPLAY={os.environ.get('DISPLAY','')}",
        f"WINEARCH={os.environ.get('WINEARCH','(auto)')} WINEPREFIX={os.environ.get('WINEPREFIX','(auto)')}",
    ]
    try: lines.append("wine: "+subprocess.check_output(["wine","--version"]).decode().strip())
    except Exception as e: lines.append(f"wine: error ({e})")
    return "\n".join(lines)

@app.get("/test-gui")
def test_gui():
    try:
        subprocess.Popen(["xterm","-geometry","60x10+40+40","-T","Hello from container","-e","bash","-lc","echo it works; sleep 120"],
                         env={"DISPLAY":":99"}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"ok":True,"message":"Launched xterm test window for 2 minutes."}
    except Exception as e:
        return {"ok":False,"message":str(e)}

@app.post("/launch")
def launch(code: str = Query("gb")):
    ok,_=preflight()
    if not ok:
        with LOCK: STATE.update({"phase":"error","message":"AIRSDK or SWF missing","pid":None,"code":1,"tmp":None})
        return JSONResponse({"ok":False,"message":STATE["message"]})
    with LOCK: STATE.update({"phase":"launch","message":"Launching...","pid":None,"code":None})
    threading.Thread(target=run_swf, args=(code,), daemon=True).start()
    return JSONResponse({"ok":True,"message":"Launching..."})

# ---- WebSocket bridge (binary/base64) + aliases ----
@app.websocket("/ws")
async def ws_proxy(ws: WebSocket):
    req=(ws.headers.get("sec-websocket-protocol") or "").replace(" ","").split(",")
    sub="binary" if "binary" in req else ("base64" if "base64" in req else None)
    if sub: await ws.accept(subprotocol=sub)
    else:   await ws.accept()
    use_base64=(sub=="base64")
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1",5900)
    except:
        await ws.close(code=1011); return

    async def ws_to_tcp():
        try:
            while True:
                msg=await ws.receive()
                t=msg.get("type")
                if t=="websocket.receive":
                    if msg.get("bytes") is not None: data=msg["bytes"]
                    else:
                        txt=msg.get("text") or ""
                        data=(base64.b64decode(txt) if use_base64 else txt.encode("latin1","ignore"))
                    if data: writer.write(data); await writer.drain()
                elif t=="websocket.disconnect": break
        finally:
            try: writer.close()
            except: pass

    async def tcp_to_ws():
        try:
            while True:
                data=await reader.read(32768)
                if not data: break
                if use_base64: await ws.send_text(base64.b64encode(data).decode("ascii"))
                else:          await ws.send_bytes(data)
        finally:
            try: await ws.close()
            except: pass

    await asyncio.gather(ws_to_tcp(), tcp_to_ws())

@app.websocket("/websockify")
async def ws_proxy_websockify(ws: WebSocket): await ws_proxy(ws)

@app.websocket("/novnc/ws")
async def ws_proxy_under_novnc(ws: WebSocket): await ws_proxy(ws)

def main():
    port=int(os.environ.get("PORT","8000"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")

if __name__ == "__main__":
    main()
