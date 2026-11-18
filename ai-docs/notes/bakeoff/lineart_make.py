from PIL import Image, ImageDraw
import math
def save(name, fn, w=4):
    im=Image.new("L",(1600,1200),255); d=ImageDraw.Draw(im); fn(d,w)
    im.resize((400,300),Image.LANCZOS).save(name)
def spiral(d,w):
    pts=[(800+30*t*math.cos(t),600+30*t*math.sin(t)) for t in [i/20 for i in range(400)]]
    d.line(pts,fill=0,width=w*4,joint="curve")
def sketch(d,w):
    d.line([(100,1000),(400,200),(700,1000)],fill=0,width=w*4,joint="curve")
    d.line([(250,600),(550,600)],fill=0,width=w*4)
    d.ellipse([900,300,1400,900],outline=0,width=w*4)
    d.arc([850,200,1500,1100],200,340,fill=0,width=w*4)
    pts=[(100+i*7,150+60*math.sin(i/12)) for i in range(200)]; d.line(pts,fill=0,width=w*3,joint="curve")
def grid(d,w):
    for x in range(200,1500,260): d.line([(x,100),(x,1100)],fill=0,width=w*4)
    for y in range(150,1100,240): d.line([(100,y),(1500,y)],fill=0,width=w*4)
save("spiral.png",spiral); save("sketch.png",sketch); save("grid.png",grid)
