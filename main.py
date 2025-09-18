import os, sys, shutil, tempfile, subprocess, threading, time
from fastapi import FastAPI, Form, Query
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, FileResponse
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

HTML_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MSP</title><style>html,body{height:100%;margin:0;color:#fff;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Ubuntu,Helvetica,Arial,sans-serif}body{background-image:linear-gradient(rgba(0,0,0,.55),rgba(0,0,0,.55)),url('/background.jpg');background-position:center;background-size:cover;background-attachment:fixed;background-repeat:no-repeat}.wrap{display:flex;align-items:center;justify-content:center;height:100%}.card{background:rgba(255,255,255,.08);backdrop-filter:blur(8px);padding:24px 20px;border-radius:16px;box-shadow:0 10px 30px rgba(0,0,0,.35);width:360px}select,button{appearance:none;background:rgba(0,0,0,.35);color:#fff;border:1px solid rgba(255,255,255,.18);border-radius:12px;padding:12px 16px;font-size:16px;outline:none;width:100%}button{margin-top:10px;cursor:pointer}#status{margin-top:10px;font-size:12px;opacity:.95;white-space:pre-wrap}a{color:#9ddcff;text-decoration:none}</style></head><body><div class="wrap"><div class="card"><h1 style="margin:0 0 12px 0;font-size:18px">Choose country</h1><form id="f"><select name="code">__OPTS__</select><button type="submit">Play MovieStarPlanet</button></form><div id="status"></div><div style="margin-top:8px"><a href="/logs?type=out" target="_blank">stdout</a> · <a href="/logs?type=err" target="_blank">stderr</a></div></div></div><script>const s=document.getElementById("status");let poll=null;document.getElementById("f").addEventListener("submit",async e=>{e.preventDefault();s.textContent="Launching...";if(poll){clearInterval(poll);poll=null};const d=new FormData(e.target);const r=await fetch("/launch",{method:"POST",body:d});const j=await r.json();if(!j.ok){s.textContent=j.message;return};poll=setInterval(async()=>{const rs=await fetch("/status");const js=await rs.json();s.textContent=js.phase.toUpperCase()+": "+js.message;if(js.phase==="running"||js.phase==="error"){clearInterval(poll);poll=null}},700)})</script></body></html>"""

COUNTRIES=[("gb","United Kingdom"),("au","Australia"),("ca","Canada"),("de","Deutschland"),("dk","Danmark"),("es","España"),("fr","France"),("ie","Ireland"),("nl","Nederland"),("nz","New Zealand"),("no","Norge"),("pl","Polska"),("fi","Suomi"),("se","Sverige"),("tr","Türkiye"),("us","United States")]

STATE={"phase":"idle","message":"","pid":None,"code":None,"tmp":None}
LOCK=threading.Lock()

def find_adl(base):
    override=os.environ.get("ADL_PATH","").strip()
    if override and os.path.exists(override):
        return override
    sdk=os.environ.get("AIRSDK_HOME","").strip()
    local=os.path.join(base,"AIRSDK_51.2.2")
    if not sdk and os.path.isdir(local):
        sdk=local
    if not sdk:
        return None
    p_exe=os.path.join(sdk,"bin","adl.exe")
    p_bin=os.path.join(sdk,"bin","adl")
    if os.path.exists(p_exe):
        return p_exe
    if os.path.exists(p_bin):
        if not os.access(p_bin,os.X_OK):
            try: os.chmod(p_bin,0o755)
            except: pass
        return p_bin
    return None

def preflight():
    base=os.path.dirname(os.path.abspath(__file__))
    adl=find_adl(base)
    if not adl:
        return False,"AIRSDK/ADL not found"
    resources=os.path.join(base,"Resources")
    if not os.path.isdir(resources):
        return False,"Resources folder not found"
    if not os.path.exists(os.path.join(resources,"MovieStarPlanet.swf")):
        return False,"MovieStarPlanet.swf missing"
    return True,{"adl":adl,"resources":resources}

def build_cmd(adl, appxml, tmpdir):
    custom=os.environ.get("ADL_CMD","").strip()
    if custom:
        parts=[]
        token=""
        quote=None
        for c in custom:
            if c in ("'",'"'):
                if quote==c:
                    quote=None
                    parts.append(token); token=""
                elif quote is None:
                    quote=c
                else:
                    token+=c
            elif c==" " and quote is None:
                if token: parts.append(token); token=""
            else:
                token+=c
        if token: parts.append(token)
        parts=[s.replace("{adl}",adl).replace("{appxml}",appxml).replace("{tmpdir}",tmpdir) for s in parts]
        parts+=["-nodebug",appxml,tmpdir]
        return parts
    headless=os.environ.get("HEADLESS","1")!="0"
    use_wine=str(adl).lower().endswith(".exe")
    if headless and use_wine and sys.platform.startswith("linux"):
        return ["xvfb-run","-a","-s","-screen 0 1280x800x24","wine",adl,"-nodebug",appxml,tmpdir]
    if headless and not use_wine and sys.platform.startswith("linux"):
        return ["xvfb-run","-a","-s","-screen 0 1280x800x24",adl,"-nodebug",appxml,tmpdir]
    if use_wine and sys.platform.startswith("linux"):
        return ["wine",adl,"-nodebug",appxml,tmpdir]
    return [adl,"-nodebug",appxml,tmpdir]

def sweep_tmp_later(path):
    def f():
        try: shutil.rmtree(path, ignore_errors=True)
        except: pass
    threading.Timer(30.0,f).start()

def run_swf(country):
    ok,data=preflight()
    if not ok:
        with LOCK: STATE.update({"phase":"error","message":data,"pid":None,"code":1,"tmp":None})
        return
    adl=data["adl"]; resources=data["resources"]
    tmp=tempfile.mkdtemp(prefix="msp_headless_")
    try:
        for name in os.listdir(resources):
            src=os.path.join(resources,name)
            dst=os.path.join(tmp,name)
            if os.path.isdir(src): shutil.copytree(src,dst)
            else: shutil.copy2(src,dst)
        swf="MovieStarPlanet.swf"+(f"?country={country}" if country else "")
        appxml=os.path.join(tmp,"application.xml")
        with open(appxml,"w",encoding="utf-8") as f: f.write(APP_XML.format(content=swf))
        out=os.path.join(tmp,"adl.out"); err=os.path.join(tmp,"adl.err")
        cmd=build_cmd(adl,appxml,tmp)
        with open(out,"wb") as so, open(err,"wb") as se:
            p=subprocess.Popen(cmd,cwd=tmp,stdout=so,stderr=se)
        with LOCK: STATE.update({"phase":"starting","message":"ADL starting","pid":p.pid,"code":None,"tmp":tmp})
        t0=time.time()
        while time.time()-t0<3:
            if p.poll() is None:
                with LOCK: STATE.update({"phase":"running","message":"SWF launched (headless)","pid":p.pid,"code":None})
                return
            time.sleep(0.1)
        rc=p.poll()
        if rc is None:
            with LOCK: STATE.update({"phase":"running","message":"SWF launched (headless)","pid":p.pid,"code":None})
            return
        try:
            with open(err,"rb") as se: em=se.read()[:2048].decode(errors="ignore")
        except:
            em=""
        with LOCK: STATE.update({"phase":"error","message":f"ADL exited {rc}. {em.strip()}","pid":None,"code":rc})
    except Exception as e:
        with LOCK: STATE.update({"phase":"error","message":str(e),"pid":None,"code":1})
    finally:
        sweep_tmp_later(tmp)

app=FastAPI()

@app.get("/",response_class=HTMLResponse)
def index():
    opts="".join([f'<option value="{c}">{n}</option>' for c,n in COUNTRIES])
    html=HTML_PAGE.replace("__OPTS__",opts)
    return HTMLResponse(html, media_type="text/html")

@app.get("/background.jpg")
def bg():
    if os.path.exists("background.jpg"):
        return FileResponse("background.jpg", media_type="image/jpeg")
    return PlainTextResponse("not found",status_code=404)

@app.get("/status")
def status():
    with LOCK:
        return JSONResponse(STATE.copy())

@app.get("/logs",response_class=PlainTextResponse)
def logs(type: str = Query("out")):
    with LOCK:
        tmp=STATE.get("tmp")
    if not tmp:
        return PlainTextResponse("no run",status_code=404)
    path=os.path.join(tmp,"adl.out" if type!="err" else "adl.err")
    if not os.path.exists(path):
        return PlainTextResponse("no logs",status_code=404)
    try:
        with open(path,"rb") as f: data=f.read()
        return data.decode(errors="ignore")[-10000:]
    except:
        return PlainTextResponse("unreadable",status_code=500)

@app.post("/launch")
def launch(code: str = Form("")):
    ok,_=preflight()
    if not ok:
        with LOCK: STATE.update({"phase":"error","message":"AIRSDK or SWF missing","pid":None,"code":1,"tmp":None})
        return JSONResponse({"ok":False,"message":STATE["message"]})
    with LOCK: STATE.update({"phase":"launch","message":"Launching...","pid":None,"code":None})
    threading.Thread(target=run_swf,args=(code,),daemon=True).start()
    return JSONResponse({"ok":True,"message":"Launching..."})

def main():
    port=int(os.environ.get("PORT","8000"))
    uvicorn.run(app,host="0.0.0.0",port=port,log_level="warning")

if __name__=="__main__":
    main()
