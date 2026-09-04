!(function(){"use strict";var ce=(_t,tt,D)=>new Promise((et,A)=>{var V=_=>{try{B(D.next(_))}catch(E){A(E)}},j=_=>{try{B(D.throw(_))}catch(E){A(E)}},B=_=>_.done?et(_.value):Promise.resolve(_.value).then(V,j);B((D=D.apply(_t,tt)).next())});(self.webpackChunkfenix_dashboard_v3=self.webpackChunkfenix_dashboard_v3||[]).push([[3230],{338:function(_t,tt,D){D.d(tt,{CP:function(){return Y},Ck:function(){return dt},HT:function(){return H},PB:function(){return J},aC:function(){return l},lC:function(){return _},m:function(){return E},tk:function(){return B}});var et=D(76385),A=D(86827),V=D(16750),j=D(12300),B=(0,A.K)((L,S)=>{const v=L.append("rect");if(v.attr("x",S.x),v.attr("y",S.y),v.attr("fill",S.fill),v.attr("stroke",S.stroke),v.attr("width",S.width),v.attr("height",S.height),S.name&&v.attr("name",S.name),S.rx&&v.attr("rx",S.rx),S.ry&&v.attr("ry",S.ry),S.attrs!==void 0)for(const x in S.attrs)v.attr(x,S.attrs[x]);return S.class&&v.attr("class",S.class),v},"drawRect"),_=(0,A.K)((L,S)=>{const v={x:S.startx,y:S.starty,width:S.stopx-S.startx,height:S.stopy-S.starty,fill:S.fill,stroke:S.stroke,class:"rect"};B(L,v).lower()},"drawBackgroundRect"),E=(0,A.K)((L,S)=>{const v=S.text.replace(et.H1," "),x=L.append("text");x.attr("x",S.x),x.attr("y",S.y),x.attr("class","legend"),x.style("text-anchor",S.anchor),S.class&&x.attr("class",S.class);const O=x.append("tspan");return O.attr("x",S.x+S.textMargin*2),O.text(v),x},"drawText"),l=(0,A.K)((L,S,v,x)=>{const O=L.append("image");O.attr("x",S),O.attr("y",v);const ot=(0,V.J)(x);O.attr("xlink:href",ot)},"drawImage"),Y=(0,A.K)((L,S,v,x)=>{const O=L.append("use");O.attr("x",S),O.attr("y",v);const ot=(0,V.J)(x);O.attr("xlink:href",`#${ot}`)},"drawEmbeddedImage"),J=(0,A.K)(()=>({x:0,y:0,width:100,height:100,fill:"#EDF2AE",stroke:"#666",anchor:"start",rx:0,ry:0}),"getNoteRect"),H=(0,A.K)(()=>({x:0,y:0,width:100,height:100,"text-anchor":"start",style:"#666",textMargin:0,rx:0,ry:0,tspan:!0}),"getTextObj"),dt=(0,A.K)(()=>{let L=(0,j.Ltv)(".mermaidTooltip");return L.empty()&&(L=(0,j.Ltv)("body").append("div").attr("class","mermaidTooltip").style("opacity",0).style("position","absolute").style("text-align","center").style("max-width","200px").style("padding","2px").style("font-size","12px").style("background","#ffffde").style("border","1px solid #333").style("border-radius","2px").style("pointer-events","none").style("z-index","100")),L},"createTooltip")},13230:function(_t,tt,D){var lt;D.d(tt,{Zk:function(){return dt},q7:function(){return Oe},tM:function(){return $e},u4:function(){return Pe}});var et=D(96755),A=D(1672),V=D(10561),j=D(338),B=D(16459),_=D(76385),E=D(31293),l=D(86827),Y=D(12300),J=D(99418),H=function(){var t=(0,l.K)(function(at,c,d,a){for(d=d||{},a=at.length;a--;d[at[a]]=c);return d},"o"),e=[1,2],s=[1,3],n=[1,4],i=[2,4],o=[1,9],u=[1,11],p=[1,16],f=[1,17],T=[1,18],b=[1,19],C=[1,33],z=[1,20],Z=[1,21],U=[1,22],N=[1,23],I=[1,24],y=[1,26],$=[1,27],w=[1,28],Q=[1,29],M=[1,30],q=[1,31],X=[1,32],F=[1,35],ft=[1,36],ct=[1,37],xt=[1,38],pt=[1,34],g=[1,4,5,16,17,19,21,22,24,25,26,27,28,29,33,35,37,38,41,45,48,51,52,53,54,57],Ct=[1,4,5,14,15,16,17,19,21,22,24,25,26,27,28,29,33,35,37,38,39,40,41,45,48,51,52,53,54,57],ae=[4,5,16,17,19,21,22,24,25,26,27,28,29,33,35,37,38,41,45,48,51,52,53,54,57],$t={trace:(0,l.K)(function(){},"trace"),yy:{},symbols_:{error:2,start:3,SPACE:4,NL:5,SD:6,document:7,line:8,statement:9,classDefStatement:10,styleStatement:11,cssClassStatement:12,idStatement:13,DESCR:14,"-->":15,HIDE_EMPTY:16,scale:17,WIDTH:18,COMPOSIT_STATE:19,STRUCT_START:20,STRUCT_STOP:21,STATE_DESCR:22,AS:23,ID:24,FORK:25,JOIN:26,CHOICE:27,CONCURRENT:28,note:29,notePosition:30,NOTE_TEXT:31,direction:32,acc_title:33,acc_title_value:34,acc_descr:35,acc_descr_value:36,acc_descr_multiline_value:37,CLICK:38,STRING:39,HREF:40,classDef:41,CLASSDEF_ID:42,CLASSDEF_STYLEOPTS:43,DEFAULT:44,style:45,STYLE_IDS:46,STYLEDEF_STYLEOPTS:47,class:48,CLASSENTITY_IDS:49,STYLECLASS:50,direction_tb:51,direction_bt:52,direction_rl:53,direction_lr:54,eol:55,";":56,EDGE_STATE:57,STYLE_SEPARATOR:58,left_of:59,right_of:60,$accept:0,$end:1},terminals_:{2:"error",4:"SPACE",5:"NL",6:"SD",14:"DESCR",15:"-->",16:"HIDE_EMPTY",17:"scale",18:"WIDTH",19:"COMPOSIT_STATE",20:"STRUCT_START",21:"STRUCT_STOP",22:"STATE_DESCR",23:"AS",24:"ID",25:"FORK",26:"JOIN",27:"CHOICE",28:"CONCURRENT",29:"note",31:"NOTE_TEXT",33:"acc_title",34:"acc_title_value",35:"acc_descr",36:"acc_descr_value",37:"acc_descr_multiline_value",38:"CLICK",39:"STRING",40:"HREF",41:"classDef",42:"CLASSDEF_ID",43:"CLASSDEF_STYLEOPTS",44:"DEFAULT",45:"style",46:"STYLE_IDS",47:"STYLEDEF_STYLEOPTS",48:"class",49:"CLASSENTITY_IDS",50:"STYLECLASS",51:"direction_tb",52:"direction_bt",53:"direction_rl",54:"direction_lr",56:";",57:"EDGE_STATE",58:"STYLE_SEPARATOR",59:"left_of",60:"right_of"},productions_:[0,[3,2],[3,2],[3,2],[7,0],[7,2],[8,2],[8,1],[8,1],[9,1],[9,1],[9,1],[9,1],[9,2],[9,3],[9,4],[9,1],[9,2],[9,1],[9,4],[9,3],[9,6],[9,1],[9,1],[9,1],[9,1],[9,4],[9,4],[9,1],[9,2],[9,2],[9,1],[9,5],[9,5],[10,3],[10,3],[11,3],[12,3],[32,1],[32,1],[32,1],[32,1],[55,1],[55,1],[13,1],[13,1],[13,3],[13,3],[30,1],[30,1]],performAction:(0,l.K)(function(c,d,a,m,k,r,yt){var h=r.length-1;switch(k){case 3:return m.setRootDoc(r[h]),r[h];case 4:this.$=[];break;case 5:r[h]!="nl"&&(r[h-1].push(r[h]),this.$=r[h-1]);break;case 6:case 7:this.$=r[h];break;case 8:this.$="nl";break;case 12:this.$=r[h];break;case 13:const Lt=r[h-1];Lt.description=m.trimColon(r[h]),this.$=Lt;break;case 14:this.$={stmt:"relation",state1:r[h-2],state2:r[h]};break;case 15:const Rt=m.trimColon(r[h]);this.$={stmt:"relation",state1:r[h-3],state2:r[h-1],description:Rt};break;case 19:this.$={stmt:"state",id:r[h-3],type:"default",description:"",doc:r[h-1]};break;case 20:var st=r[h],it=r[h-2].trim();if(r[h].match(":")){var Dt=r[h].split(":");st=Dt[0],it=[it,Dt[1]]}this.$={stmt:"state",id:st,type:"default",description:it};break;case 21:this.$={stmt:"state",id:r[h-3],type:"default",description:r[h-5],doc:r[h-1]};break;case 22:this.$={stmt:"state",id:r[h],type:"fork"};break;case 23:this.$={stmt:"state",id:r[h],type:"join"};break;case 24:this.$={stmt:"state",id:r[h],type:"choice"};break;case 25:this.$={stmt:"state",id:m.getDividerId(),type:"divider"};break;case 26:this.$={stmt:"state",id:r[h-1].trim(),note:{position:r[h-2].trim(),text:r[h].trim()}};break;case 29:this.$=r[h].trim(),m.setAccTitle(this.$);break;case 30:case 31:this.$=r[h].trim(),m.setAccDescription(this.$);break;case 32:this.$={stmt:"click",id:r[h-3],url:r[h-2],tooltip:r[h-1]};break;case 33:this.$={stmt:"click",id:r[h-3],url:r[h-1],tooltip:""};break;case 34:case 35:this.$={stmt:"classDef",id:r[h-1].trim(),classes:r[h].trim()};break;case 36:this.$={stmt:"style",id:r[h-1].trim(),styleClass:r[h].trim()};break;case 37:this.$={stmt:"applyClass",id:r[h-1].trim(),styleClass:r[h].trim()};break;case 38:m.setDirection("TB"),this.$={stmt:"dir",value:"TB"};break;case 39:m.setDirection("BT"),this.$={stmt:"dir",value:"BT"};break;case 40:m.setDirection("RL"),this.$={stmt:"dir",value:"RL"};break;case 41:m.setDirection("LR"),this.$={stmt:"dir",value:"LR"};break;case 44:case 45:this.$={stmt:"state",id:r[h].trim(),type:"default",description:""};break;case 46:this.$={stmt:"state",id:r[h-2].trim(),classes:[r[h].trim()],type:"default",description:""};break;case 47:this.$={stmt:"state",id:r[h-2].trim(),classes:[r[h].trim()],type:"default",description:""};break}},"anonymous"),table:[{3:1,4:e,5:s,6:n},{1:[3]},{3:5,4:e,5:s,6:n},{3:6,4:e,5:s,6:n},t([1,4,5,16,17,19,22,24,25,26,27,28,29,33,35,37,38,41,45,48,51,52,53,54,57],i,{7:7}),{1:[2,1]},{1:[2,2]},{1:[2,3],4:o,5:u,8:8,9:10,10:12,11:13,12:14,13:15,16:p,17:f,19:T,22:b,24:C,25:z,26:Z,27:U,28:N,29:I,32:25,33:y,35:$,37:w,38:Q,41:M,45:q,48:X,51:F,52:ft,53:ct,54:xt,57:pt},t(g,[2,5]),{9:39,10:12,11:13,12:14,13:15,16:p,17:f,19:T,22:b,24:C,25:z,26:Z,27:U,28:N,29:I,32:25,33:y,35:$,37:w,38:Q,41:M,45:q,48:X,51:F,52:ft,53:ct,54:xt,57:pt},t(g,[2,7]),t(g,[2,8]),t(g,[2,9]),t(g,[2,10]),t(g,[2,11]),t(g,[2,12],{14:[1,40],15:[1,41]}),t(g,[2,16]),{18:[1,42]},t(g,[2,18],{20:[1,43]}),{23:[1,44]},t(g,[2,22]),t(g,[2,23]),t(g,[2,24]),t(g,[2,25]),{30:45,31:[1,46],59:[1,47],60:[1,48]},t(g,[2,28]),{34:[1,49]},{36:[1,50]},t(g,[2,31]),{13:51,24:C,57:pt},{42:[1,52],44:[1,53]},{46:[1,54]},{49:[1,55]},t(Ct,[2,44],{58:[1,56]}),t(Ct,[2,45],{58:[1,57]}),t(g,[2,38]),t(g,[2,39]),t(g,[2,40]),t(g,[2,41]),t(g,[2,6]),t(g,[2,13]),{13:58,24:C,57:pt},t(g,[2,17]),t(ae,i,{7:59}),{24:[1,60]},{24:[1,61]},{23:[1,62]},{24:[2,48]},{24:[2,49]},t(g,[2,29]),t(g,[2,30]),{39:[1,63],40:[1,64]},{43:[1,65]},{43:[1,66]},{47:[1,67]},{50:[1,68]},{24:[1,69]},{24:[1,70]},t(g,[2,14],{14:[1,71]}),{4:o,5:u,8:8,9:10,10:12,11:13,12:14,13:15,16:p,17:f,19:T,21:[1,72],22:b,24:C,25:z,26:Z,27:U,28:N,29:I,32:25,33:y,35:$,37:w,38:Q,41:M,45:q,48:X,51:F,52:ft,53:ct,54:xt,57:pt},t(g,[2,20],{20:[1,73]}),{31:[1,74]},{24:[1,75]},{39:[1,76]},{39:[1,77]},t(g,[2,34]),t(g,[2,35]),t(g,[2,36]),t(g,[2,37]),t(Ct,[2,46]),t(Ct,[2,47]),t(g,[2,15]),t(g,[2,19]),t(ae,i,{7:78}),t(g,[2,26]),t(g,[2,27]),{5:[1,79]},{5:[1,80]},{4:o,5:u,8:8,9:10,10:12,11:13,12:14,13:15,16:p,17:f,19:T,21:[1,81],22:b,24:C,25:z,26:Z,27:U,28:N,29:I,32:25,33:y,35:$,37:w,38:Q,41:M,45:q,48:X,51:F,52:ft,53:ct,54:xt,57:pt},t(g,[2,32]),t(g,[2,33]),t(g,[2,21])],defaultActions:{5:[2,1],6:[2,2],47:[2,48],48:[2,49]},parseError:(0,l.K)(function(c,d){if(d.recoverable)this.trace(c);else{var a=new Error(c);throw a.hash=d,a}},"parseError"),parse:(0,l.K)(function(c){var d=this,a=[0],m=[],k=[null],r=[],yt=this.table,h="",st=0,it=0,Dt=0,Lt=2,Rt=1,Be=r.slice.call(arguments,1),R=Object.create(this.lexer),ht={yy:{}};for(var Kt in this.yy)Object.prototype.hasOwnProperty.call(this.yy,Kt)&&(ht.yy[Kt]=this.yy[Kt]);R.setInput(c,ht.yy),ht.yy.lexer=R,ht.yy.parser=this,typeof R.yylloc=="undefined"&&(R.yylloc={});var Bt=R.yylloc;r.push(Bt);var Ye=R.options&&R.options.ranges;typeof ht.yy.parseError=="function"?this.parseError=ht.yy.parseError:this.parseError=Object.getPrototypeOf(this).parseError;function Me(G){a.length=a.length-2*G,k.length=k.length-G,r.length=r.length-G}(0,l.K)(Me,"popStack");function oe(){var G;return G=m.pop()||R.lex()||Rt,typeof G!="number"&&(G instanceof Array&&(m=G,G=m.pop()),G=d.symbols_[G]||G),G}(0,l.K)(oe,"lex");for(var K,Yt,ut,W,Fe,Mt,St={},Ot,rt,le,It;;){if(ut=a[a.length-1],this.defaultActions[ut]?W=this.defaultActions[ut]:((K===null||typeof K=="undefined")&&(K=oe()),W=yt[ut]&&yt[ut][K]),typeof W=="undefined"||!W.length||!W[0]){var Ft="";It=[];for(Ot in yt[ut])this.terminals_[Ot]&&Ot>Lt&&It.push("'"+this.terminals_[Ot]+"'");R.showPosition?Ft="Parse error on line "+(st+1)+`:
`+R.showPosition()+`
Expecting `+It.join(", ")+", got '"+(this.terminals_[K]||K)+"'":Ft="Parse error on line "+(st+1)+": Unexpected "+(K==Rt?"end of input":"'"+(this.terminals_[K]||K)+"'"),this.parseError(Ft,{text:R.match,token:this.terminals_[K]||K,line:R.yylineno,loc:Bt,expected:It})}if(W[0]instanceof Array&&W.length>1)throw new Error("Parse Error: multiple actions possible at state: "+ut+", token: "+K);switch(W[0]){case 1:a.push(K),k.push(R.yytext),r.push(R.yylloc),a.push(W[1]),K=null,Yt?(K=Yt,Yt=null):(it=R.yyleng,h=R.yytext,st=R.yylineno,Bt=R.yylloc,Dt>0&&Dt--);break;case 2:if(rt=this.productions_[W[1]][1],St.$=k[k.length-rt],St._$={first_line:r[r.length-(rt||1)].first_line,last_line:r[r.length-1].last_line,first_column:r[r.length-(rt||1)].first_column,last_column:r[r.length-1].last_column},Ye&&(St._$.range=[r[r.length-(rt||1)].range[0],r[r.length-1].range[1]]),Mt=this.performAction.apply(St,[h,it,st,ht.yy,W[1],k,r].concat(Be)),typeof Mt!="undefined")return Mt;rt&&(a=a.slice(0,-1*rt*2),k=k.slice(0,-1*rt),r=r.slice(0,-1*rt)),a.push(this.productions_[W[1]][0]),k.push(St.$),r.push(St._$),le=yt[a[a.length-2]][a[a.length-1]],a.push(le);break;case 3:return!0}}return!0},"parse")},Ke=function(){var at={EOF:1,parseError:(0,l.K)(function(d,a){if(this.yy.parser)this.yy.parser.parseError(d,a);else throw new Error(d)},"parseError"),setInput:(0,l.K)(function(c,d){return this.yy=d||this.yy||{},this._input=c,this._more=this._backtrack=this.done=!1,this.yylineno=this.yyleng=0,this.yytext=this.matched=this.match="",this.conditionStack=["INITIAL"],this.yylloc={first_line:1,first_column:0,last_line:1,last_column:0},this.options.ranges&&(this.yylloc.range=[0,0]),this.offset=0,this},"setInput"),input:(0,l.K)(function(){var c=this._input[0];this.yytext+=c,this.yyleng++,this.offset++,this.match+=c,this.matched+=c;var d=c.match(/(?:\r\n?|\n).*/g);return d?(this.yylineno++,this.yylloc.last_line++):this.yylloc.last_column++,this.options.ranges&&this.yylloc.range[1]++,this._input=this._input.slice(1),c},"input"),unput:(0,l.K)(function(c){var d=c.length,a=c.split(/(?:\r\n?|\n)/g);this._input=c+this._input,this.yytext=this.yytext.substr(0,this.yytext.length-d),this.offset-=d;var m=this.match.split(/(?:\r\n?|\n)/g);this.match=this.match.substr(0,this.match.length-1),this.matched=this.matched.substr(0,this.matched.length-1),a.length-1&&(this.yylineno-=a.length-1);var k=this.yylloc.range;return this.yylloc={first_line:this.yylloc.first_line,last_line:this.yylineno+1,first_column:this.yylloc.first_column,last_column:a?(a.length===m.length?this.yylloc.first_column:0)+m[m.length-a.length].length-a[0].length:this.yylloc.first_column-d},this.options.ranges&&(this.yylloc.range=[k[0],k[0]+this.yyleng-d]),this.yyleng=this.yytext.length,this},"unput"),more:(0,l.K)(function(){return this._more=!0,this},"more"),reject:(0,l.K)(function(){if(this.options.backtrack_lexer)this._backtrack=!0;else return this.parseError("Lexical error on line "+(this.yylineno+1)+`. You can only invoke reject() in the lexer when the lexer is of the backtracking persuasion (options.backtrack_lexer = true).
`+this.showPosition(),{text:"",token:null,line:this.yylineno});return this},"reject"),less:(0,l.K)(function(c){this.unput(this.match.slice(c))},"less"),pastInput:(0,l.K)(function(){var c=this.matched.substr(0,this.matched.length-this.match.length);return(c.length>20?"...":"")+c.substr(-20).replace(/\n/g,"")},"pastInput"),upcomingInput:(0,l.K)(function(){var c=this.match;return c.length<20&&(c+=this._input.substr(0,20-c.length)),(c.substr(0,20)+(c.length>20?"...":"")).replace(/\n/g,"")},"upcomingInput"),showPosition:(0,l.K)(function(){var c=this.pastInput(),d=new Array(c.length+1).join("-");return c+this.upcomingInput()+`
`+d+"^"},"showPosition"),test_match:(0,l.K)(function(c,d){var a,m,k;if(this.options.backtrack_lexer&&(k={yylineno:this.yylineno,yylloc:{first_line:this.yylloc.first_line,last_line:this.last_line,first_column:this.yylloc.first_column,last_column:this.yylloc.last_column},yytext:this.yytext,match:this.match,matches:this.matches,matched:this.matched,yyleng:this.yyleng,offset:this.offset,_more:this._more,_input:this._input,yy:this.yy,conditionStack:this.conditionStack.slice(0),done:this.done},this.options.ranges&&(k.yylloc.range=this.yylloc.range.slice(0))),m=c[0].match(/(?:\r\n?|\n).*/g),m&&(this.yylineno+=m.length),this.yylloc={first_line:this.yylloc.last_line,last_line:this.yylineno+1,first_column:this.yylloc.last_column,last_column:m?m[m.length-1].length-m[m.length-1].match(/\r?\n?/)[0].length:this.yylloc.last_column+c[0].length},this.yytext+=c[0],this.match+=c[0],this.matches=c,this.yyleng=this.yytext.length,this.options.ranges&&(this.yylloc.range=[this.offset,this.offset+=this.yyleng]),this._more=!1,this._backtrack=!1,this._input=this._input.slice(c[0].length),this.matched+=c[0],a=this.performAction.call(this,this.yy,this,d,this.conditionStack[this.conditionStack.length-1]),this.done&&this._input&&(this.done=!1),a)return a;if(this._backtrack){for(var r in k)this[r]=k[r];return!1}return!1},"test_match"),next:(0,l.K)(function(){if(this.done)return this.EOF;this._input||(this.done=!0);var c,d,a,m;this._more||(this.yytext="",this.match="");for(var k=this._currentRules(),r=0;r<k.length;r++)if(a=this._input.match(this.rules[k[r]]),a&&(!d||a[0].length>d[0].length)){if(d=a,m=r,this.options.backtrack_lexer){if(c=this.test_match(a,k[r]),c!==!1)return c;if(this._backtrack){d=!1;continue}else return!1}else if(!this.options.flex)break}return d?(c=this.test_match(d,k[m]),c!==!1?c:!1):this._input===""?this.EOF:this.parseError("Lexical error on line "+(this.yylineno+1)+`. Unrecognized text.
`+this.showPosition(),{text:"",token:null,line:this.yylineno})},"next"),lex:(0,l.K)(function(){var d=this.next();return d||this.lex()},"lex"),begin:(0,l.K)(function(d){this.conditionStack.push(d)},"begin"),popState:(0,l.K)(function(){var d=this.conditionStack.length-1;return d>0?this.conditionStack.pop():this.conditionStack[0]},"popState"),_currentRules:(0,l.K)(function(){return this.conditionStack.length&&this.conditionStack[this.conditionStack.length-1]?this.conditions[this.conditionStack[this.conditionStack.length-1]].rules:this.conditions.INITIAL.rules},"_currentRules"),topState:(0,l.K)(function(d){return d=this.conditionStack.length-1-Math.abs(d||0),d>=0?this.conditionStack[d]:"INITIAL"},"topState"),pushState:(0,l.K)(function(d){this.begin(d)},"pushState"),stateStackSize:(0,l.K)(function(){return this.conditionStack.length},"stateStackSize"),options:{"case-insensitive":!0},performAction:(0,l.K)(function(d,a,m,k){function r(){const h=a.yytext.indexOf("%%");if(h===0)return!1;if(h>0){const st=a.yytext.slice(0,h),it=a.yytext.slice(h);it&&d.lexer.unput(it),a.yytext=st}return!0}(0,l.K)(r,"processId");var yt=k;switch(m){case 0:return 38;case 1:return 40;case 2:return 39;case 3:return 44;case 4:return 51;case 5:return 52;case 6:return 53;case 7:return 54;case 8:return 5;case 9:break;case 10:break;case 11:break;case 12:break;case 13:return this.pushState("SCALE"),17;case 14:return 18;case 15:this.popState();break;case 16:return this.begin("acc_title"),33;case 17:return this.popState(),"acc_title_value";case 18:return this.begin("acc_descr"),35;case 19:return this.popState(),"acc_descr_value";case 20:this.begin("acc_descr_multiline");break;case 21:this.popState();break;case 22:return"acc_descr_multiline_value";case 23:return this.pushState("CLASSDEF"),41;case 24:return this.popState(),this.pushState("CLASSDEFID"),"DEFAULT_CLASSDEF_ID";case 25:return this.popState(),this.pushState("CLASSDEFID"),42;case 26:return this.popState(),43;case 27:return this.pushState("CLASS"),48;case 28:return this.popState(),this.pushState("CLASS_STYLE"),49;case 29:return this.popState(),50;case 30:return this.pushState("STYLE"),45;case 31:return this.popState(),this.pushState("STYLEDEF_STYLES"),46;case 32:return this.popState(),47;case 33:return this.pushState("SCALE"),17;case 34:return 18;case 35:this.popState();break;case 36:this.pushState("STATE");break;case 37:return this.popState(),a.yytext=a.yytext.slice(0,-8).trim(),25;case 38:return this.popState(),a.yytext=a.yytext.slice(0,-8).trim(),26;case 39:return this.popState(),a.yytext=a.yytext.slice(0,-10).trim(),27;case 40:return this.popState(),a.yytext=a.yytext.slice(0,-8).trim(),25;case 41:return this.popState(),a.yytext=a.yytext.slice(0,-8).trim(),26;case 42:return this.popState(),a.yytext=a.yytext.slice(0,-10).trim(),27;case 43:return 51;case 44:return 52;case 45:return 53;case 46:return 54;case 47:this.pushState("STATE_STRING");break;case 48:return this.pushState("STATE_ID"),"AS";case 49:return r()?(this.popState(),"ID"):void 0;case 50:this.popState();break;case 51:return"STATE_DESCR";case 52:throw new Error('Error: State name must be a single word. Found: "'+a.yytext.trim()+'"');case 53:return 19;case 54:this.popState();break;case 55:return this.popState(),this.pushState("struct"),20;case 56:return this.popState(),21;case 57:break;case 58:return this.begin("NOTE"),29;case 59:return this.popState(),this.pushState("NOTE_ID"),59;case 60:return this.popState(),this.pushState("NOTE_ID"),60;case 61:this.popState(),this.pushState("FLOATING_NOTE");break;case 62:return this.popState(),this.pushState("FLOATING_NOTE_ID"),"AS";case 63:break;case 64:return"NOTE_TEXT";case 65:return r()?(this.popState(),"ID"):void 0;case 66:return r()?(this.popState(),this.pushState("NOTE_TEXT"),24):void 0;case 67:return this.popState(),a.yytext=a.yytext.substr(2).trim(),31;case 68:return this.popState(),a.yytext=a.yytext.slice(0,-8).trim(),31;case 69:return 6;case 70:return 6;case 71:return 16;case 72:return 57;case 73:return r()?24:void 0;case 74:return a.yytext=a.yytext.trim(),14;case 75:return 15;case 76:return 28;case 77:return 58;case 78:return 5;case 79:return"INVALID"}},"anonymous"),rules:[/^(?:click\b)/i,/^(?:href\b)/i,/^(?:"[^"]*")/i,/^(?:default\b)/i,/^(?:.*direction\s+TB[^\n]*)/i,/^(?:.*direction\s+BT[^\n]*)/i,/^(?:.*direction\s+RL[^\n]*)/i,/^(?:.*direction\s+LR[^\n]*)/i,/^(?:[\n]+)/i,/^(?:[\s]+)/i,/^(?:((?!\n)\s)+)/i,/^(?:#[^\n]*)/i,/^(?:%%(?!\{)[^\n]*)/i,/^(?:scale\s+)/i,/^(?:\d+)/i,/^(?:\s+width\b)/i,/^(?:accTitle\s*:\s*)/i,/^(?:(?!\n||)*[^\n]*)/i,/^(?:accDescr\s*:\s*)/i,/^(?:(?!\n||)*[^\n]*)/i,/^(?:accDescr\s*\{\s*)/i,/^(?:[\}])/i,/^(?:[^\}]*)/i,/^(?:classDef\s+)/i,/^(?:DEFAULT\s+)/i,/^(?:\w+\s+)/i,/^(?:[^\n]*)/i,/^(?:class\s+)/i,/^(?:(\w+)+((,\s*\w+)*))/i,/^(?:[^\n]*)/i,/^(?:style\s+)/i,/^(?:[\w,]+\s+)/i,/^(?:[^\n]*)/i,/^(?:scale\s+)/i,/^(?:\d+)/i,/^(?:\s+width\b)/i,/^(?:state\s+)/i,/^(?:.*<<fork>>)/i,/^(?:.*<<join>>)/i,/^(?:.*<<choice>>)/i,/^(?:.*\[\[fork\]\])/i,/^(?:.*\[\[join\]\])/i,/^(?:.*\[\[choice\]\])/i,/^(?:.*direction\s+TB[^\n]*)/i,/^(?:.*direction\s+BT[^\n]*)/i,/^(?:.*direction\s+RL[^\n]*)/i,/^(?:.*direction\s+LR[^\n]*)/i,/^(?:["])/i,/^(?:\s*as\s+)/i,/^(?:[^\n\{]*)/i,/^(?:["])/i,/^(?:[^"]*)/i,/^(?:\w+\s+\w+.*?\{)/i,/^(?:[^\n\s\{]+)/i,/^(?:\n)/i,/^(?:\{)/i,/^(?:\})/i,/^(?:[\n])/i,/^(?:note\s+)/i,/^(?:left of\b)/i,/^(?:right of\b)/i,/^(?:")/i,/^(?:\s*as\s*)/i,/^(?:["])/i,/^(?:[^"]*)/i,/^(?:[^\n]*)/i,/^(?:\s*[^:\n\s\-]+)/i,/^(?:\s*:[^:\n;]+)/i,/^(?:[\s\S]*?\n\s*end note\b)/i,/^(?:stateDiagram\s+)/i,/^(?:stateDiagram-v2\s+)/i,/^(?:hide empty description\b)/i,/^(?:\[\*\])/i,/^(?:[^:\n\s\-\{]+)/i,/^(?:\s*:(?:[^:\n;]|:[^:\n;])+)/i,/^(?:-->)/i,/^(?:--)/i,/^(?::::)/i,/^(?:$)/i,/^(?:.)/i],conditions:{LINE:{rules:[10,11,12],inclusive:!1},struct:{rules:[10,11,12,23,27,30,36,43,44,45,46,56,57,58,72,73,74,75,76,77],inclusive:!1},FLOATING_NOTE_ID:{rules:[65],inclusive:!1},FLOATING_NOTE:{rules:[62,63,64],inclusive:!1},NOTE_TEXT:{rules:[67,68],inclusive:!1},NOTE_ID:{rules:[66],inclusive:!1},NOTE:{rules:[59,60,61],inclusive:!1},STYLEDEF_STYLEOPTS:{rules:[],inclusive:!1},STYLEDEF_STYLES:{rules:[32],inclusive:!1},STYLE_IDS:{rules:[],inclusive:!1},STYLE:{rules:[31],inclusive:!1},CLASS_STYLE:{rules:[29],inclusive:!1},CLASS:{rules:[28],inclusive:!1},CLASSDEFID:{rules:[26],inclusive:!1},CLASSDEF:{rules:[24,25],inclusive:!1},acc_descr_multiline:{rules:[21,22],inclusive:!1},acc_descr:{rules:[19],inclusive:!1},acc_title:{rules:[17],inclusive:!1},SCALE:{rules:[14,15,34,35],inclusive:!1},ALIAS:{rules:[],inclusive:!1},STATE_ID:{rules:[49],inclusive:!1},STATE_STRING:{rules:[50,51],inclusive:!1},FORK_STATE:{rules:[],inclusive:!1},STATE:{rules:[10,11,12,37,38,39,40,41,42,47,48,52,53,54,55],inclusive:!1},ID:{rules:[10,11,12],inclusive:!1},INITIAL:{rules:[0,1,2,3,4,5,6,7,8,9,11,12,13,16,18,20,23,27,30,33,36,55,58,69,70,71,72,73,74,75,77,78,79],inclusive:!0}}};return at}();$t.lexer=Ke;function At(){this.yy={}}return(0,l.K)(At,"Parser"),At.prototype=$t,$t.Parser=At,new At}();H.parser=H;var dt=H,L="TB",S="TB",v="dir",x="state",O="root",ot="relation",he="classDef",ue="style",de="applyClass",gt="default",Gt="divider",Vt="fill:none",Ut="fill: #333",Wt="c",jt="markdown",Ht="normal",wt="rect",Pt="rectWithTitle",fe="stateStart",pe="stateEnd",zt="divider",Xt="roundedWithTitle",ye="note",Se="noteGroup",Et="statediagram",_e="state",ge=`${Et}-${_e}`,Jt="transition",Ee="note",Te="note-edge",me=`${Jt} ${Te}`,De=`${Et}-${Ee}`,ve="cluster",ke=`${Et}-${ve}`,be="cluster-alt",xe=`${Et}-${be}`,Zt="parent",Qt="note",Ce="state",Nt="----",Ae=`${Nt}${Qt}`,qt=`${Nt}${Zt}`,te=(0,l.K)((t,e=S)=>{if(!t.doc)return e;let s=e;for(const n of t.doc)n.stmt==="dir"&&(s=n.value);return s},"getDir"),Le=(0,l.K)(function(t,e){return e.db.getClasses()},"getClasses"),Re=(0,l.K)(function(t,e,s,n){return ce(this,null,function*(){var C,z;E.R.info("REF0:"),E.R.info("Drawing state diagram (v2)",e);const{securityLevel:i,state:o,layout:u}=(0,_.D7)();n.db.extract(n.db.getRootDocV2());const p=n.db.getData(),f=(0,et.A)(e,i);p.type=n.type,p.layoutAlgorithm=u,p.nodeSpacing=(o==null?void 0:o.nodeSpacing)||50,p.rankSpacing=(o==null?void 0:o.rankSpacing)||50,(0,_.D7)().look==="neo"?p.markers=["barbNeo"]:p.markers=["barb"],p.diagramId=e,yield(0,V.XX)(p,f);const b=8;try{(typeof n.db.getLinks=="function"?n.db.getLinks():new Map).forEach((U,N)=>{var X;const I=typeof N=="string"?N:typeof(N==null?void 0:N.id)=="string"?N.id:"",y=p.nodes.find(F=>F.id===I);if(!I){E.R.warn("\u26A0\uFE0F Invalid or missing stateId from key:",JSON.stringify(N));return}const $=(X=f.node())==null?void 0:X.querySelectorAll("g.node, g.rough-node");let w;if($==null||$.forEach(F=>{var ct;const ft=(ct=F.textContent)==null?void 0:ct.trim();(F.id===(y==null?void 0:y.domId)||ft===I)&&(w=F)}),!w){E.R.warn("\u26A0\uFE0F Could not find node matching text:",I);return}const Q=w.parentNode;if(!Q){E.R.warn("\u26A0\uFE0F Node has no parent, cannot wrap:",I);return}const M=document.createElementNS("http://www.w3.org/2000/svg","a"),q=U.url.replace(/^"+|"+$/g,"");if(M.setAttributeNS("http://www.w3.org/1999/xlink","xlink:href",q),M.setAttribute("target","_blank"),U.tooltip){const F=U.tooltip.replace(/^"+|"+$/g,"");M.setAttribute("title",F),w.setAttribute("title",F)}Q.replaceChild(M,w),M.appendChild(w),E.R.info("\u{1F517} Wrapped node in <a> tag for:",I,U.url)})}catch(Z){E.R.error("\u274C Error injecting clickable links:",Z)}B._K.insertTitle(f,"statediagramTitleText",(C=o==null?void 0:o.titleTopMargin)!=null?C:25,n.db.getDiagramTitle()),(0,A.P)(f,b,Et,(z=o==null?void 0:o.useMaxWidth)!=null?z:!0)})},"draw"),Oe={getClasses:Le,draw:Re,getDir:te},vt=new Map,nt=0;function kt(t="",e=0,s="",n=Nt){const i=s!==null&&s.length>0?`${n}${s}`:"";return`${Ce}-${t}${i}-${e}`}(0,l.K)(kt,"stateDomId");var Ie=(0,l.K)((t,e,s,n,i,o,u,p)=>{E.R.trace("items",e),e.forEach(f=>{var T;switch(f.stmt){case x:mt(t,f,s,n,i,o,u,p);break;case gt:mt(t,f,s,n,i,o,u,p);break;case ot:{mt(t,f.state1,s,n,i,o,u,p),mt(t,f.state2,s,n,i,o,u,p);const b=u==="neo",C={id:"edge"+nt,start:f.state1.id,end:f.state2.id,arrowhead:"normal",arrowTypeEnd:b?"arrow_barb_neo":"arrow_barb",style:Vt,labelStyle:"",label:_.Y2.sanitizeText((T=f.description)!=null?T:"",(0,_.D7)()),arrowheadStyle:Ut,labelpos:Wt,labelType:jt,thickness:Ht,classes:Jt,look:u};i.push(C),nt++}break}})},"setupDoc"),ee=(0,l.K)((t,e=S)=>{let s=e;if(t.doc)for(const n of t.doc)n.stmt==="dir"&&(s=n.value);return s},"getDir");function Tt(t,e,s){if(!e.id||e.id==="</join></fork>"||e.id==="</choice>")return;e.cssClasses&&(Array.isArray(e.cssCompiledStyles)||(e.cssCompiledStyles=[]),e.cssClasses.split(" ").forEach(i=>{var u;const o=s.get(i);o&&(e.cssCompiledStyles=[...(u=e.cssCompiledStyles)!=null?u:[],...o.styles])}));const n=t.find(i=>i.id===e.id);n?Object.assign(n,e):t.push(e)}(0,l.K)(Tt,"insertOrUpdateNode");function se(t){var e,s;return(s=(e=t==null?void 0:t.classes)==null?void 0:e.join(" "))!=null?s:""}(0,l.K)(se,"getClassesFromDbInfo");function ie(t){var e;return(e=t==null?void 0:t.styles)!=null?e:[]}(0,l.K)(ie,"getStylesFromDbInfo");var mt=(0,l.K)((t,e,s,n,i,o,u,p)=>{var Z,U,N;const f=e.id,T=s.get(f),b=se(T),C=ie(T),z=(0,_.D7)();if(E.R.info("dataFetcher parsedItem",e,T,C),f!=="root"){let I=wt;e.start===!0?I=fe:e.start===!1&&(I=pe),e.type!==gt&&(I=e.type),vt.get(f)||vt.set(f,{id:f,shape:I,description:_.Y2.sanitizeText(f,z),cssClasses:`${b} ${ge}`,cssStyles:C});const y=vt.get(f);e.description&&(Array.isArray(y.description)?(y.shape=Pt,y.description.push(e.description)):(Z=y.description)!=null&&Z.length&&y.description.length>0?(y.shape=Pt,y.description===f?y.description=[e.description]:y.description=[y.description,e.description]):(y.shape=wt,y.description=e.description),y.description=_.Y2.sanitizeTextOrArray(y.description,z)),((U=y.description)==null?void 0:U.length)===1&&y.shape===Pt&&(y.type==="group"?y.shape=Xt:y.shape=wt),!y.type&&e.doc&&(E.R.info("Setting cluster for XCX",f,ee(e)),y.type="group",y.isGroup=!0,y.dir=ee(e),y.shape=e.type===Gt?zt:Xt,y.cssClasses=`${y.cssClasses} ${ke} ${o?xe:""}`);const $={labelStyle:"",shape:y.shape,label:y.description,cssClasses:y.cssClasses,cssCompiledStyles:[],cssStyles:y.cssStyles,id:f,dir:y.dir,domId:kt(f,nt),type:y.type,isGroup:y.type==="group",padding:8,rx:10,ry:10,look:u,labelType:"markdown"};if($.shape===zt&&($.label=""),t&&t.id!=="root"&&(E.R.trace("Setting node ",f," to be child of its parent ",t.id),$.parentId=t.id),$.centerLabel=!0,e.note){const w={labelStyle:"",shape:ye,label:e.note.text,labelType:"markdown",cssClasses:De,cssStyles:[],cssCompiledStyles:[],id:f+Ae+"-"+nt,domId:kt(f,nt,Qt),type:y.type,isGroup:y.type==="group",padding:(N=z.flowchart)==null?void 0:N.padding,look:u,position:e.note.position},Q=f+qt,M={labelStyle:"",shape:Se,label:e.note.text,cssClasses:y.cssClasses,cssStyles:[],id:f+qt,domId:kt(f,nt,Zt),type:"group",isGroup:!0,padding:16,look:u,position:e.note.position};nt++,M.id=Q,w.parentId=Q,Tt(n,M,p),Tt(n,w,p),Tt(n,$,p);let q=f,X=w.id;e.note.position==="left of"&&(q=w.id,X=f),i.push({id:q+"-"+X,start:q,end:X,arrowhead:"none",arrowTypeEnd:"",style:Vt,labelStyle:"",classes:me,arrowheadStyle:Ut,labelpos:Wt,labelType:jt,thickness:Ht,look:u})}else Tt(n,$,p)}e.doc&&(E.R.trace("Adding nodes children "),Ie(e,e.doc,s,n,i,!o,u,p))},"dataFetcher"),we=(0,l.K)(()=>{vt.clear(),nt=0},"reset"),P={START_NODE:"[*]",START_TYPE:"start",END_NODE:"[*]",END_TYPE:"end",COLOR_KEYWORD:"color",FILL_KEYWORD:"fill",BG_FILL:"bgFill",STYLECLASS_SEP:","},re=(0,l.K)(()=>new Map,"newClassesList"),ne=(0,l.K)(()=>({relations:[],states:new Map,documents:{}}),"newDoc"),bt=(0,l.K)(t=>JSON.parse(JSON.stringify(t)),"clone"),Pe=(lt=class{constructor(e){this.version=e,this.nodes=[],this.edges=[],this.rootDoc=[],this.classes=re(),this.documents={root:ne()},this.currentDocument=this.documents.root,this.startEndCount=0,this.dividerCnt=0,this.links=new Map,this.funs=[],this.getAccTitle=_.iN,this.setAccTitle=_.SV,this.getAccDescription=_.m7,this.setAccDescription=_.EI,this.setDiagramTitle=_.ke,this.getDiagramTitle=_.ab,this.clear(),this.setRootDoc=this.setRootDoc.bind(this),this.getDividerId=this.getDividerId.bind(this),this.setDirection=this.setDirection.bind(this),this.trimColon=this.trimColon.bind(this),this.bindFunctions=this.bindFunctions.bind(this)}extract(e){this.clear(!0);for(const i of Array.isArray(e)?e:e.doc)switch(i.stmt){case x:this.addState(i.id.trim(),i.type,i.doc,i.description,i.note);break;case ot:this.addRelation(i.state1,i.state2,i.description);break;case he:this.addStyleClass(i.id.trim(),i.classes);break;case ue:this.handleStyleDef(i);break;case de:this.setCssClass(i.id.trim(),i.styleClass);break;case"click":this.addLink(i.id,i.url,i.tooltip);break}const s=this.getStates(),n=(0,_.D7)();we(),mt(void 0,this.getRootDocV2(),s,this.nodes,this.edges,!0,n.look,this.classes);for(const i of this.nodes)if(Array.isArray(i.label)){if(i.description=i.label.slice(1),i.isGroup&&i.description.length>0)throw new Error(`Group nodes can only have label. Remove the additional description for node [${i.id}]`);i.label=i.label[0]}}handleStyleDef(e){const s=e.id.trim().split(","),n=e.styleClass.split(",");for(const i of s){let o=this.getState(i);if(!o){const u=i.trim();this.addState(u),o=this.getState(u)}o&&(o.styles=n.map(u=>{var p;return(p=u.replace(/;/g,""))==null?void 0:p.trim()}))}}setRootDoc(e){E.R.info("Setting root doc",e),this.rootDoc=e,this.version===1?this.extract(e):this.extract(this.getRootDocV2())}docTranslator(e,s,n){if(s.stmt===ot){this.docTranslator(e,s.state1,!0),this.docTranslator(e,s.state2,!1);return}if(s.stmt===x&&(s.id===P.START_NODE?(s.id=e.id+(n?"_start":"_end"),s.start=n):s.id=s.id.trim()),s.stmt!==O&&s.stmt!==x||!s.doc)return;const i=[];let o=[];for(const u of s.doc)if(u.type===Gt){const p=bt(u);p.doc=bt(o),i.push(p),o=[]}else o.push(u);if(i.length>0&&o.length>0){const u={stmt:x,id:(0,B.$C)(),type:"divider",doc:bt(o)};i.push(bt(u)),s.doc=i}s.doc.forEach(u=>this.docTranslator(s,u,!0))}getRootDocV2(){return this.docTranslator({id:O,stmt:O},{id:O,stmt:O,doc:this.rootDoc},!0),{id:O,doc:this.rootDoc}}addState(e,s=gt,n=void 0,i=void 0,o=void 0,u=void 0,p=void 0,f=void 0){const T=e==null?void 0:e.trim();if(!this.currentDocument.states.has(T))E.R.info("Adding state ",T,i),this.currentDocument.states.set(T,{stmt:x,id:T,descriptions:[],type:s,doc:n,note:o,classes:[],styles:[],textStyles:[]});else{const b=this.currentDocument.states.get(T);if(!b)throw new Error(`State not found: ${T}`);b.doc||(b.doc=n),b.type||(b.type=s)}if(i&&(E.R.info("Setting state description",T,i),(Array.isArray(i)?i:[i]).forEach(C=>this.addDescription(T,C.trim()))),o){const b=this.currentDocument.states.get(T);if(!b)throw new Error(`State not found: ${T}`);b.note=o,b.note.text=_.Y2.sanitizeText(b.note.text,(0,_.D7)())}u&&(E.R.info("Setting state classes",T,u),(Array.isArray(u)?u:[u]).forEach(C=>this.setCssClass(T,C.trim()))),p&&(E.R.info("Setting state styles",T,p),(Array.isArray(p)?p:[p]).forEach(C=>this.setStyle(T,C.trim()))),f&&(E.R.info("Setting state styles",T,p),(Array.isArray(f)?f:[f]).forEach(C=>this.setTextStyle(T,C.trim())))}clear(e){this.nodes=[],this.edges=[],this.funs=[this.setupToolTips.bind(this)],this.documents={root:ne()},this.currentDocument=this.documents.root,this.startEndCount=0,this.classes=re(),e||(this.links=new Map,(0,_.IU)())}getState(e){return this.currentDocument.states.get(e)}getStates(){return this.currentDocument.states}logDocuments(){E.R.info("Documents = ",this.documents)}getRelations(){return this.currentDocument.relations}addLink(e,s,n){this.links.set(e,{url:s,tooltip:n}),E.R.warn("Adding link",e,s,n)}getLinks(){return this.links}startIdIfNeeded(e=""){return e===P.START_NODE?(this.startEndCount++,`${P.START_TYPE}${this.startEndCount}`):e}startTypeIfNeeded(e="",s=gt){return e===P.START_NODE?P.START_TYPE:s}endIdIfNeeded(e=""){return e===P.END_NODE?(this.startEndCount++,`${P.END_TYPE}${this.startEndCount}`):e}endTypeIfNeeded(e="",s=gt){return e===P.END_NODE?P.END_TYPE:s}addRelationObjs(e,s,n=""){const i=this.startIdIfNeeded(e.id.trim()),o=this.startTypeIfNeeded(e.id.trim(),e.type),u=this.startIdIfNeeded(s.id.trim()),p=this.startTypeIfNeeded(s.id.trim(),s.type);this.addState(i,o,e.doc,e.description,e.note,e.classes,e.styles,e.textStyles),this.addState(u,p,s.doc,s.description,s.note,s.classes,s.styles,s.textStyles),this.currentDocument.relations.push({id1:i,id2:u,relationTitle:_.Y2.sanitizeText(n,(0,_.D7)())})}addRelation(e,s,n){if(typeof e=="object"&&typeof s=="object")this.addRelationObjs(e,s,n);else if(typeof e=="string"&&typeof s=="string"){const i=this.startIdIfNeeded(e.trim()),o=this.startTypeIfNeeded(e),u=this.endIdIfNeeded(s.trim()),p=this.endTypeIfNeeded(s);this.addState(i,o),this.addState(u,p),this.currentDocument.relations.push({id1:i,id2:u,relationTitle:n?_.Y2.sanitizeText(n,(0,_.D7)()):void 0})}}addDescription(e,s){var o;const n=this.currentDocument.states.get(e),i=s.startsWith(":")?s.replace(":","").trim():s;(o=n==null?void 0:n.descriptions)==null||o.push(_.Y2.sanitizeText(i,(0,_.D7)()))}cleanupLabel(e){return e.startsWith(":")?e.slice(2).trim():e.trim()}getDividerId(){return this.dividerCnt++,`divider-id-${this.dividerCnt}`}addStyleClass(e,s=""){this.classes.has(e)||this.classes.set(e,{id:e,styles:[],textStyles:[]});const n=this.classes.get(e);s&&n&&s.split(P.STYLECLASS_SEP).forEach(i=>{const o=i.replace(/([^;]*);/,"$1").trim();if(RegExp(P.COLOR_KEYWORD).exec(i)){const p=o.replace(P.FILL_KEYWORD,P.BG_FILL).replace(P.COLOR_KEYWORD,P.FILL_KEYWORD);n.textStyles.push(p)}n.styles.push(o)})}getClasses(){return this.classes}setupToolTips(e){const s=(0,j.Ck)();(0,Y.Ltv)(e).select("svg").selectAll("g.node, g.rough-node").on("mouseover",o=>{var T;const u=(0,Y.Ltv)(o.currentTarget),p=u.attr("title");if(p===null)return;const f=(T=o.currentTarget)==null?void 0:T.getBoundingClientRect();s.transition().duration(200).style("opacity",".9"),s.style("left",window.scrollX+f.left+(f.right-f.left)/2+"px").style("top",window.scrollY+f.bottom+"px"),s.html(J.A.sanitize(p)),u.classed("hover",!0)}).on("mouseout",o=>{s.transition().duration(500).style("opacity",0),(0,Y.Ltv)(o.currentTarget).classed("hover",!1)})}setCssClass(e,s){e.split(",").forEach(n=>{var o;let i=this.getState(n);if(!i){const u=n.trim();this.addState(u),i=this.getState(u)}(o=i==null?void 0:i.classes)==null||o.push(s)})}setStyle(e,s){var n,i;(i=(n=this.getState(e))==null?void 0:n.styles)==null||i.push(s)}setTextStyle(e,s){var n,i;(i=(n=this.getState(e))==null?void 0:n.textStyles)==null||i.push(s)}bindFunctions(e){this.funs.forEach(s=>{s(e)})}getDirectionStatement(){return this.rootDoc.find(e=>e.stmt===v)}getDirection(){var e,s;return(s=(e=this.getDirectionStatement())==null?void 0:e.value)!=null?s:L}setDirection(e){const s=this.getDirectionStatement();s?s.value=e:this.rootDoc.unshift({stmt:v,value:e})}trimColon(e){return e.startsWith(":")?e.slice(1).trim():e.trim()}getData(){const e=(0,_.D7)();return{nodes:this.nodes,edges:this.edges,other:{},config:e,direction:te(this.getRootDocV2())}}getConfig(){return(0,_.D7)().state}},(0,l.K)(lt,"StateDB"),lt.relationType={AGGREGATION:0,EXTENSION:1,COMPOSITION:2,DEPENDENCY:3},lt),Ne=(0,l.K)(t=>{var e;return`
defs [id$="-barbEnd"] {
    fill: ${t.transitionColor};
    stroke: ${t.transitionColor};
  }
g.stateGroup text {
  fill: ${t.nodeBorder};
  stroke: none;
  font-size: 10px;
}
g.stateGroup text {
  fill: ${t.textColor};
  stroke: none;
  font-size: 10px;

}
g.stateGroup .state-title {
  font-weight: bolder;
  fill: ${t.stateLabelColor};
}

g.stateGroup rect {
  fill: ${t.mainBkg};
  stroke: ${t.nodeBorder};
}

g.stateGroup line {
  stroke: ${t.lineColor};
  stroke-width: ${t.strokeWidth||1};
}

.transition {
  stroke: ${t.transitionColor};
  stroke-width: ${t.strokeWidth||1};
  fill: none;
}

.stateGroup .composit {
  fill: ${t.background};
  border-bottom: 1px
}

.stateGroup .alt-composit {
  fill: #e0e0e0;
  border-bottom: 1px
}

.state-note {
  stroke: ${t.noteBorderColor};
  fill: ${t.noteBkgColor};

  text {
    fill: ${t.noteTextColor};
    stroke: none;
    font-size: 10px;
  }
}

.stateLabel .box {
  stroke: none;
  stroke-width: 0;
  fill: ${t.mainBkg};
  opacity: 0.5;
}

.edgeLabel .label rect {
  fill: ${t.labelBackgroundColor};
  opacity: 0.5;
}
.edgeLabel {
  background-color: ${t.edgeLabelBackground};
  p {
    background-color: ${t.edgeLabelBackground};
  }
  rect {
    opacity: 0.5;
    background-color: ${t.edgeLabelBackground};
    fill: ${t.edgeLabelBackground};
  }
  text-align: center;
}
.edgeLabel .label text {
  fill: ${t.transitionLabelColor||t.tertiaryTextColor};
}
.label div .edgeLabel {
  color: ${t.transitionLabelColor||t.tertiaryTextColor};
}

.stateLabel text {
  fill: ${t.stateLabelColor};
  font-size: 10px;
  font-weight: bold;
}

.node circle.state-start {
  fill: ${t.specialStateColor};
  stroke: ${t.specialStateColor};
}

.node .fork-join {
  fill: ${t.specialStateColor};
  stroke: ${t.specialStateColor};
}

.node circle.state-end {
  fill: ${t.innerEndBackground};
  stroke: ${t.background};
  stroke-width: 1.5
}
.end-state-inner {
  fill: ${t.compositeBackground||t.background};
  // stroke: ${t.background};
  stroke-width: 1.5
}

.node rect {
  fill: ${t.stateBkg||t.mainBkg};
  stroke: ${t.stateBorder||t.nodeBorder};
  stroke-width: ${t.strokeWidth||1}px;
}
.node polygon {
  fill: ${t.mainBkg};
  stroke: ${t.stateBorder||t.nodeBorder};;
  stroke-width: ${t.strokeWidth||1}px;
}
[id$="-barbEnd"] {
  fill: ${t.lineColor};
}

.statediagram-cluster rect {
  fill: ${t.compositeTitleBackground};
  stroke: ${t.stateBorder||t.nodeBorder};
  stroke-width: ${t.strokeWidth||1}px;
}

.cluster-label, .nodeLabel {
  color: ${t.stateLabelColor};
  // line-height: 1;
}

.statediagram-cluster rect.outer {
  rx: 5px;
  ry: 5px;
}
.statediagram-state .divider {
  stroke: ${t.stateBorder||t.nodeBorder};
}

.statediagram-state .title-state {
  rx: 5px;
  ry: 5px;
}
.statediagram-cluster.statediagram-cluster .inner {
  fill: ${t.compositeBackground||t.background};
}
.statediagram-cluster.statediagram-cluster-alt .inner {
  fill: ${t.altBackground?t.altBackground:"#efefef"};
}

.statediagram-cluster .inner {
  rx:0;
  ry:0;
}

.statediagram-state rect.basic {
  rx: 5px;
  ry: 5px;
}
.statediagram-state rect.divider {
  stroke-dasharray: 10,10;
  fill: ${t.altBackground?t.altBackground:"#efefef"};
}

.note-edge {
  stroke-dasharray: 5;
}

.statediagram-note rect {
  fill: ${t.noteBkgColor};
  stroke: ${t.noteBorderColor};
  stroke-width: 1px;
  rx: 0;
  ry: 0;
}
.statediagram-note rect {
  fill: ${t.noteBkgColor};
  stroke: ${t.noteBorderColor};
  stroke-width: 1px;
  rx: 0;
  ry: 0;
}

.statediagram-note text {
  fill: ${t.noteTextColor};
}

.statediagram-note .nodeLabel {
  color: ${t.noteTextColor};
}
.statediagram .edgeLabel {
  color: red; // ${t.noteTextColor};
}

[id$="-dependencyStart"], [id$="-dependencyEnd"] {
  fill: ${t.lineColor};
  stroke: ${t.lineColor};
  stroke-width: ${t.strokeWidth||1};
}

.statediagramTitleText {
  text-anchor: middle;
  font-size: 18px;
  fill: ${t.textColor};
}

[data-look="neo"].statediagram-cluster rect {
  fill: ${t.mainBkg};
  stroke: ${t.useGradient?"url("+t.svgId+"-gradient)":t.stateBorder||t.nodeBorder};
  stroke-width: ${(e=t.strokeWidth)!=null?e:1};
}
[data-look="neo"].statediagram-cluster rect.outer {
  rx: ${t.radius}px;
  ry: ${t.radius}px;
  filter: ${t.dropShadow?t.dropShadow.replace("url(#drop-shadow)",`url(${t.svgId}-drop-shadow)`):"none"}
}
`},"getStyles"),$e=Ne},1672:function(_t,tt,D){D.d(tt,{P:function(){return j}});var et=D(76385),A=D(31293),V=D(86827),j=(0,V.K)((E,l,Y,J)=>{E.attr("class",Y);const{width:H,height:dt,x:L,y:S}=B(E,l);(0,et.a$)(E,dt,H,J);const v=_(L,S,H,dt,l);E.attr("viewBox",v),A.R.debug(`viewBox configured: ${v} with padding: ${l}`)},"setupViewPortForSVG"),B=(0,V.K)((E,l)=>{var J;const Y=((J=E.node())==null?void 0:J.getBBox())||{width:0,height:0,x:0,y:0};return{width:Y.width+l*2,height:Y.height+l*2,x:Y.x,y:Y.y}},"calculateDimensionsWithPadding"),_=(0,V.K)((E,l,Y,J,H)=>`${E-H} ${l-H} ${Y} ${J}`,"createViewBox")},96755:function(_t,tt,D){D.d(tt,{A:function(){return V}});var et=D(86827),A=D(12300),V=(0,et.K)((j,B)=>{let _;return B==="sandbox"&&(_=(0,A.Ltv)("#i"+j)),(B==="sandbox"?(0,A.Ltv)(_.nodes()[0].contentDocument.body):(0,A.Ltv)("body")).select(`[id="${j}"]`)},"getDiagramElement")}}]);
}());