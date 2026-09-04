!(function(){"use strict";var at=(K,T,n)=>new Promise((A,E)=>{var h=r=>{try{g(n.next(r))}catch(m){E(m)}},a=r=>{try{g(n.throw(r))}catch(m){E(m)}},g=r=>r.done?A(r.value):Promise.resolve(r.value).then(h,a);g((n=n.apply(K,T)).next())});(self.webpackChunkfenix_dashboard_v3=self.webpackChunkfenix_dashboard_v3||[]).push([[6806],{77454:function(K,T,n){n.d(T,{S:function(){return E}});var A=n(86827);function E(h,a){var g,r,m;h.accDescr&&((g=a.setAccDescription)==null||g.call(a,h.accDescr)),h.accTitle&&((r=a.setAccTitle)==null||r.call(a,h.accTitle)),h.title&&((m=a.setDiagramTitle)==null||m.call(a,h.title))}(0,A.K)(E,"populateCommonDb")},76806:function(K,T,n){n.d(T,{diagram:function(){return mt}});var A=n(77454),E=n(5637),h=n(16459),a=n(76385),g=n(31293),r=n(86827),m=n(78731),M=n(12300),j=a.UI.pie,I={sections:new Map,showData:!1,config:j},y=I.sections,B=I.showData,rt=structuredClone(j),it=(0,r.K)(()=>structuredClone(rt),"getConfig"),nt=(0,r.K)(()=>{y=new Map,B=I.showData,(0,a.IU)()},"clear"),st=(0,r.K)(({label:t,value:s})=>{if(s<0)throw new Error(`"${t}" has invalid value: ${s}. Negative values are not allowed in pie charts. All slice values must be >= 0.`);y.has(t)||(y.set(t,s),g.R.debug(`added new section: ${t}, with value: ${s}`))},"addSection"),ot=(0,r.K)(()=>y,"getSections"),lt=(0,r.K)(t=>{B=t},"setShowData"),ct=(0,r.K)(()=>B,"getShowData"),N={getConfig:it,clear:nt,setDiagramTitle:a.ke,getDiagramTitle:a.ab,setAccTitle:a.SV,getAccTitle:a.iN,setAccDescription:a.EI,getAccDescription:a.m7,addSection:st,getSections:ot,setShowData:lt,getShowData:ct},ht=(0,r.K)((t,s)=>{(0,A.S)(t,s),s.setShowData(t.showData),t.sections.map(s.addSection)},"populateDb"),dt={parse:(0,r.K)(t=>at(this,null,function*(){const s=yield(0,m.qg)("pie",t);g.R.debug(s),ht(s,N)}),"parse")},gt=(0,r.K)(t=>`
  .pieCircle{
    stroke: ${t.pieStrokeColor};
    stroke-width : ${t.pieStrokeWidth};
    opacity : ${t.pieOpacity};
  }
  .pieCircle.highlighted{
    scale: 1.05;
    opacity: 1;
  }
  .pieCircle.highlightedOnHover:hover{
    transition-duration: 250ms;
    scale: 1.05;
    opacity: 1;
  }
  .pieOuterCircle{
    stroke: ${t.pieOuterStrokeColor};
    stroke-width: ${t.pieOuterStrokeWidth};
    fill: none;
  }
  .pieTitleText {
    text-anchor: middle;
    font-size: ${t.pieTitleTextSize};
    fill: ${t.pieTitleTextColor};
    font-family: ${t.fontFamily};
  }
  .slice {
    font-family: ${t.fontFamily};
    fill: ${t.pieSectionTextColor};
    font-size:${t.pieSectionTextSize};
    // fill: white;
  }
  .legend text {
    fill: ${t.pieLegendTextColor};
    font-family: ${t.fontFamily};
    font-size: ${t.pieLegendTextSize};
  }
`,"getStyles"),ut=gt,_t=(0,r.K)(t=>{const s=[...t.values()].reduce((c,x)=>c+x,0),b=[...t.entries()].map(([c,x])=>({label:c,value:x})).filter(c=>c.value/s*100>=1);return(0,M.rLf)().value(c=>c.value).sort(null)(b)},"createPieArcs"),pt=(0,r.K)((t,s,b,Z)=>{var tt,et;g.R.debug(`rendering pie chart
`+t);const c=Z.db,x=(0,a.D7)(),v=(0,h.$t)(c.getConfig(),x.pie),Y=40,o=18,u=4,w=450,$=w,U=(0,E.D)(s),L=U.append("g");L.attr("transform","translate("+$/2+","+w/2+")");const{themeVariables:l}=x;let[R]=(0,h.I5)(l.pieOuterStrokeWidth);R!=null||(R=2);const vt=v.legendPosition,J=v.textPosition,Dt=v.donutHole>0&&v.donutHole<=.9?v.donutHole:0,D=Math.min($,w)/2-Y,Ct=(0,M.JLW)().innerRadius(Dt*D).outerRadius(D),Et=(0,M.JLW)().innerRadius(D*J).outerRadius(D*J),O=L.append("g");O.append("circle").attr("cx",0).attr("cy",0).attr("r",D+R/2).attr("class","pieOuterCircle");const k=c.getSections(),xt=_t(k),St=[l.pie1,l.pie2,l.pie3,l.pie4,l.pie5,l.pie6,l.pie7,l.pie8,l.pie9,l.pie10,l.pie11,l.pie12];let z=0;k.forEach(e=>{z+=e});const V=xt.filter(e=>(e.data.value/z*100).toFixed(0)!=="0"),F=(0,M.UMr)(St).domain([...k.keys()]);O.selectAll("mySlices").data(V).enter().append("path").attr("d",Ct).attr("fill",e=>F(e.data.label)).attr("class",e=>{let i="pieCircle";return v.highlightSlice==="hover"?i+=" highlightedOnHover":v.highlightSlice===e.data.label&&(i+=" highlighted"),i}),O.selectAll("mySlices").data(V).enter().append("text").text(e=>(e.data.value/z*100).toFixed(0)+"%").attr("transform",e=>"translate("+Et.centroid(e)+")").style("text-anchor","middle").attr("class","slice");const Tt=L.append("text").text(c.getDiagramTitle()).attr("x",0).attr("y",-(w-50)/2).attr("class","pieTitleText"),P=[...k.entries()].map(([e,i])=>({label:e,value:i})),C=L.selectAll(".legend").data(P).enter().append("g").attr("class","legend");C.append("rect").attr("width",o).attr("height",o).style("fill",e=>F(e.label)).style("stroke",e=>F(e.label)),C.append("text").attr("x",o+u).attr("y",o-u).text(e=>c.getShowData()?`${e.label} [${e.value}]`:e.label);const S=Math.max(...C.selectAll("text").nodes().map(e=>{var i;return(i=e==null?void 0:e.getBoundingClientRect().width)!=null?i:0}));let W=w,H=$+Y;const d=o+u,G=P.length*d;switch(vt){case"center":C.attr("transform",(e,i)=>{const _=d*P.length/2,p=-S/2-(o+u),f=i*d-_;return"translate("+p+","+f+")"});break;case"top":W+=G,C.attr("transform",(e,i)=>{const _=D,p=-S/2-(o+u),f=i*d-_;return`translate(${p}, ${f})`}),O.attr("transform",()=>`translate(0, ${G+d})`);break;case"bottom":W+=G,C.attr("transform",(e,i)=>{const _=-D-d,p=-S/2-(o+u),f=i*d-_;return"translate("+p+","+f+")"});break;case"left":H+=o+u+S,C.attr("transform",(e,i)=>{const _=d*P.length/2,p=-D-(o+u),f=i*d-_;return"translate("+p+","+f+")"}),O.attr("transform",()=>`translate(${S+o+u}, 0)`);break;case"right":default:H+=o+u+S,C.attr("transform",(e,i)=>{const _=d*P.length/2,p=12*o,f=i*d-_;return"translate("+p+","+f+")"});break}const X=(et=(tt=Tt.node())==null?void 0:tt.getBoundingClientRect().width)!=null?et:0,At=$/2-X/2,wt=$/2+X/2,Q=Math.min(0,At),q=Math.max(H,wt)-Q;U.attr("viewBox",`${Q} 0 ${q} ${W}`),(0,a.a$)(U,W,q,v.useMaxWidth)},"draw"),ft={draw:pt},mt={parser:dt,db:N,renderer:ft,styles:ut}}}]);
}());