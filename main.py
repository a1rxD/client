import os, sys, shutil, tempfile, subprocess, threading, socket, time
from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn, webview

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

COUNTRIES=[("au","Australia"),("ca","Canada"),("de","Deutschland"),("dk","Danmark"),("es","España"),("fr","France"),("ie","Ireland"),("nl","Nederland"),("nz","New Zealand"),("no","Norge"),("pl","Polska"),("fi","Suomi"),("se","Sverige"),("tr","Türkiye"),("uk","UK"),("us","USA")]

STATE={"phase":"idle","message":"","pid":None,"code":None}

def find_adl(base):
    local=os.path.join(base,"AIRSDK_51.2.2")
    env=os.environ.get("AIRSDK_HOME","")
    sdk=local if os.path.isdir(local) else env
    if not sdk:
        print("find_adl: no AIRSDK found", flush=True)
        return None
    p=os.path.join(sdk,"bin","adl.exe" if sys.platform.startswith("win") else "adl")
    if os.path.exists(p) and not os.access(p,os.X_OK):
        try:
            os.chmod(p,0o755)
            print(f"find_adl: chmod +x {p}", flush=True)
        except:
            pass
    if os.path.exists(p):
        print(f"find_adl: using {p}", flush=True)
        return p
    print(f"find_adl: adl not in {sdk}", flush=True)
    return None

def preflight():
    base=os.path.dirname(os.path.abspath(__file__))
    adl=find_adl(base)
    if not adl:
        print("preflight: AIRSDK missing", flush=True)
        return False,"AIRSDK not found. Set AIRSDK_HOME or place AIRSDK_51.2.2 next to this file."
    resources=os.path.join(base,"Resources")
    print(f"preflight: resources at {resources}", flush=True)
    if not os.path.isdir(resources):
        print("preflight: resources folder missing", flush=True)
        return False,"Resources folder not found."
    swf=os.path.join(resources,"MovieStarPlanet.swf")
    if not os.path.exists(swf):
        print(f"preflight: missing {swf}", flush=True)
        return False,"MovieStarPlanet.swf not found in Resources."
    print(f"preflight: swf ok {swf}", flush=True)
    return True,{"adl":adl,"resources":resources}

def run_swf(country):
    print(f"run_swf: start country={country}", flush=True)
    ok,data=preflight()
    if not ok:
        STATE.update({"phase":"error","message":data,"pid":None,"code":1})
        print(f"run_swf: abort {data}", flush=True)
        return
    adl=data["adl"]; resources=data["resources"]
    tmp=tempfile.mkdtemp(prefix="msp_webview_")
    print(f"run_swf: temp {tmp}", flush=True)
    try:
        for name in os.listdir(resources):
            src=os.path.join(resources,name)
            dst=os.path.join(tmp,name)
            if os.path.isdir(src): shutil.copytree(src,dst)
            else: shutil.copy2(src,dst)
        print("run_swf: resources copied", flush=True)
        swf="MovieStarPlanet.swf"+(f"?country={country}" if country else "")
        appxml=os.path.join(tmp,"application.xml")
        with open(appxml,"w",encoding="utf-8") as f:
            f.write(APP_XML.format(content=swf))
        print(f"run_swf: wrote {appxml} with content={swf}", flush=True)
        out=os.path.join(tmp,"adl.out")
        err=os.path.join(tmp,"adl.err")
        args=[adl,"-nodebug",appxml,tmp]
        print(f"run_swf: exec {' '.join(args)}", flush=True)
        with open(out,"wb") as so, open(err,"wb") as se:
            p=subprocess.Popen(args,cwd=tmp,stdout=so,stderr=se)
        STATE.update({"phase":"starting","message":"ADL starting","pid":p.pid,"code":None})
        print(f"run_swf: pid {p.pid}", flush=True)
        t0=time.time()
        while time.time()-t0<3:
            rc=p.poll()
            if rc is None:
                STATE.update({"phase":"running","message":"SWF launched","pid":p.pid,"code":None})
                print("run_swf: running", flush=True)
                return
            time.sleep(0.1)
        rc=p.poll()
        if rc is None:
            STATE.update({"phase":"running","message":"SWF launched","pid":p.pid,"code":None})
            print("run_swf: running (delayed)", flush=True)
            return
        try:
            with open(err,"rb") as se: em=se.read()[:2048].decode(errors="ignore")
        except:
            em=""
        STATE.update({"phase":"error","message":f"ADL exited {rc}. {em.strip()}","pid":None,"code":rc})
        print(f"run_swf: exit {rc} err={em.strip()}", flush=True)
    except Exception as e:
        STATE.update({"phase":"error","message":str(e),"pid":None,"code":1})
        print(f"run_swf: exception {e}", flush=True)
    finally:
        print(f"run_swf: scheduling cleanup for {tmp}", flush=True)
        threading.Timer(20.0, lambda: shutil.rmtree(tmp, ignore_errors=True)).start()

