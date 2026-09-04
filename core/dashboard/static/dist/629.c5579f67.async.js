!(function(){"use strict";var Ut=Object.defineProperty;var $t=Object.getOwnPropertySymbols;var Yt=Object.prototype.hasOwnProperty,Ft=Object.prototype.propertyIsEnumerable;var _t=(_,p,s)=>p in _?Ut(_,p,{enumerable:!0,configurable:!0,writable:!0,value:s}):_[p]=s,ot=(_,p)=>{for(var s in p||(p={}))Yt.call(p,s)&&_t(_,s,p[s]);if($t)for(var s of $t(p))Ft.call(p,s)&&_t(_,s,p[s]);return _};var Ct=(_,p,s)=>new Promise((X,S)=>{var g=a=>{try{C(s.next(a))}catch(E){S(E)}},c=a=>{try{C(s.throw(a))}catch(E){S(E)}},C=a=>a.done?X(a.value):Promise.resolve(a.value).then(g,c);C((s=s.apply(_,p)).next())});(self.webpackChunkfenix_dashboard_v3=self.webpackChunkfenix_dashboard_v3||[]).push([[629],{77454:function(_,p,s){s.d(p,{S:function(){return S}});var X=s(86827);function S(g,c){var C,a,E;g.accDescr&&((C=c.setAccDescription)==null||C.call(c,g.accDescr)),g.accTitle&&((a=c.setAccTitle)==null||a.call(c,g.accTitle)),g.title&&((E=c.setDiagramTitle)==null||E.call(c,g.title))}(0,X.K)(S,"populateCommonDb")},30629:function(_,p,s){s.d(p,{diagram:function(){return Wt}});var X=s(77454),S=s(5637),g=s(16459),c=s(76385),C=s(31293),a=s(86827),E=s(78731),at=(0,a.K)(()=>({domains:new Map,transitions:[]}),"createDefaultData"),Z=at(),bt=(0,a.K)(()=>Z.domains,"getDomains"),Dt=(0,a.K)(()=>Z.transitions,"getTransitions"),wt=(0,a.K)(t=>{var e;if(t)for(const n of t){const o=n.domain,f=((e=n.items)!=null?e:[]).map(m=>({label:m.label}));Z.domains.set(o,{name:o,items:f})}},"setDomains"),vt=(0,a.K)(t=>{t&&(Z.transitions=t.filter(e=>e.from===e.to?(C.R.warn(`Cynefin: self-loop transition on domain "${e.from}" is not meaningful and will be skipped.`),!1):!0).map(e=>({from:e.from,to:e.to,label:e.label||void 0})))},"setTransitions"),Tt=(0,a.K)(()=>(0,g.$t)(ot(ot({},c.UI.cynefin),(0,c.zj)().cynefin)),"getConfig"),At=(0,a.K)(()=>{(0,c.IU)(),Z=at()},"clear"),Q={getDomains:bt,getTransitions:Dt,setDomains:wt,setTransitions:vt,getConfig:Tt,clear:At,setAccTitle:c.SV,getAccTitle:c.iN,setDiagramTitle:c.ke,getDiagramTitle:c.ab,getAccDescription:c.m7,setAccDescription:c.EI},kt=(0,a.K)(t=>{(0,X.S)(t,Q),Q.setDomains(t.domains),Q.setTransitions(t.transitions)},"populate"),Et={parse:(0,a.K)(t=>Ct(this,null,function*(){const e=yield(0,E.qg)("cynefin",t);C.R.debug(e),kt(e)}),"parse")};function J(t){let e=t+1831565813|0;return e=Math.imul(e^e>>>15,e|1),e^=e+Math.imul(e^e>>>7,e|61),((e^e>>>14)>>>0)/4294967296}(0,a.K)(J,"seededRandom");function rt(t){let e=0;for(let n=0;n<t.length;n++){const o=t.charCodeAt(n);e=(e<<5)-e+o,e|=0}return e}(0,a.K)(rt,"hashString");function st(t,e){return typeof t=="number"&&Number.isFinite(t)&&t!==0?t:rt(e)}(0,a.K)(st,"resolveSeed");function ct(t,e,n,o){const f=t/2,m=o!=null?o:t*.015,M=7,Y=e/M,y=[];for(let r=0;r<=M;r++){const h=J(n+r*17)*m*2-m;y.push({x:f+h,y:r*Y})}let P=`M${y[0].x},${y[0].y}`;for(let r=0;r<y.length-1;r++){const h=y[r],l=y[r+1],u=(h.y+l.y)/2,T=r%2===0?1:-1,b=m*1.5*T*J(n+r*31+7),F=h.x+b,V=u,H=l.x-b;P+=` C${F},${V} ${H},${u} ${l.x},${l.y}`}return P}(0,a.K)(ct,"generateFoldPath");function it(t,e,n,o){const f=e/2,m=o!=null?o:e*.015,M=7,Y=t/M,y=[];for(let r=0;r<=M;r++){const h=J(n+r*23)*m*2-m;y.push({x:r*Y,y:f+h})}let P=`M${y[0].x},${y[0].y}`;for(let r=0;r<y.length-1;r++){const h=y[r],l=y[r+1],u=(h.x+l.x)/2,T=r%2===0?1:-1,b=m*1.5*T*J(n+r*37+11),F=u,V=h.y+b,H=u,z=l.y-b;P+=` C${F},${V} ${H},${z} ${l.x},${l.y}`}return P}(0,a.K)(it,"generateHorizontalBoundary");function lt(t,e){const n=t/2,o=e*.5,f=e,m=t*.03;return[`M${n},${o}`,`C${n+m},${o+(f-o)*.2}`,`${n-m*1.5},${o+(f-o)*.55}`,`${n+m*.5},${o+(f-o)*.75}`,`C${n-m},${o+(f-o)*.85}`,`${n+m*.3},${o+(f-o)*.95}`,`${n},${f}`].join(" ")}(0,a.K)(lt,"generateCliffPath");function ft(t,e,n,o){return[`M${t-n},${e}`,`A${n},${o} 0 1,1 ${t+n},${e}`,`A${n},${o} 0 1,1 ${t-n},${e}`,"Z"].join(" ")}(0,a.K)(ft,"generateConfusionPath");var dt={complex:{model:"Probe \u2192 Sense \u2192 Respond",practice:"Emergent Practices"},complicated:{model:"Sense \u2192 Analyse \u2192 Respond",practice:"Good Practices"},clear:{model:"Sense \u2192 Categorise \u2192 Respond",practice:"Best Practices"},chaotic:{model:"Act \u2192 Sense \u2192 Respond",practice:"Novel Practices"},confusion:{model:"",practice:"Disorder"}},Mt=(0,a.K)((t,e)=>{const n=t/2,o=e/2;return{complex:{cx:n/2,cy:o/2,x:0,y:0,w:n,h:o},complicated:{cx:n+n/2,cy:o/2,x:n,y:0,w:n,h:o},chaotic:{cx:n/2,cy:o+o/2,x:0,y:o,w:n,h:o},clear:{cx:n+n/2,cy:o+o/2,x:n,y:o,w:n,h:o},confusion:{cx:n,cy:o,x:n*.7,y:o*.7,w:n*.6,h:o*.6}}},"getDomainLayouts"),Pt=(0,a.K)(()=>{const t=(0,c.P$)(),e=(0,c.zj)();return(0,g.$t)(t,e.themeVariables).cynefin},"getCynefinDomainColors"),tt=3,Bt=(0,a.K)((t,e,n,o)=>{var ht;const f=o.db,m=f.getDomains(),M=f.getTransitions(),Y=f.getDiagramTitle(),y=f.getAccTitle(),P=f.getAccDescription(),r=f.getConfig(),h=Pt();C.R.debug("Rendering Cynefin diagram");const l=r.width,u=r.height,T=r.padding,b=r.showDomainDescriptions,F=r.boundaryAmplitude,V=l+T*2,H=u+T*2,z={complex:h.complexBg,complicated:h.complicatedBg,clear:h.clearBg,chaotic:h.chaoticBg,confusion:h.confusionBg},B=(0,S.D)(e);(0,c.a$)(B,H,V,(ht=r.useMaxWidth)!=null?ht:!0),B.attr("viewBox",`0 0 ${V} ${H}`),y&&B.append("title").text(y),P&&B.append("desc").text(P);const K=B.append("g").attr("transform",`translate(${T}, ${T})`),G=Mt(l,u),mt=st(r.seed,e),St=K.append("g").attr("class","cynefin-backgrounds"),et=["complex","complicated","chaotic","clear"];for(const d of et){const i=G[d];St.append("rect").attr("class","cynefinDomain").attr("x",i.x).attr("y",i.y).attr("width",i.w).attr("height",i.h).attr("fill",z[d]).attr("fill-opacity",.4).attr("stroke","none")}const nt=K.append("g").attr("class","cynefin-boundaries");nt.append("path").attr("class","cynefinBoundary").attr("d",ct(l,u,mt,F)).attr("fill","none"),nt.append("path").attr("class","cynefinBoundary").attr("d",it(l,u,mt+100,F)).attr("fill","none"),nt.append("path").attr("class","cynefinCliff").attr("d",lt(l,u)).attr("fill","none");const zt=l*.15,jt=u*.15;K.append("path").attr("class","cynefinConfusion").attr("d",ft(l/2,u/2,zt,jt)).attr("fill",z.confusion).attr("fill-opacity",.5);const pt=K.append("g").attr("class","cynefin-labels");for(const d of et){const i=G[d];pt.append("text").attr("class","cynefinDomainLabel").attr("x",i.cx).attr("y",b?i.cy-30:i.cy).attr("text-anchor","middle").attr("dominant-baseline","middle").text(d.charAt(0).toUpperCase()+d.slice(1))}if(pt.append("text").attr("class","cynefinDomainLabel").attr("x",l/2).attr("y",b?u/2-10:u/2).attr("text-anchor","middle").attr("dominant-baseline","middle").text("Confusion"),b){const d=K.append("g").attr("class","cynefin-subtitles");for(const i of et){const $=G[i],x=dt[i];d.append("text").attr("class","cynefinSubtitle").attr("x",$.cx).attr("y",$.cy-10).attr("text-anchor","middle").attr("dominant-baseline","middle").text(x.model),d.append("text").attr("class","cynefinSubtitle").attr("x",$.cx).attr("y",$.cy+5).attr("text-anchor","middle").attr("dominant-baseline","middle").text(x.practice)}d.append("text").attr("class","cynefinSubtitle").attr("x",l/2).attr("y",u/2+8).attr("text-anchor","middle").attr("dominant-baseline","middle").text(dt.confusion.practice)}const yt=K.append("g").attr("class","cynefin-items"),L=26,ut=10,Ot=["complex","complicated","chaotic","clear","confusion"];for(const d of Ot){const i=m.get(d);if(!i||i.items.length===0)continue;const $=G[d],x=d==="confusion";let j=i.items,O=0;x&&i.items.length>tt&&(O=i.items.length-tt,j=i.items.slice(0,tt));let I;if(x){const w=b?22:14;I=$.cy+w}else I=$.cy+(b?25:15);if([...j].forEach((w,R)=>{const A=I+R*(L+4),W=yt.append("g"),N=W.append("text").attr("class","cynefinItemText").attr("x",0).attr("y",L/2).attr("text-anchor","middle").attr("dominant-baseline","central").text(w.label);let v=w.label.length*7;const D=N.node();if(D&&typeof D.getBBox=="function"){const q=D.getBBox();q.width>0&&(v=q.width)}const k=v+ut*2,U=$.cx-k/2;W.attr("transform",`translate(${U}, ${A})`),W.insert("rect","text").attr("class","cynefinItem").attr("x",0).attr("y",0).attr("width",k).attr("height",L).attr("rx",4).attr("ry",4).attr("fill",z[d]).attr("fill-opacity",.95),N.attr("x",k/2).attr("y",L/2)}),O>0){const w=I+j.length*(L+4),R=`+${O} more`,A=yt.append("g"),W=A.append("text").attr("class","cynefinItemText").attr("x",0).attr("y",L/2).attr("text-anchor","middle").attr("dominant-baseline","central").text(R);let N=R.length*7;const v=W.node();if(v&&typeof v.getBBox=="function"){const U=v.getBBox();U.width>0&&(N=U.width)}const D=N+ut*2,k=$.cx-D/2;A.attr("transform",`translate(${k}, ${w})`),A.insert("rect","text").attr("class","cynefinItemOverflow").attr("x",0).attr("y",0).attr("width",D).attr("height",L).attr("rx",4).attr("ry",4).attr("fill",z[d]).attr("fill-opacity",.6),W.attr("x",D/2).attr("y",L/2)}}if(M.length>0){const d=B.select("defs").empty()?B.append("defs"):B.select("defs"),i=`cynefin-arrow-${e}`;d.append("marker").attr("id",i).attr("viewBox","0 0 10 10").attr("refX",9).attr("refY",5).attr("markerWidth",6).attr("markerHeight",6).attr("orient","auto-start-reverse").append("path").attr("d","M 0 0 L 10 5 L 0 10 z").attr("class","cynefinArrowHead");const $=K.append("g").attr("class","cynefin-arrows");M.forEach(x=>{const j=G[x.from],O=G[x.to];if(!j||!O)return;if(x.from===x.to){C.R.warn(`Cynefin renderer: skipping self-loop on domain "${x.from}"`);return}const I=j.cx,w=j.cy,R=O.cx,A=O.cy,W=(I+R)/2,N=(w+A)/2,v=R-I,D=A-w,k=Math.sqrt(v*v+D*D),U=k*.15,q=-D/k,Nt=v/k,xt=W+q*U,gt=N+Nt*U;$.append("path").attr("class","cynefinArrowLine").attr("d",`M${I},${w} Q${xt},${gt} ${R},${A}`).attr("fill","none").attr("marker-end",`url(#${i})`),x.label&&$.append("text").attr("class","cynefinArrowLabel").attr("x",xt).attr("y",gt-6).attr("text-anchor","middle").attr("dominant-baseline","auto").text(x.label)})}Y&&K.append("text").attr("class","cynefinTitle").attr("x",l/2).attr("y",-T/2).attr("text-anchor","middle").attr("dominant-baseline","middle").text(Y)},"draw"),Kt={draw:Bt},Lt=(0,a.K)(()=>{const t=(0,c.P$)(),e=(0,c.zj)();return(0,g.$t)(t,e.themeVariables).cynefin},"getCynefinTheme"),It=(0,a.K)(()=>{const t=Lt();return`
	.cynefinDomain {
		stroke: none;
	}
	.cynefinDomainLabel {
		font-size: ${t.domainFontSize}px;
		font-weight: bold;
		fill: ${t.labelColor};
	}
	.cynefinSubtitle {
		font-size: ${t.itemFontSize-1}px;
		fill: ${t.textColor};
		font-style: italic;
	}
	.cynefinItem {
		fill-opacity: 0.95;
		stroke: ${t.boundaryColor};
		stroke-width: 1;
	}
	.cynefinItemText {
		font-size: ${t.itemFontSize}px;
		fill: ${t.textColor};
	}
	.cynefinItemOverflow {
		fill-opacity: 0.6;
		stroke: ${t.boundaryColor};
		stroke-width: 1;
		stroke-dasharray: 3 2;
	}
	.cynefinBoundary {
		stroke: ${t.boundaryColor};
		stroke-width: ${t.boundaryWidth};
		stroke-dasharray: 6 3;
	}
	.cynefinCliff {
		stroke: ${t.cliffColor};
		stroke-width: ${t.cliffWidth};
	}
	.cynefinConfusion {
		stroke: ${t.boundaryColor};
		stroke-width: 1.5;
		stroke-dasharray: 4 2;
	}
	.cynefinArrowLine {
		stroke: ${t.arrowColor};
		stroke-width: ${t.arrowWidth};
		fill: none;
	}
	.cynefinArrowHead {
		fill: ${t.arrowColor};
		stroke: none;
	}
	.cynefinArrowLabel {
		font-size: ${t.itemFontSize-1}px;
		fill: ${t.textColor};
	}
	.cynefinTitle {
		font-size: ${t.domainFontSize+2}px;
		font-weight: bold;
		fill: ${t.labelColor};
	}
	`},"styles"),Rt=It,Wt={parser:Et,db:Q,renderer:Kt,styles:Rt}}}]);
}());