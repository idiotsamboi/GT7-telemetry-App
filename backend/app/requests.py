"""The offline engineer's 100-request catalogue and three factual response forms."""
import math,time
from .telemetry.units import spoken_measure

CATALOG={}
def legacy(key,phrase,category,forms):
    CATALOG[key]={'id':key,'request':phrase,'category':category,'answers':forms,'kind':'action'}

legacy('radio','radio check','Radio',['Radio check. Engineer is ready.','Engineer online. Ready for your request.','Radio check received. Standing by.'])
legacy('status','status','Race',['{answer}','Current race update: {answer}','Here is your status. {answer}'])
legacy('fuel','how much fuel','Fuel',['{answer}','Fuel remaining: {answer}','Tank update. {answer}'])
legacy('finish','can i finish','Fuel',['{answer}','Finish projection. {answer}','Based on measured consumption: {answer}'])
legacy('save','how much do i need to save','Fuel',['{answer}','Fuel-saving calculation. {answer}','Here is the saving requirement. {answer}'])
legacy('pit','when should i pit','Strategy',['{answer}','Pit planning update. {answer}','For your next stop: {answer}'])
legacy('box','box this lap','Controls',['{answer}','Copy. {answer}','Pit intent confirmed. {answer}'])
legacy('last','last lap','Timing',['{answer}','Your previous lap: {answer}','Last-lap timing. {answer}'])
legacy('best','best lap','Timing',['{answer}','Personal-best timing. {answer}','Your best recorded time: {answer}'])
legacy('delta','delta to reference','Timing',['{answer}','Reference comparison. {answer}','Your estimated delta: {answer}'])
legacy('loss','where am i losing time','Analysis',['{answer}','Evidence review. {answer}','Here is what the recorded laps show. {answer}'])
legacy('tyres','how are the tyres','Tyres',['{answer}','Tyre temperature update. {answer}','Surface-temperature report. {answer}'])
legacy('lap_summary','what happened that lap','Analysis',['{answer}','Lap review. {answer}','Looking back at the recorded lap: {answer}'])
legacy('compare','compare with my best','Analysis',['{answer}','Comparison evidence. {answer}','Against your recorded performance: {answer}'])
legacy('reference','use the last lap as reference','Controls',['{answer}','Reference selection. {answer}','Comparison setup: {answer}'])
legacy('corner','mark this corner','Controls',['{answer}','Corner annotation: {answer}','Corner marker. {answer}'])
legacy('incident','mark that incident','Controls',['{answer}','Incident annotation: {answer}','Incident marker. {answer}'])
legacy('show_live','show live','Navigation',['{answer}','Opening the live dashboard.','Live race display selected.'])
legacy('show_analysis','show analysis','Navigation',['{answer}','Opening the analysis view.','Analysis display selected.'])
legacy('show_strategy','show strategy','Navigation',['{answer}','Opening the strategy view.','Strategy display selected.'])
legacy('repeat','repeat','Radio',['{answer}','Repeating: {answer}','Again: {answer}'])
legacy('less','speak less','Radio',['{answer}','Quiet mode selected.','Reducing optional radio messages.'])
legacy('more','speak more','Radio',['{answer}','Detailed mode selected.','Increasing radio detail.'])
legacy('quiet','quiet for two minutes','Radio',['{answer}','Two minutes of quiet; critical warnings remain active.','Reducing chatter for two minutes. Critical alerts stay on.'])
legacy('mute','mute','Radio',['Engineer muted.','All spoken output muted.','Hard mute is on.'])
legacy('stop','stop talking','Radio',['Stopped.','Speech stopped.','Current speech cancelled.'])
legacy('resume','resume engineer','Radio',['Engineer resumed. Spoken output is enabled.','Radio output enabled. Engineer standing by.','Back on the radio. Normal mode and speech are enabled.'])
legacy('end','end session','Controls',['{answer}','Recording ended. Your report is ready.','Session closed. Opening the report.'])

