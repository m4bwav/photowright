import subprocess,time,json,re,sys
PHW="D:/m4bwa/Claude/Projects/Ai/photowright-s50/scripts/phw.py"; LT="D:/m4bwa/Claude/Projects/Ai/photowright-lab/lineart-venv/Scripts/lineart-trace.exe"
for f in ["scan"]:
    for t,cmd in [("own",["python",PHW,"trace",f+".png","-o",f+".own.svg","--kind","centreline"]),("ltdn",[LT,f+".png","--svg","-q","--denoise","-o",f+".ltdn.svg"])]:
        a=time.time(); subprocess.run(cmd,capture_output=True); dt=time.time()-a
        s=open(f"{f}.{t}.svg").read()
        v=json.loads(subprocess.run(["python",PHW,"--json","vcheck",f"{f}.{t}.svg","--source",f+".png","--kind","centreline"],capture_output=True,text=True).stdout)
        print(f,t,f"{dt:.2f}s bytes={len(s)} nodes={v['counts']['nodes']} sub={v['counts']['subpaths']} overlap={v['overlap']} pass={v['pass']} fails={v['fails']}")
