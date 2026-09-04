!(function(){"use strict";var Re=Object.defineProperty,Se=Object.defineProperties;var Fe=Object.getOwnPropertyDescriptors;var B=Object.getOwnPropertySymbols;var Q=Object.prototype.hasOwnProperty,V=Object.prototype.propertyIsEnumerable;var q=(T,x,g)=>x in T?Re(T,x,{enumerable:!0,configurable:!0,writable:!0,value:g}):T[x]=g,v=(T,x)=>{for(var g in x||(x={}))Q.call(x,g)&&q(T,g,x[g]);if(B)for(var g of B(x))V.call(x,g)&&q(T,g,x[g]);return T},$=(T,x)=>Se(T,Fe(x));var ee=(T,x)=>{var g={};for(var S in T)Q.call(T,S)&&x.indexOf(S)<0&&(g[S]=T[S]);if(T!=null&&B)for(var S of B(T))x.indexOf(S)<0&&V.call(T,S)&&(g[S]=T[S]);return g};(self.webpackChunkfenix_dashboard_v3=self.webpackChunkfenix_dashboard_v3||[]).push([[6164],{77454:function(T,x,g){g.d(x,{S:function(){return y}});var S=g(86827);function y(C,d){var A,K,O;C.accDescr&&((A=d.setAccDescription)==null||A.call(d,C.accDescr)),C.accTitle&&((K=d.setAccTitle)==null||K.call(d,C.accTitle)),C.title&&((O=d.setDiagramTitle)==null||O.call(d,C.title))}(0,S.K)(y,"populateCommonDb")},19279:function(T,x,g){var N,b;g.d(x,{$:function(){return xe},U:function(){return ke},db:function(){return X}});var S=g(5637),y=g(76385),C=g(31293),d=g(86827),A="",K="",O="",Y=[],P=new Map,_=(0,d.K)(e=>(0,y.jZ)(e,(0,y.D7)()),"sanitizeText"),E=(0,d.K)(e=>{switch(e.type){case"terminal":return $(v({},e),{value:_(e.value)});case"nonterminal":return $(v({},e),{name:_(e.name)});case"sequence":return $(v({},e),{elements:e.elements.map(E)});case"choice":return $(v({},e),{alternatives:e.alternatives.map(E)});case"optional":return $(v({},e),{element:E(e.element)});case"repetition":return $(v({},e),{element:E(e.element),separator:e.separator?E(e.separator):void 0});case"special":return $(v({},e),{text:_(e.text)})}},"sanitizeAstNode"),te=(0,d.K)(()=>{A="",K="",O="",Y.length=0,P.clear(),(0,y.IU)(),C.R.debug("[Railroad] Database cleared")},"clear"),U=(0,d.K)(e=>{A=_(e),C.R.debug("[Railroad] Title set:",e)},"setTitle"),j=(0,d.K)(()=>A,"getTitle"),re=(0,d.K)(e=>{const i=$(v({},e),{name:_(e.name),definition:E(e.definition),comment:e.comment?_(e.comment):void 0});C.R.debug("[Railroad] Adding rule:",i.name),P.has(i.name)&&C.R.warn(`[Railroad] Rule '${i.name}' is already defined. Overwriting.`),Y.push(i),P.set(i.name,i)},"addRule"),ie=(0,d.K)(()=>Y,"getRules"),ne=(0,d.K)(e=>P.get(e),"getRule"),ae=(0,d.K)(e=>{K=_(e).replace(/^\s+/g,""),C.R.debug("[Railroad] Accessibility title set:",e)},"setAccTitle"),oe=(0,d.K)(()=>K,"getAccTitle"),le=(0,d.K)(e=>{O=_(e).replace(/\n\s+/g,`
`),C.R.debug("[Railroad] Accessibility description set:",e)},"setAccDescription"),se=(0,d.K)(()=>O,"getAccDescription"),de=U,ce=j,X={clear:te,setTitle:U,getTitle:j,addRule:re,getRules:ie,getRule:ne,setAccTitle:ae,getAccTitle:oe,setAccDescription:le,getAccDescription:se,setDiagramTitle:de,getDiagramTitle:ce},k={compactMode:!1,padding:10,verticalSeparation:8,horizontalSeparation:10,arcRadius:10,fontSize:14,fontFamily:"monospace",terminalFill:"#FFFFC0",terminalStroke:"#000000",terminalTextColor:"#000000",nonTerminalFill:"#FFFFFF",nonTerminalStroke:"#000000",nonTerminalTextColor:"#000000",lineColor:"#000000",strokeWidth:2,markerFill:"#000000",commentFill:"#E8E8E8",commentStroke:"#888888",commentTextColor:"#666666",specialFill:"#F0E0FF",specialStroke:"#8800CC",ruleNameColor:"#000066",showMarkers:!0,markerRadius:5},me=/^#(?:[\da-f]{3,4}|[\da-f]{6}|[\da-f]{8})$|^(?:rgb|rgba|hsl|hsla|hwb|lab|lch|oklab|oklch)\([\d\s%+,./-]+\)$|^[a-z]+$/i,he=/^[\w "',.-]+$/,pe=new Set(["compactMode","padding","verticalSeparation","horizontalSeparation","arcRadius","fontSize","fontFamily","terminalFill","terminalStroke","terminalTextColor","nonTerminalFill","nonTerminalStroke","nonTerminalTextColor","lineColor","strokeWidth","markerFill","commentFill","commentStroke","commentTextColor","specialFill","specialStroke","ruleNameColor","showMarkers","markerRadius"]),H=(0,d.K)(e=>e?Object.keys(e).every(i=>i==="railroad"||pe.has(i)):!1,"isRailroadStyleOptions"),ue=(0,d.K)(e=>e?"railroad"in e&&e.railroad?e.railroad:H(e)?e:{}:{},"extractRailroadOverrides"),fe=(0,d.K)(e=>{if(!e||H(e))return{};const a=e,{railroad:i,svgId:o,theme:n,look:t}=a;return ee(a,["railroad","svgId","theme","look"])},"extractThemeOverrides"),u=(0,d.K)((e,i)=>{if(typeof e!="string")return i;const o=e.trim();return me.test(o)?o:i},"sanitizeColorValue"),G=(0,d.K)((e,i)=>{if(typeof e!="string")return i;const o=e.trim();return he.test(o)?o:i},"sanitizeFontFamilyValue"),D=(0,d.K)((e,i)=>{const o=typeof e=="number"?e:typeof e=="string"?Number.parseFloat(e):Number.NaN;return Number.isFinite(o)&&o>=0?o:i},"sanitizeNumberValue"),ge=(0,d.K)(e=>{const i=typeof e=="number"?e:typeof e=="string"?Number.parseFloat(e):Number.NaN;return Number.isFinite(i)&&i>0?i:void 0},"parseThemeFontSize"),Te=(0,d.K)(e=>{var n,t,r,a,m,l,s,p,f,h,R,c,w;const i=G(e.fontFamily,k.fontFamily),o=(n=ge(e.fontSize))!=null?n:k.fontSize;return $(v({},k),{fontFamily:i,fontSize:o,terminalFill:u((t=e.secondBkg)!=null?t:e.secondaryColor,k.terminalFill),terminalStroke:u((r=e.secondaryBorderColor)!=null?r:e.lineColor,k.terminalStroke),terminalTextColor:u((a=e.secondaryTextColor)!=null?a:e.textColor,k.terminalTextColor),nonTerminalFill:u((m=e.mainBkg)!=null?m:e.background,k.nonTerminalFill),nonTerminalStroke:u((l=e.primaryBorderColor)!=null?l:e.lineColor,k.nonTerminalStroke),nonTerminalTextColor:u((s=e.primaryTextColor)!=null?s:e.textColor,k.nonTerminalTextColor),lineColor:u(e.lineColor,k.lineColor),markerFill:u(e.lineColor,k.markerFill),commentFill:u((p=e.labelBackground)!=null?p:e.tertiaryColor,k.commentFill),commentStroke:u((f=e.tertiaryBorderColor)!=null?f:e.lineColor,k.commentStroke),commentTextColor:u((h=e.tertiaryTextColor)!=null?h:e.textColor,k.commentTextColor),specialFill:u((R=e.tertiaryColor)!=null?R:e.secondaryColor,k.specialFill),specialStroke:u((c=e.tertiaryBorderColor)!=null?c:e.secondaryBorderColor,k.specialStroke),ruleNameColor:u((w=e.titleColor)!=null?w:e.textColor,k.ruleNameColor)})},"buildThemeDefaults"),L=(0,d.K)(e=>{var r,a,m,l;const i=(0,y.zj)(),o=v(v(v({},(0,y.P$)()),(r=i.themeVariables)!=null?r:{}),fe(e)),n=Te(o),t=v(v({},(a=i.railroad)!=null?a:{}),ue(e));return{compactMode:(m=t.compactMode)!=null?m:n.compactMode,padding:D(t.padding,n.padding),verticalSeparation:D(t.verticalSeparation,n.verticalSeparation),horizontalSeparation:D(t.horizontalSeparation,n.horizontalSeparation),arcRadius:D(t.arcRadius,n.arcRadius),fontSize:D(t.fontSize,n.fontSize),fontFamily:G(t.fontFamily,n.fontFamily),terminalFill:u(t.terminalFill,n.terminalFill),terminalStroke:u(t.terminalStroke,n.terminalStroke),terminalTextColor:u(t.terminalTextColor,n.terminalTextColor),nonTerminalFill:u(t.nonTerminalFill,n.nonTerminalFill),nonTerminalStroke:u(t.nonTerminalStroke,n.nonTerminalStroke),nonTerminalTextColor:u(t.nonTerminalTextColor,n.nonTerminalTextColor),lineColor:u(t.lineColor,n.lineColor),strokeWidth:D(t.strokeWidth,n.strokeWidth),markerFill:u(t.markerFill,n.markerFill),commentFill:u(t.commentFill,n.commentFill),commentStroke:u(t.commentStroke,n.commentStroke),commentTextColor:u(t.commentTextColor,n.commentTextColor),specialFill:u(t.specialFill,n.specialFill),specialStroke:u(t.specialStroke,n.specialStroke),ruleNameColor:u(t.ruleNameColor,n.ruleNameColor),showMarkers:(l=t.showMarkers)!=null?l:n.showMarkers,markerRadius:D(t.markerRadius,n.markerRadius)}},"buildRailroadStyleOptions"),xe=(0,d.K)(e=>{const{fontFamily:i,fontSize:o,terminalFill:n,terminalStroke:t,terminalTextColor:r,nonTerminalFill:a,nonTerminalStroke:m,nonTerminalTextColor:l,lineColor:s,strokeWidth:p,markerFill:f,commentFill:h,commentStroke:R,commentTextColor:c,specialFill:w,specialStroke:W,ruleNameColor:M}=L(e);return`
  .railroad-diagram {
    font-family: ${i};
    font-size: ${o}px;
  }

  .railroad-terminal rect {
    fill: ${n};
    stroke: ${t};
    stroke-width: ${p}px;
  }

  .railroad-terminal text {
    fill: ${r};
    font-family: ${i};
    font-size: ${o}px;
    text-anchor: middle;
    dominant-baseline: middle;
  }

  .railroad-nonterminal rect {
    fill: ${a};
    stroke: ${m};
    stroke-width: ${p}px;
  }

  .railroad-nonterminal text {
    fill: ${l};
    font-family: ${i};
    font-size: ${o}px;
    text-anchor: middle;
    dominant-baseline: middle;
  }

  .railroad-line {
    stroke: ${s};
    stroke-width: ${p}px;
    fill: none;
  }

  .railroad-start circle,
  .railroad-end circle {
    fill: ${f};
  }

  .railroad-comment ellipse {
    fill: ${h};
    stroke: ${R};
    stroke-width: ${p}px;
  }

  .railroad-comment text {
    fill: ${c};
    font-style: italic;
    font-family: ${i};
    font-size: ${o}px;
    text-anchor: middle;
    dominant-baseline: middle;
  }

  .railroad-special rect {
    fill: ${w};
    stroke: ${W};
    stroke-width: ${p}px;
    stroke-dasharray: 5,3;
  }

  .railroad-special text {
    fill: ${l};
    font-family: ${i};
    font-size: ${o}px;
    text-anchor: middle;
    dominant-baseline: middle;
  }

  .railroad-rule-name {
    font-weight: bold;
    fill: ${M};
    font-family: ${i};
    font-size: ${o}px;
  }

  .railroad-group {
    /* Grouping container, no specific styles */
  }
`},"getStyles"),F=(N=class{constructor(){this.d=""}moveTo(i,o){return this.d+=`M ${i} ${o} `,this}lineTo(i,o){return this.d+=`L ${i} ${o} `,this}horizontalTo(i){return this.d+=`H ${i} `,this}verticalTo(i){return this.d+=`V ${i} `,this}arcTo(i,o,n,t,r,a,m){return this.d+=`A ${i} ${o} ${n} ${t?1:0} ${r?1:0} ${a} ${m} `,this}build(){return this.d.trim()}},(0,d.K)(N,"PathBuilder"),N),we=(b=class{constructor(i,o=L()){this.textCache=new Map,this.svg=i,this.config=o}measureText(i){if(this.textCache.has(i))return this.textCache.get(i);const o=this.svg.append("text").attr("font-family",this.config.fontFamily).attr("font-size",this.config.fontSize).text(i),n=o.node().getBBox(),t={width:n.width,height:n.height};return o.remove(),this.textCache.set(i,t),t}renderTerminal(i,o){const n=this.measureText(o),t=n.width+this.config.padding*2,r=n.height+this.config.padding*2,a=i.append("g").attr("class","railroad-terminal");return a.append("rect").attr("x",0).attr("y",0).attr("width",t).attr("height",r).attr("rx",10).attr("ry",10),a.append("text").attr("x",t/2).attr("y",r/2).text(o),{element:a.node(),dimensions:{width:t,height:r,up:r/2,down:r/2}}}renderNonTerminal(i,o){const n=this.measureText(o),t=n.width+this.config.padding*2,r=n.height+this.config.padding*2,a=i.append("g").attr("class","railroad-nonterminal");return a.append("rect").attr("x",0).attr("y",0).attr("width",t).attr("height",r),a.append("text").attr("x",t/2).attr("y",r/2).text(o),{element:a.node(),dimensions:{width:t,height:r,up:r/2,down:r/2}}}renderSequence(i,o){const n=o.map(s=>this.renderExpression(i,s));let t=0,r=0,a=0;for(const s of n)t+=s.dimensions.width,r=Math.max(r,s.dimensions.up),a=Math.max(a,s.dimensions.down);t+=(n.length-1)*this.config.horizontalSeparation;const m=i.append("g").attr("class","railroad-sequence");let l=0;for(let s=0;s<n.length;s++){const p=n[s],f=r-p.dimensions.up;if(m.node().appendChild(p.element).setAttribute("transform",`translate(${l}, ${f})`),s<n.length-1){const R=l+p.dimensions.width,c=R+this.config.horizontalSeparation,w=r;m.append("path").attr("class","railroad-line").attr("d",new F().moveTo(R,w).lineTo(c,w).build())}l+=p.dimensions.width+this.config.horizontalSeparation}return{element:m.node(),dimensions:{width:t,height:r+a,up:r,down:a}}}renderChoice(i,o){const n=o.map(h=>this.renderExpression(i,h));let t=0,r=0;for(const h of n)t=Math.max(t,h.dimensions.width),r+=h.dimensions.height;r+=(n.length-1)*this.config.verticalSeparation;const a=this.config.arcRadius,m=a*4,l=t+m,s=i.append("g").attr("class","railroad-choice");let p=0;const f=r/2;for(const h of n){const R=p,c=R+h.dimensions.up,w=a*2+(t-h.dimensions.width)/2;s.node().appendChild(h.element).setAttribute("transform",`translate(${w}, ${R})`);const M=new F,z=c>f;c===f?M.moveTo(0,f).lineTo(w,c):M.moveTo(0,f).arcTo(a,a,0,!1,z,a,f+(z?a:-a)).lineTo(a,c-(z?a:-a)).arcTo(a,a,0,!1,!z,a*2,c).lineTo(w,c),s.append("path").attr("class","railroad-line").attr("d",M.build());const I=new F,J=w+h.dimensions.width,ve=l-a*2;c===f?I.moveTo(J,c).lineTo(l,f):I.moveTo(J,c).lineTo(ve,c).arcTo(a,a,0,!1,!z,l-a,c+(z?-a:a)).lineTo(l-a,f+(z?a:-a)).arcTo(a,a,0,!1,z,l,f),s.append("path").attr("class","railroad-line").attr("d",I.build()),p+=h.dimensions.height+this.config.verticalSeparation}return{element:s.node(),dimensions:{width:l,height:r,up:f,down:r-f}}}renderOptional(i,o){const n=this.renderExpression(i,o),t=this.config.arcRadius,r=t*2,a=n.dimensions.width+t*4,m=n.dimensions.height+r,l=i.append("g").attr("class","railroad-optional"),s=t*2,p=r;l.node().appendChild(n.element).setAttribute("transform",`translate(${s}, ${p})`);const h=p+n.dimensions.up,R=new F().moveTo(0,h).lineTo(t*2,h);l.append("path").attr("class","railroad-line").attr("d",R.build());const c=new F().moveTo(s+n.dimensions.width,h).lineTo(a,h);l.append("path").attr("class","railroad-line").attr("d",c.build());const w=new F().moveTo(0,h).arcTo(t,t,0,!1,!1,t,h-t).lineTo(t,t).arcTo(t,t,0,!1,!0,t*2,0).lineTo(a-t*2,0).arcTo(t,t,0,!1,!0,a-t,t).lineTo(a-t,h-t).arcTo(t,t,0,!1,!1,a,h);return l.append("path").attr("class","railroad-line").attr("d",w.build()),{element:l.node(),dimensions:{width:a,height:m,up:h,down:m-h}}}renderRepetition(i,o,n){const t=this.renderExpression(i,o),r=this.config.arcRadius,a=r*2,m=t.dimensions.width+r*4,l=n===0,s=t.dimensions.height+a+(l?a:0),p=i.append("g").attr("class","railroad-repetition"),f=r*2,h=l?a:0;p.node().appendChild(t.element).setAttribute("transform",`translate(${f}, ${h})`);const c=h+t.dimensions.up;p.append("path").attr("class","railroad-line").attr("d",new F().moveTo(0,c).lineTo(r*2,c).build()),p.append("path").attr("class","railroad-line").attr("d",new F().moveTo(f+t.dimensions.width,c).lineTo(m,c).build());const w=h+t.dimensions.height+r,W=new F().moveTo(f+t.dimensions.width,c).arcTo(r,r,0,!1,!0,f+t.dimensions.width+r,c+r).lineTo(f+t.dimensions.width+r,w).arcTo(r,r,0,!1,!0,f+t.dimensions.width,w+r).lineTo(r*2,w+r).arcTo(r,r,0,!1,!0,r,w).lineTo(r,c+r).arcTo(r,r,0,!1,!0,r*2,c);if(p.append("path").attr("class","railroad-line").attr("d",W.build()),l){const M=new F().moveTo(0,c).arcTo(r,r,0,!1,!1,r,c-r).lineTo(r,r).arcTo(r,r,0,!1,!0,r*2,0).lineTo(m-r*2,0).arcTo(r,r,0,!1,!0,m-r,r).lineTo(m-r,c-r).arcTo(r,r,0,!1,!1,m,c);p.append("path").attr("class","railroad-line").attr("d",M.build())}return{element:p.node(),dimensions:{width:m,height:s,up:c,down:s-c}}}renderSpecial(i,o){const n=this.measureText("? "+o+" ?"),t=n.width+this.config.padding*2,r=n.height+this.config.padding*2,a=i.append("g").attr("class","railroad-special");return a.append("rect").attr("x",0).attr("y",0).attr("width",t).attr("height",r),a.append("text").attr("x",t/2).attr("y",r/2).text("? "+o+" ?"),{element:a.node(),dimensions:{width:t,height:r,up:r/2,down:r/2}}}renderExpression(i,o){switch(o.type){case"terminal":return this.renderTerminal(i,o.value);case"nonterminal":return this.renderNonTerminal(i,o.name);case"sequence":return this.renderSequence(i,o.elements);case"choice":return this.renderChoice(i,o.alternatives);case"optional":return this.renderOptional(i,o.element);case"repetition":return this.renderRepetition(i,o.element,o.min);case"special":return this.renderSpecial(i,o.text);default:throw new Error(`Unknown node type: ${o.type}`)}}renderRule(i,o){const n=this.svg.append("g").attr("class","railroad-rule").attr("transform",`translate(0, ${o})`),t=i.name+" =",r=this.measureText(t).width+20,a=r+20,m=n.append("g"),l=this.renderExpression(m,i.definition),s=Math.max(20,l.dimensions.up),p=s-l.dimensions.up;return m.attr("transform",`translate(${a}, ${p})`),n.append("g").attr("class","railroad-rule-name-group").append("text").attr("class","railroad-rule-name").attr("x",0).attr("y",s).text(t),n.append("g").attr("class","railroad-start").append("circle").attr("cx",r).attr("cy",s).attr("r",this.config.markerRadius),n.append("g").attr("class","railroad-end").append("circle").attr("cx",a+l.dimensions.width+10).attr("cy",s).attr("r",this.config.markerRadius),n.append("path").attr("class","railroad-line").attr("d",new F().moveTo(r+this.config.markerRadius,s).lineTo(a,s).build()),n.append("path").attr("class","railroad-line").attr("d",new F().moveTo(a+l.dimensions.width,s).lineTo(a+l.dimensions.width+10-this.config.markerRadius,s).build()),{height:Math.max(40,p+l.dimensions.height+this.config.padding*2),width:a+l.dimensions.width+10+this.config.markerRadius}}renderDiagram(i){let o=this.config.padding,n=0;for(const t of i){const r=this.renderRule(t,o);o+=r.height+this.config.verticalSeparation,n=Math.max(n,r.width)}return{width:n+this.config.padding*2,height:o+this.config.padding}}},(0,d.K)(b,"RailroadRenderer"),b),Z=(0,d.K)((e,i,o)=>{(0,y.a$)(e,i.height,i.width,o),e.attr("viewBox",`0 0 ${i.width} ${i.height}`)},"configureRailroadSvgSize"),Ce=(0,d.K)((e,i,o)=>{var n;C.R.debug(`[Railroad] Rendering diagram
`+e);try{const t=(0,S.D)(i);t.attr("class","railroad-diagram");const r=(0,y.zj)().railroad,a=(n=r==null?void 0:r.useMaxWidth)!=null?n:!0,m=X.getRules();if(C.R.debug(`[Railroad] Rendering ${m.length} rules`),m.length===0){C.R.warn("[Railroad] No rules to render"),Z(t,{height:100,width:200},a);return}const s=new we(t,L()).renderDiagram(m);Z(t,s,a),C.R.debug("[Railroad] Render complete")}catch(t){throw C.R.error("[Railroad] Render error:",t),t}},"draw"),ke={draw:Ce}}}]);
}());