# id | exact spoken request | category | label | value path | unit | scale
METRICS='''speed|what is my speed|Car|speed|v.speed_kmh|kilometres per hour|1
rpm|what are my revs|Car|engine speed|v.rpm|revolutions per minute|1
gear|what gear am i in|Car|gear|v.gear||1
throttle|how much throttle|Inputs|throttle input|v.throttle|percent|100
brake|how much brake|Inputs|brake input|v.brake|percent|100
clutch|how much clutch|Inputs|clutch input|v.clutch|percent|100
capacity|what is my tank capacity|Fuel|reported tank capacity|v.fuel_capacity|litres|1
fuel_percent|what percent fuel remains|Fuel|fuel level|calc.fuel_percent|percent|1
lap_number|what lap am i on|Timing|current lap|v.lap||1
total_laps|what is the game lap count|Timing|game-reported total laps|v.total_laps||1
suggested_gear|what gear does the game suggest|Car|game-suggested gear|v.suggested_gear||1
rpm_limit|what is my shift ceiling|Car|reported upper RPM indicator|v.rpm_max|revolutions per minute|1
tyre_wear|how much tyre wear|Unavailable|tyre wear|unavailable.wear||1
tyre_pressure|what are my tyre pressures|Unavailable|tyre pressures|unavailable.pressure||1
race_position|what is my race position|Unavailable|live race position|unavailable.position||1
gap_ahead|what is the gap ahead|Unavailable|opponent gap|unavailable.gap||1
sector_times|what are my sector times|Unavailable|sector times|unavailable.sectors||1
race_flags|what flags are out|Unavailable|race-control flags|unavailable.flags||1
steering|what is my steering angle|Car|raw upstream steering rotation|v.steering_rotation|radians, interpretation unverified|1
steering_rate|how fast am i steering|Car|raw upstream steering velocity|v.steering_velocity|radians per second, interpretation unverified|1
tyre_fl|front left tyre temperature|Tyres|front-left surface temperature|v.tyres.0|degrees Celsius|1
tyre_fr|front right tyre temperature|Tyres|front-right surface temperature|v.tyres.1|degrees Celsius|1
tyre_rl|rear left tyre temperature|Tyres|rear-left surface temperature|v.tyres.2|degrees Celsius|1
tyre_rr|rear right tyre temperature|Tyres|rear-right surface temperature|v.tyres.3|degrees Celsius|1
tyre_front|average front tyre temperature|Tyres|average front surface temperature|calc.tyre_front|degrees Celsius|1
tyre_rear|average rear tyre temperature|Tyres|average rear surface temperature|calc.tyre_rear|degrees Celsius|1
tyre_spread|what is my tyre temperature spread|Tyres|surface temperature spread|analysis.tyre_spread_c|degrees Celsius|1
wheel_fl|front left wheel speed|Car|front-left calculated wheel speed|v.wheel_speed_kmh.0|kilometres per hour|1
wheel_fr|front right wheel speed|Car|front-right calculated wheel speed|v.wheel_speed_kmh.1|kilometres per hour|1
wheel_rl|rear left wheel speed|Car|rear-left calculated wheel speed|v.wheel_speed_kmh.2|kilometres per hour|1
wheel_rr|rear right wheel speed|Car|rear-right calculated wheel speed|v.wheel_speed_kmh.3|kilometres per hour|1
susp_fl|front left suspension height|Car|front-left suspension reading|v.suspension.0|millimetres|1000
susp_fr|front right suspension height|Car|front-right suspension reading|v.suspension.1|millimetres|1000
susp_rl|rear left suspension height|Car|rear-left suspension reading|v.suspension.2|millimetres|1000
susp_rr|rear right suspension height|Car|rear-right suspension reading|v.suspension.3|millimetres|1000
car_name|what car am i driving|Car|car identity|car.name||1
track_name|what track is configured|Setup|user-configured track|settings.track||1
layout|what layout is configured|Setup|user-configured layout|settings.layout||1
direction|what direction is configured|Setup|user-configured direction|settings.direction||1
source|what telemetry source is active|System|active data source|runtime.source||1
packet_type|what packet type is arriving|System|received packet type|sample.variant||1
fuel_burn|what is my fuel consumption|Fuel|measured fuel use per clean lap|fuel.litres_per_lap|litres|1
fuel_range|how many laps of fuel remain|Fuel|estimated range including reserve|fuel.laps_remaining|laps|1
fuel_margin|what is my finish fuel margin|Fuel|estimated finish fuel margin|fuel.margin_l|litres|1
refuel|how much should i refuel|Fuel|estimated refuel requirement|fuel.refuel_l|litres|1
fuel_uncertainty|how uncertain is the fuel estimate|Fuel|consumption-spread uncertainty|fuel.uncertainty_l|litres, not a guarantee|1
reserve|what is my fuel reserve|Setup|configured fuel reserve|settings.reserve_l|litres|1
race_distance|what race distance is configured|Setup|configured race distance|settings.race_laps|laps|1
race_duration|what race duration is configured|Setup|configured race duration|settings.race_minutes|minutes|1
target_lap|what is my target lap|Setup|configured target lap|settings.target_ms|seconds|0.001
pit_limit|what is my pit speed limit|Setup|user-configured pit speed limit|settings.pit_limit_kmh|kilometres per hour|1
average_lap|what is my average lap|Timing|average comparable lap|report.pace.mean_ms|seconds|0.001
median_lap|what is my median lap|Timing|median comparable lap|report.pace.median_ms|seconds|0.001
consistency|how consistent are my laps|Timing|lap-time standard deviation|report.pace.std_ms|seconds|0.001
clean_laps|how many comparable laps|Timing|comparable lap count|report.pace.count||1
completed_laps|how many laps have i completed|Timing|recorded complete lap count|calc.completed_laps||1
acceleration|what is my acceleration|Analysis|speed-derived longitudinal acceleration|analysis.longitudinal_g|g|1
coasting|how much am i coasting|Analysis|coasting in the trailing analysis window|analysis.coast_percent|percent|1
overlap|how much pedal overlap|Analysis|pedal overlap in the trailing analysis window|analysis.overlap_percent|percent|1
last_braking|how long was my last braking event|Analysis|last recorded braking duration|analysis.braking_episodes.0.duration_s|seconds|1
reference_time|what is my reference lap time|Timing|live alignment reference duration|delta.reference_s|seconds, estimated|1
delta_trend|am i gaining or losing time|Timing|reference delta trend|calc.delta_trend||1
receive_rate|what is the telemetry rate|System|receive rate|health.rate_hz|packets per second|1
packet_loss|how many packets are missing|System|sequence gaps since source reset|network.gaps|packets|1
parser_errors|how many decoding errors|System|decoder errors this run|runtime.parse_errors||1
storage_queue|how much recording backlog|System|pending storage queue|health.storage.queue|jobs|1
storage_drops|have any recordings been dropped|System|application recording drops this run|store.drops|samples|1
disk_free|how much storage is free|System|free recording disk space|health.free_bytes|gigabytes|0.000000001
temperature|what is the computer temperature|System|reported CPU temperature|health.thermal_c|degrees Celsius|1
cpu|what is the processor load|System|application CPU use|health.cpu_percent_one_core|percent of one core|1
memory|how much memory is being used|System|reported peak backend memory|health.peak_rss_bytes|megabytes, excludes other processes|0.000001
speech_status|is spoken output enabled|Radio|spoken output status|calc.speech_status||1'''

