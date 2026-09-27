"""Bounded, direction-aware geometry matching; no network or receiver dependencies."""
import math
from collections import defaultdict

def length(points):return sum(math.dist(a,b) for a,b in zip(points,points[1:]))
def resample(points,count=128):
 if len(points)<2:return points[:]
 distances=[0.]
 for a,b in zip(points,points[1:]):distances.append(distances[-1]+math.dist(a,b))
 if distances[-1]<=0:return points[:1]
 result=[];j=1
 for i in range(count):
  target=distances[-1]*i/(count-1)
  while j<len(points)-1 and distances[j]<target:j+=1
  span=distances[j]-distances[j-1];t=(target-distances[j-1])/span if span else 0
  result.append([points[j-1][k]+t*(points[j][k]-points[j-1][k]) for k in (0,1)])
 return result

class Fingerprint:
 def __init__(self,points):
  self.points=points;self.length=length(points);self.closed=len(points)>=20 and self.length>=100 and math.dist(points[0],points[-1])<=75
  self.grid=defaultdict(list);self.segments=[];offset=0
  for a,b in zip(points,points[1:]+[points[0]]):
   size=math.dist(a,b)
   if size>200:self.closed=False;continue
   if size<.01:continue
   index=len(self.segments);self.segments.append((a,b,size,offset));offset+=size
   for x in range(math.floor(min(a[0],b[0])/50),math.floor(max(a[0],b[0])/50)+1):
    for y in range(math.floor(min(a[1],b[1])/50),math.floor(max(a[1],b[1])/50)+1):self.grid[x,y].append(index)
  self.total=offset
 def nearest(self,p):
  cell=(math.floor(p[0]/50),math.floor(p[1]/50));indices=set()
  for dx in (-1,0,1):
   for dy in (-1,0,1):indices.update(self.grid.get((cell[0]+dx,cell[1]+dy),()))
  best=None
  for index in indices:
   a,b,size,offset=self.segments[index];t=max(0,min(1,sum((p[k]-a[k])*(b[k]-a[k]) for k in (0,1))/size**2));distance=math.hypot(p[0]-a[0]-t*(b[0]-a[0]),p[1]-a[1]-t*(b[1]-a[1]))
   if best is None or distance<best[0]:best=(distance,(offset+t*size)/max(self.total,1),(b[0]-a[0])/size,(b[1]-a[1])/size)
  return best
 def match(self,points,complete=False):
  if not self.closed or len(points)<12:return None
  probe=resample(points,96);errors=[];directions=[];progress=[]
  for i,p in enumerate(probe):
   hit=self.nearest(p)
   if hit is None or hit[0]>45:return None
   errors.append(hit[0]);progress.append(hit[1])
   if i:
    dx=p[0]-probe[i-1][0];dy=p[1]-probe[i-1][1];d=math.hypot(dx,dy)
    if d>1:directions.append((dx*hit[2]+dy*hit[3])/d)
  if not directions or sum(v>.3 for v in directions)/len(directions)<.85:return None
  # Ordered progress rejects loops, skipped branches and backwards travel.
  steps=[(b-a+.5)%1-.5 for a,b in zip(progress,progress[1:])]
  if any(delta<-.015 or delta>.08 for delta in steps):return None
  mean=sum(errors)/len(errors)
  if mean>15:return None
  coverage=min(1,length(points)/max(self.length,1))
  if complete:
   if abs(length(points)-self.length)/self.length>.06:return None
   reverse=Fingerprint(points)
   for p in resample(self.points,128):
    hit=reverse.nearest(p)
    if hit is None or hit[0]>35:return None
  return {'mean_error_m':round(mean,2),'max_error_m':round(max(errors),2),'coverage':round(coverage,3),'direction_agreement':round(sum(v>.3 for v in directions)/len(directions),3),'complete_lap':complete}

def shape_fit(reference,world):
 """Fit rotation, translation and one uniform scale, never reflection or warping."""
 a=resample(reference,96);b=resample(world,96)
 if len(a)!=96 or len(b)!=96:return None
 ca=[sum(p[k] for p in a[:95])/95 for k in (0,1)];cb=[sum(p[k] for p in b[:95])/95 for k in (0,1)]
 aa=[[p[k]-ca[k] for k in (0,1)] for p in a];bb=[[p[k]-cb[k] for k in (0,1)] for p in b];den=sum(x*x+y*y for x,y in aa)
 if den<1e-8:return None
 best=None
 # Cyclic shift accommodates unknown image start/finish. No reversed ordering.
 for shift in range(95):
  paired=[bb[(i+shift)%95] for i in range(95)];src=aa[:95];den=sum(x*x+y*y for x,y in src)
  u=sum(x*p[0]+y*p[1] for (x,y),p in zip(src,paired))/den;v=sum(x*p[1]-y*p[0] for (x,y),p in zip(src,paired))/den
  error=math.sqrt(sum((u*x-v*y-p[0])**2+(v*x+u*y-p[1])**2 for (x,y),p in zip(src,paired))/95)
  if best is None or error<best['error_m']:best={'error_m':error,'a':u,'b':v,'tx':cb[0]-u*ca[0]+v*ca[1],'ty':cb[1]-v*ca[0]-u*ca[1]}
 if best is None:return None
 best['relative_error']=best['error_m']/max(length(world),1);best['reflected']=False;best['transform']='uniform scale + rotation + translation'
 return best

def transform(points,fit):return [[fit['a']*x-fit['b']*y+fit['tx'],fit['b']*x+fit['a']*y+fit['ty']] for x,y in points]
