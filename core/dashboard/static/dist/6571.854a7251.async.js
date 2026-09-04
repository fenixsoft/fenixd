!(function(){"use strict";var ct=Object.defineProperty;var W=Object.getOwnPropertySymbols;var lt=Object.prototype.hasOwnProperty,dt=Object.prototype.propertyIsEnumerable;var B=(_,h,i)=>h in _?ct(_,h,{enumerable:!0,configurable:!0,writable:!0,value:i}):_[h]=i,T=(_,h)=>{for(var i in h||(h={}))lt.call(h,i)&&B(_,i,h[i]);if(W)for(var i of W(h))dt.call(h,i)&&B(_,i,h[i]);return _};var F=(_,h,i)=>new Promise((E,M)=>{var v=s=>{try{C(i.next(s))}catch(f){M(f)}},u=s=>{try{C(i.throw(s))}catch(f){M(f)}},C=s=>s.done?E(s.value):Promise.resolve(s.value).then(v,u);C((i=i.apply(_,h)).next())});(self.webpackChunkfenix_dashboard_v3=self.webpackChunkfenix_dashboard_v3||[]).push([[6571],{77454:function(_,h,i){i.d(h,{S:function(){return M}});var E=i(86827);function M(v,u){var C,s,f;v.accDescr&&((C=u.setAccDescription)==null||C.call(u,v.accDescr)),v.accTitle&&((s=u.setAccTitle)==null||s.call(u,v.accTitle)),v.title&&((f=u.setDiagramTitle)==null||f.call(u,v.title))}(0,E.K)(M,"populateCommonDb")},76571:function(_,h,i){i.d(h,{diagram:function(){return ot}});var E=i(77454),M=i(5637),v=i(16459),u=i(76385),C=i(31293),s=i(86827),f=i(78731),A={showLegend:!0,ticks:5,max:null,min:0,graticule:"circle"},K=32,P={axes:[],curves:[],options:A},$=structuredClone(P),U=u.UI.radar,j=(0,s.K)(()=>(0,v.$t)(T(T({},U),(0,u.zj)().radar)),"getConfig"),k=(0,s.K)(()=>$.axes,"getAxes"),z=(0,s.K)(()=>$.curves,"getCurves"),G=(0,s.K)(()=>$.options,"getOptions"),V=(0,s.K)(a=>{$.axes=a.map(t=>{var e;return{name:t.name,label:(e=t.label)!=null?e:t.name}})},"setAxes"),Y=(0,s.K)(a=>{$.curves=a.map(t=>{var e;return{name:t.name,label:(e=t.label)!=null?e:t.name,entries:Z(t.entries)}})},"setCurves"),Z=(0,s.K)(a=>{if(a[0].axis==null)return a.map(e=>e.value);const t=k();if(t.length===0)throw new Error("Axes must be populated before curves for reference entries");return t.map(e=>{const r=a.find(n=>{var o;return((o=n.axis)==null?void 0:o.$refText)===e.name});if(r===void 0)throw new Error("Missing entry for axis "+e.label);return r.value})},"computeCurveEntries"),H=(0,s.K)(a=>{var e,r,n,o,d,c,l,p,x,m;const t=a.reduce((g,y)=>(g[y.name]=y,g),{});$.options={showLegend:(r=(e=t.showLegend)==null?void 0:e.value)!=null?r:A.showLegend,ticks:(o=(n=t.ticks)==null?void 0:n.value)!=null?o:A.ticks,max:(c=(d=t.max)==null?void 0:d.value)!=null?c:A.max,min:(p=(l=t.min)==null?void 0:l.value)!=null?p:A.min,graticule:(m=(x=t.graticule)==null?void 0:x.value)!=null?m:A.graticule},$.options.ticks>K&&(C.R.warn(`Radar diagram ticks (${$.options.ticks}) exceeds maximum allowed (${K}). Using ${K} instead.`),$.options.ticks=K)},"setOptions"),X=(0,s.K)(()=>{(0,u.IU)(),$=structuredClone(P)},"clear"),w={getAxes:k,getCurves:z,getOptions:G,setAxes:V,setCurves:Y,setOptions:H,getConfig:j,clear:X,setAccTitle:u.SV,getAccTitle:u.iN,setDiagramTitle:u.ke,getDiagramTitle:u.ab,getAccDescription:u.m7,setAccDescription:u.EI},J=(0,s.K)(a=>{(0,E.S)(a,w);const{axes:t,curves:e,options:r}=a;w.setAxes(t),w.setCurves(e),w.setOptions(r)},"populate"),N={parse:(0,s.K)(a=>F(this,null,function*(){const t=yield(0,f.qg)("radar",a);C.R.debug(t),J(t)}),"parse")},Q=(0,s.K)((a,t,e,r)=>{var L;const n=r.db,o=n.getAxes(),d=n.getCurves(),c=n.getOptions(),l=n.getConfig(),p=n.getDiagramTitle(),x=(0,M.D)(t),m=q(x,l),g=(L=c.max)!=null?L:Math.max(...d.map(O=>Math.max(...O.entries))),y=c.min,D=Math.min(l.width,l.height)/2;tt(m,o,D,c.ticks,c.graticule),et(m,o,D,l),I(m,o,d,y,g,c.graticule,l),b(m,d,c.showLegend,l),m.append("text").attr("class","radarTitle").text(p).attr("x",0).attr("y",-l.height/2-l.marginTop)},"draw"),q=(0,s.K)((a,t)=>{var o;const e=t.width+t.marginLeft+t.marginRight,r=t.height+t.marginTop+t.marginBottom,n={x:t.marginLeft+t.width/2,y:t.marginTop+t.height/2};return(0,u.a$)(a,r,e,(o=t.useMaxWidth)!=null?o:!0),a.attr("viewBox",`0 0 ${e} ${r}`).attr("overflow","visible"),a.append("g").attr("transform",`translate(${n.x}, ${n.y})`)},"drawFrame"),tt=(0,s.K)((a,t,e,r,n)=>{if(n==="circle")for(let o=0;o<r;o++){const d=e*(o+1)/r;a.append("circle").attr("r",d).attr("class","radarGraticule")}else if(n==="polygon"){const o=t.length;for(let d=0;d<r;d++){const c=e*(d+1)/r,l=t.map((p,x)=>{const m=2*x*Math.PI/o-Math.PI/2,g=c*Math.cos(m),y=c*Math.sin(m);return`${g},${y}`}).join(" ");a.append("polygon").attr("points",l).attr("class","radarGraticule")}}},"drawGraticule"),et=(0,s.K)((a,t,e,r)=>{const n=t.length;for(let o=0;o<n;o++){const d=t[o].label,c=2*o*Math.PI/n-Math.PI/2,l=Math.cos(c),p=Math.sin(c);a.append("line").attr("x1",0).attr("y1",0).attr("x2",e*r.axisScaleFactor*l).attr("y2",e*r.axisScaleFactor*p).attr("class","radarAxisLine");const x=l>.01?"start":l<-.01?"end":"middle",m=p>.01?"hanging":p<-.01?"auto":"central",g=4;a.append("text").text(d).attr("x",e*r.axisLabelFactor*l+g*l).attr("y",e*r.axisLabelFactor*p+g*p).attr("text-anchor",x).attr("dominant-baseline",m).attr("class","radarAxisLabel")}},"drawAxes");function I(a,t,e,r,n,o,d){const c=t.length,l=Math.min(d.width,d.height)/2;e.forEach((p,x)=>{if(p.entries.length!==c)return;const m=p.entries.map((g,y)=>{const D=2*Math.PI*y/c-Math.PI/2,L=R(g,r,n,l),O=L*Math.cos(D),it=L*Math.sin(D);return{x:O,y:it}});o==="circle"?a.append("path").attr("d",S(m,d.curveTension)).attr("class",`radarCurve-${x}`):o==="polygon"&&a.append("polygon").attr("points",m.map(g=>`${g.x},${g.y}`).join(" ")).attr("class",`radarCurve-${x}`)})}(0,s.K)(I,"drawCurves");function R(a,t,e,r){const n=Math.min(Math.max(a,t),e);return r*(n-t)/(e-t)}(0,s.K)(R,"relativeRadius");function S(a,t){const e=a.length;let r=`M${a[0].x},${a[0].y}`;for(let n=0;n<e;n++){const o=a[(n-1+e)%e],d=a[n],c=a[(n+1)%e],l=a[(n+2)%e],p={x:d.x+(c.x-o.x)*t,y:d.y+(c.y-o.y)*t},x={x:c.x-(l.x-d.x)*t,y:c.y-(l.y-d.y)*t};r+=` C${p.x},${p.y} ${x.x},${x.y} ${c.x},${c.y}`}return`${r} Z`}(0,s.K)(S,"closedRoundCurve");function b(a,t,e,r){if(!e)return;const n=(r.width/2+r.marginRight)*3/4,o=-(r.height/2+r.marginTop)*3/4,d=20;t.forEach((c,l)=>{const p=a.append("g").attr("transform",`translate(${n}, ${o+l*d})`);p.append("rect").attr("width",12).attr("height",12).attr("class",`radarLegendBox-${l}`),p.append("text").attr("x",16).attr("y",0).attr("class","radarLegendText").text(c.label)})}(0,s.K)(b,"drawLegend");var at={draw:Q},rt=(0,s.K)((a,t)=>{let e="";for(let r=0;r<a.THEME_COLOR_LIMIT;r++){const n=a[`cScale${r}`];e+=`
		.radarCurve-${r} {
			color: ${n};
			fill: ${n};
			fill-opacity: ${t.curveOpacity};
			stroke: ${n};
			stroke-width: ${t.curveStrokeWidth};
		}
		.radarLegendBox-${r} {
			fill: ${n};
			fill-opacity: ${t.curveOpacity};
			stroke: ${n};
		}
		`}return e},"genIndexStyles"),nt=(0,s.K)(a=>{const t=(0,u.P$)(),e=(0,u.zj)(),r=(0,v.$t)(t,e.themeVariables),n=(0,v.$t)(r.radar,a);return{themeVariables:r,radarOptions:n}},"buildRadarStyleOptions"),st=(0,s.K)(({radar:a}={})=>{const{themeVariables:t,radarOptions:e}=nt(a);return`
	.radarTitle {
		font-size: ${t.fontSize};
		color: ${t.titleColor};
		dominant-baseline: hanging;
		text-anchor: middle;
	}
	.radarAxisLine {
		stroke: ${e.axisColor};
		stroke-width: ${e.axisStrokeWidth};
	}
	.radarAxisLabel {
		font-size: ${e.axisLabelFontSize}px;
		color: ${e.axisColor};
	}
	.radarGraticule {
		fill: ${e.graticuleColor};
		fill-opacity: ${e.graticuleOpacity};
		stroke: ${e.graticuleColor};
		stroke-width: ${e.graticuleStrokeWidth};
	}
	.radarLegendText {
		text-anchor: start;
		font-size: ${e.legendFontSize}px;
		dominant-baseline: hanging;
	}
	${rt(t,e)}
	`},"styles"),ot={parser:N,db:w,renderer:at,styles:st}}}]);
}());