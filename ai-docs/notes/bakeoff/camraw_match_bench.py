"""Bench for camraw --match (0.27.0): half-image same-scene trials (fit vs Reinhard dE76 to the truth) and
different-scene pairs (residual and histogram overlap after the fit). Usage: python camraw_match_bench.py IMG..."""
import sys, time, glob, numpy as np
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[3] / "scripts"))
import phw
from phw import core, rawio, tonal
from phw.masks import rgb_to_lab
files = sys.argv[1:]
def loadsmall(f, side=320):
    return rawio.small_copy(core.load(f), side)
def grade(img, g): return rawio._render({n:0.0 for n in rawio.SLIDERS}, g, img, core.Used())
def de(a,b): return float(np.mean(np.linalg.norm(rgb_to_lab(np.clip(a,0,1))-rgb_to_lab(np.clip(b,0,1)),axis=-1)))
rng=np.random.default_rng(3); rows=[]; T=0
imgs=[loadsmall(f) for f in files]
for t in range(2*len(imgs)):
    im=imgs[t%len(imgs)]; c=im.color(); w=c.shape[1]//2
    L,R=(c[:,:w],c[:,w:]) if t%2==0 else (c[:,w:],c[:,:w])
    G={"temp":rng.uniform(-60,60),"tint":rng.uniform(-40,40),"exposure":rng.uniform(-.7,.7),"contrast":rng.uniform(-30,40),
       "whites":rng.uniform(-40,40),"blacks":rng.uniform(-40,40),"vibrance":rng.uniform(-40,50),"saturation":rng.uniform(-40,40)}
    Li=im.copy(px=np.ascontiguousarray(L)); Ri=im.copy(px=np.ascontiguousarray(R))
    ref=grade(Li,G); truth=grade(Ri,G)
    refI=im.copy(px=np.ascontiguousarray(ref.astype(np.float32)))
    t0=time.time()
    vals,loss,ev=rawio.fit_sliders(rawio.small_copy(Ri,160), rawio.small_copy(refI,160), list(rawio.FIT_DEFAULT), {n:0.0 for n in rawio.SLIDERS if n not in rawio.FIT_DEFAULT})
    T+=time.time()-t0
    vals={n:(round(v,2) if n=="exposure" else round(v,1)) for n,v in vals.items()}
    out=grade(Ri,vals)
    m,s=tonal.stats_lab(ref)
    rh=tonal.op_match(Ri,{"mean":m,"std":s},core.Used()).color()
    sm=rawio.small_copy(Ri,160).color(); osm=grade(rawio.small_copy(Ri,160),vals); rsm=rawio.small_copy(refI,160).color()
    rms=float(np.sqrt(np.mean((rawio.lab_signature(osm)-rawio.lab_signature(rsm))**2)))
    ov=rawio.hist_overlap(osm,rsm)
    rows.append((de(R,truth),de(rh,truth),de(out,truth)))
    print(t, "none %.2f reinhard %.2f fit %.2f"%rows[-1], "evals",ev, "rms %.2f ovL %.2f ovab %.2f"%(rms,*ov))
r=np.array(rows); print("MEAN", r.mean(0).round(2), "MEDIAN", np.median(r,0).round(2), "wins", int((r[:,2]<r[:,1]).sum()),"/",len(r), "s/fit %.2f"%(T/len(r)))
# different scenes
print("--- different scenes")
for i in range(len(imgs)):
    j=(i+1)%len(imgs)
    a=rawio.small_copy(imgs[i],160); b=rawio.small_copy(imgs[j],160)
    vals,loss,ev=rawio.fit_sliders(a,b,list(rawio.FIT_DEFAULT),{n:0.0 for n in rawio.SLIDERS if n not in rawio.FIT_DEFAULT})
    o=grade(a,vals); rms=float(np.sqrt(np.mean((rawio.lab_signature(o)-rawio.lab_signature(b.color()))**2)))
    print(i,j,"rms %.2f ovL %.2f ovab %.2f"%(rms,*rawio.hist_overlap(o,b.color())))