def pick_port():
    s=socket.socket()
    s.bind(("127.0.0.1",0))
    p=s.getsockname()[1]
    s.close()
    print(f"pick_port: {p}", flush=True)
    return p

app=FastAPI()

@app.get("/",response_class=HTMLResponse)
def index():
    opts="".join([f'<option value="{c}">{n}</option>' for c,n in COUNTRIES])
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MSP</title><style>html,body{{height:100%;margin:0;background:#0b1020;color:#fff;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Ubuntu,Helvetica,Arial,sans-serif}}.wrap{{display:flex;align-items:center;justify-content:center;height:100%}}.card{{background:rgba(255,255,255,.06);backdrop-filter:blur(8px);padding:24px 20px;border-radius:16px;box-shadow:0 10px 30px rgba(0,0,0,.25);width:340px}}select,button{{appearance:none;background:rgba(0,0,0,.35);color:#fff;border:1px solid rgba(255,255,255,.15);border-radius:12px;padding:12px 16px;font-size:16px;outline:none;width:100%}}button{{margin-top:10px;cursor:pointer}}#status{{margin-top:10px;font-size:12px;opacity:.9;white-space:pre-wrap}}</style></head><body><div class="wrap"><div class="card"><h1 style="margin:0 0 12px 0;font-size:18px">Choose country</h1><form id="f"><select name="code">{opts}</select><button type="submit">Launch SWF</button></form><div id="status"></div></div></div><script>const s=document.getElementById("status");let poll=null;document.getElementById("f").addEventListener("submit",async e=>{{e.preventDefault();s.textContent="Launching...";if(poll){{clearInterval(poll);poll=null}};const d=new FormData(e.target);const r=await fetch("/launch",{{method:"POST",body:d}});const j=await r.json();if(!j.ok){{s.textContent=j.message;return}};poll=setInterval(async()=>{{const rs=await fetch("/status");const js=await rs.json();s.textContent=js.phase.toUpperCase()+": "+js.message;if(js.phase==="running"||js.phase==="error"){{clearInterval(poll);poll=null}}}},500)}}</script></body></html>"""

@app.get("/status")
def status():
    return JSONResponse(STATE)

@app.post("/launch")
def launch(code: str = Form("")):
    print(f"/launch: requested country={code}", flush=True)
    ok,_=preflight()
    if not ok:
        STATE.update({"phase":"error","message":"AIRSDK or SWF missing","pid":None,"code":1})
        print("/launch: preflight failed", flush=True)
        return JSONResponse({"ok":False,"message":STATE["message"]})
    STATE.update({"phase":"launch","message":"Launching...","pid":None,"code":None})
    t=threading.Thread(target=run_swf,args=(code,),daemon=True)
    t.start()
    print("/launch: thread started", flush=True)
    return JSONResponse({"ok":True,"message":"Launching..."})

def run():
    port=pick_port()
    print(f"run: uvicorn on 127.0.0.1:{port}", flush=True)
    cfg=uvicorn.Config(app,host="127.0.0.1",port=port,log_level="warning")
    srv=uvicorn.Server(cfg)
    t=threading.Thread(target=srv.run,daemon=True)
    t.start()
    print("run: opening webview", flush=True)
    webview.create_window("MovieStarPlanet",f"http://127.0.0.1:{port}/",width=1200,height=760)
    webview.start()
    print("run: webview closed", flush=True)

if __name__=="__main__":
    run()
