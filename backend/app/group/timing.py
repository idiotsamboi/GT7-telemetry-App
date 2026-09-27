import math,hashlib,json

def validate_map(points):
 if not isinstance(points,list) or not 20<=len(points)<=4096:raise ValueError('Map needs 20–4096 points')
 if any(not isinstance(p,list) or len(p)!=2 or any(not isinstance(x,(int,float)) or not math.isfinite(x) for x in p) for p in points):raise ValueError('Invalid map positions')
 if math.dist(points[0],points[-1])>75 or any(math.dist(a,b)>200 for a,b in zip(points,points[1:])):raise ValueError('Map must be a continuous closed lap')
 return points
class Projection:
 def __init__(self,points):
  self.points=validate_map(points);self.segments=[];length=0
  for a,b in zip(points,points[1:]+[points[0]]):
   distance=math.dist(a,b)
   if distance>.01:self.segments.append((a,b,length,distance));length+=distance
  if length<100:raise ValueError('Map too short')
  self.length=length;self.revision=hashlib.sha256(json.dumps(points).encode()).hexdigest()[:16]
 def project(self,position,previous=None):
  if not position or any(v is None for v in position):return None
  p=[position[0],position[2]];matches=[]
  for a,b,start,length in self.segments:
   t=max(0,min(1,((p[0]-a[0])*(b[0]-a[0])+(p[1]-a[1])*(b[1]-a[1]))/length**2))
   d=math.dist(p,[a[0]+t*(b[0]-a[0]),a[1]+t*(b[1]-a[1])]);progress=(start+t*length)/self.length
   if d<=25:matches.append((d,progress))
  if not matches:return None
  matches.sort();best=matches[0]
  if any(.05<abs(p-best[1])<.95 and d<best[0]+3 for d,p in matches[1:]):return None
  if previous is not None and abs((best[1]-previous+.5)%1-.5)*self.length>150:return None
  return best[1]%1

def in_zone(progress,zone):
 if progress is None:return None
 a,b=zone['start'],zone['end'];return a<=progress<b if a<b else progress>=a or progress<b
FLAG_ORDER={'red':0,'black':1,'mechanical':2,'double_yellow':3,'yellow':4,'safety_car':5,'fcy':5,'vsc':5,'checkered':6,'blue':7,'white':8,'warning':9,'green':10}
def applicable_flags(instructions,entry_id,progress,zones,now):
 result=[]
 for item in instructions:
  if item['cancelled'] or item.get('expires') is not None and item['expires']<=now:continue
  applies=True
  if item['scope']=='entry':applies=item['target']==entry_id
  elif item['scope']=='zone':
   zone=next((z for z in zones if z['id']==item['target']),None);applies=in_zone(progress,zone) if zone else False
  if applies is not False:result.append({**item,'applicability':'uncertain' if applies is None else 'applies'})
 if any(i['flag']!='green' for i in result):result=[i for i in result if i['flag']!='green']
 return sorted(result,key=lambda i:(FLAG_ORDER[i['flag']],-i['version']))
