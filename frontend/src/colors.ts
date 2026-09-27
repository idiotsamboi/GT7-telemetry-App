// Semantic channels never change color when reordered or selected alone.
export const colors={throttle:'#25e58b',brake:'#ff354b',clutch:'#9edbff',fastest:'#ba65ff',personal:'#25e58b',otherLap:'#f4d34e'};
export function channelColor(channel:string){
 const key=channel.toLowerCase();
 if(key.includes('throttle'))return colors.throttle;
 if(key.includes('brake'))return colors.brake;
 if(key.includes('clutch'))return colors.clutch;
 const palette=['#ffac55','#db8fff','#5ad5ce','#f18ac3','#95a4ff','#d8e07a','#e4a67f'];
 let hash=0;for(const c of key)hash=(hash*31+c.charCodeAt(0))>>>0;
 return palette[hash%palette.length];
}