for row in METRICS.splitlines():
    key,phrase,category,label,path,unit,scale=row.split('|')
    CATALOG[key]={'id':key,'request':phrase,'category':category,'kind':'metric','path':path,'scale':float(scale),'unit':unit,'label':label,'answers':[f'{label.capitalize()}: {{value}} {unit}.'.replace(' .','.'),f'For {label}, the reading is {{value}} {unit}.'.replace(' .','.'),f'I have {{value}} {unit} for {label}.'.replace('  ',' ')]}

assert len(CATALOG)==100,len(CATALOG)

def value_at(obj,path):
    for key in path.split('.'):
        if obj is None:return None
        try:obj=obj.get(key) if isinstance(obj,dict) else obj[int(key)] if isinstance(obj,(list,tuple)) else getattr(obj,key,None)
        except (ValueError,IndexError,TypeError):return None
    return obj

def answer(runtime,action,base):
    spec=CATALOG.get(action)
    if not spec:return base,None
    index=runtime.answer_variations.get(action,0)%3;runtime.answer_variations[action]=index+1
    if spec['kind']=='action':return spec['answers'][index].format(answer=base),index
    path=spec['path'];v=runtime.sample.values if runtime.sample else {};stale=runtime.received_at is None or time.monotonic()-runtime.received_at>runtime.settings.stale_seconds
    fresh=path.startswith(('v.','fuel.','analysis.','delta.','car.','sample.')) or action in ('fuel_percent','tyre_front','tyre_rear','delta_trend')
    if path.startswith('unavailable.'):
        return [f"GT7 does not provide {spec['label']} in this player telemetry stream.",f"{spec['label'].capitalize()} is unavailable from GT7 UDP; I cannot infer it reliably.",f"I cannot report {spec['label']}. That data is not transmitted."][index],index
    if fresh and stale:return ['Telemetry is stale. I cannot give a current reading.','No fresh telemetry is available for that request.','I need a current telemetry packet before I can answer that.'][index],index
    if path.startswith('calc.'):
        value=None
        if action=='fuel_percent' and v.get('fuel') is not None and (v.get('fuel_capacity') or 0)>0:value=100*v['fuel']/v['fuel_capacity']
        elif action in ('tyre_front','tyre_rear'):
            tyres=(v.get('tyres') or [None]*4)[0:2] if action=='tyre_front' else (v.get('tyres') or [None]*4)[2:4]
            if len(tyres)==2 and all(t is not None for t in tyres):value=sum(tyres)/2
        elif action=='completed_laps':value=sum(bool(l.get('complete')) for l in runtime.sessions.laps)
        elif action=='delta_trend' and runtime.live_delta.result.get('available'):value={1:'gaining time',-1:'losing time',0:'approximately steady'}[runtime.live_delta.result['trend']]
        elif action=='speech_status':value='muted' if runtime.settings.hard_mute else 'enabled' if runtime.settings.speech_enabled else 'disabled'
    else:
        from .cars import identify
        roots={'v':v,'car':identify(v.get('car_id')),'runtime':runtime,'settings':runtime.settings,'sample':runtime.sample,'fuel':runtime.sessions.fuel(),'report':runtime.sessions.report() if runtime.sessions.id else runtime.sessions.last_report or {},'analysis':runtime.live_analysis.result,'delta':runtime.live_delta.result,'health':runtime.health_cache,'network':runtime.seq.counts,'store':runtime.store}
        value=value_at(roots,path)
    if value is None or value=='' or (isinstance(value,float) and not math.isfinite(value)):
        return [f"{spec['label'].capitalize()} is not available yet.",f"I do not have a reliable value for {spec['label']}.",f"I need more data or configuration to report {spec['label']}."][index],index
    template=spec['answers'][index]
    if isinstance(value,(int,float)):
        number=value*spec['scale']
        number,unit_word=spoken_measure(number,spec['unit'],runtime.settings.units)      # Settings.units (default: unchanged)
        if unit_word!=spec['unit']:template=template.replace(spec['unit'],unit_word)
        value=f'{number:.3f}'.rstrip('0').rstrip('.') if abs(number)<10 else f'{number:.1f}'.rstrip('0').rstrip('.')
    return template.format(value=value),index

def public_catalog():return list(CATALOG.values())
