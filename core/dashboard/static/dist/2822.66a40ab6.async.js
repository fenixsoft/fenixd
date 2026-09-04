(self.webpackChunkfenix_dashboard_v3=self.webpackChunkfenix_dashboard_v3||[]).push([[2822],{97375:function(_t){(function(it,S){_t.exports=S()})(this,function(){"use strict";return function(it,S){var ut=S.prototype,O=ut.format;ut.format=function(F){var e=this,Z=this.$locale();if(!this.isValid())return O.bind(this)(F);var b=this.$utils(),P=(F||"YYYY-MM-DDTHH:mm:ssZ").replace(/\[([^\]]+)]|Q|wo|ww|w|WW|W|zzz|z|gggg|GGGG|Do|X|x|k{1,2}|S/g,function(q){switch(q){case"Q":return Math.ceil((e.$M+1)/3);case"Do":return Z.ordinal(e.$D);case"gggg":return e.weekYear();case"GGGG":return e.isoWeekYear();case"wo":return Z.ordinal(e.week(),"W");case"w":case"ww":return b.s(e.week(),q==="w"?1:2,"0");case"W":case"WW":return b.s(e.isoWeek(),q==="W"?1:2,"0");case"k":case"kk":return b.s(String(e.$H===0?24:e.$H),q==="k"?1:2,"0");case"X":return Math.floor(e.$d.getTime()/1e3);case"x":return e.$d.getTime();case"z":return"["+e.offsetName()+"]";case"zzz":return"["+e.offsetName("long")+"]";default:return q}});return O.bind(this)(P)}}})},90445:function(_t){(function(it,S){_t.exports=S()})(this,function(){"use strict";var it={LTS:"h:mm:ss A",LT:"h:mm A",L:"MM/DD/YYYY",LL:"MMMM D, YYYY",LLL:"MMMM D, YYYY h:mm A",LLLL:"dddd, MMMM D, YYYY h:mm A"},S=/(\[[^[]*\])|([-_:/.,()\s]+)|(A|a|Q|YYYY|YY?|ww?|MM?M?M?|Do|DD?|hh?|HH?|mm?|ss?|S{1,3}|z|ZZ?)/g,ut=/\d/,O=/\d\d/,F=/\d\d?/,e=/\d*[^-_:/,()\s\d]+/,Z={},b=function(v){return(v=+v)+(v>68?1900:2e3)},P=function(v){return function(D){this[v]=+D}},q=[/[+-]\d\d:?(\d\d)?|Z/,function(v){(this.zone||(this.zone={})).offset=function(D){if(!D||D==="Z")return 0;var K=D.match(/([+-]|\d\d)/g),Y=60*K[1]+(+K[2]||0);return Y===0?0:K[0]==="+"?-Y:Y}(v)}],tt=function(v){var D=Z[v];return D&&(D.indexOf?D:D.s.concat(D.f))},dt=function(v,D){var K,Y=Z.meridiem;if(Y){for(var et=1;et<=24;et+=1)if(v.indexOf(Y(et,0,D))>-1){K=et>12;break}}else K=v===(D?"pm":"PM");return K},T={A:[e,function(v){this.afternoon=dt(v,!1)}],a:[e,function(v){this.afternoon=dt(v,!0)}],Q:[ut,function(v){this.month=3*(v-1)+1}],S:[ut,function(v){this.milliseconds=100*+v}],SS:[O,function(v){this.milliseconds=10*+v}],SSS:[/\d{3}/,function(v){this.milliseconds=+v}],s:[F,P("seconds")],ss:[F,P("seconds")],m:[F,P("minutes")],mm:[F,P("minutes")],H:[F,P("hours")],h:[F,P("hours")],HH:[F,P("hours")],hh:[F,P("hours")],D:[F,P("day")],DD:[O,P("day")],Do:[e,function(v){var D=Z.ordinal,K=v.match(/\d+/);if(this.day=K[0],D)for(var Y=1;Y<=31;Y+=1)D(Y).replace(/\[|\]/g,"")===v&&(this.day=Y)}],w:[F,P("week")],ww:[O,P("week")],M:[F,P("month")],MM:[O,P("month")],MMM:[e,function(v){var D=tt("months"),K=(tt("monthsShort")||D.map(function(Y){return Y.slice(0,3)})).indexOf(v)+1;if(K<1)throw new Error;this.month=K%12||K}],MMMM:[e,function(v){var D=tt("months").indexOf(v)+1;if(D<1)throw new Error;this.month=D%12||D}],Y:[/[+-]?\d+/,P("year")],YY:[O,function(v){this.year=b(v)}],YYYY:[/\d{4}/,P("year")],Z:q,ZZ:q};function ft(v){var D,K;D=v,K=Z&&Z.formats;for(var Y=(v=D.replace(/(\[[^\]]+])|(LTS?|l{1,4}|L{1,4})/g,function($,I,R){var B=R&&R.toUpperCase();return I||K[R]||it[R]||K[B].replace(/(\[[^\]]+])|(MMMM|MM|DD|dddd)/g,function(j,Q,nt){return Q||nt.slice(1)})})).match(S),et=Y.length,st=0;st<et;st+=1){var C=Y[st],m=T[C],d=m&&m[0],E=m&&m[1];Y[st]=E?{regex:d,parser:E}:C.replace(/^\[|\]$/g,"")}return function($){for(var I={},R=0,B=0;R<et;R+=1){var j=Y[R];if(typeof j=="string")B+=j.length;else{var Q=j.regex,nt=j.parser,vt=$.slice(B),ot=Q.exec(vt)[0];nt.call(I,ot),$=$.replace(ot,"")}}return function(mt){var wt=mt.afternoon;if(wt!==void 0){var ct=mt.hours;wt?ct<12&&(mt.hours+=12):ct===12&&(mt.hours=0),delete mt.afternoon}}(I),I}}return function(v,D,K){K.p.customParseFormat=!0,v&&v.parseTwoDigitYear&&(b=v.parseTwoDigitYear);var Y=D.prototype,et=Y.parse;Y.parse=function(st){var C=st.date,m=st.utc,d=st.args;this.$u=m;var E=d[1];if(typeof E=="string"){var $=d[2]===!0,I=d[3]===!0,R=$||I,B=d[2];I&&(B=d[2]),Z=this.$locale(),!$&&B&&(Z=K.Ls[B]),this.$d=function(vt,ot,mt,wt){try{if(["x","X"].indexOf(ot)>-1)return new Date((ot==="X"?1e3:1)*vt);var ct=ft(ot)(vt),Ot=ct.year,Mt=ct.month,ne=ct.day,re=ct.hours,ae=ct.minutes,oe=ct.seconds,ce=ct.milliseconds,Jt=ct.zone,qt=ct.week,$t=new Date,Wt=ne||(Ot||Mt?1:$t.getDate()),Ft=Ot||$t.getFullYear(),St=0;Ot&&!Mt||(St=Mt>0?Mt-1:$t.getMonth());var Kt,Pt=re||0,It=ae||0,Rt=oe||0,Vt=ce||0;return Jt?new Date(Date.UTC(Ft,St,Wt,Pt,It,Rt,Vt+60*Jt.offset*1e3)):mt?new Date(Date.UTC(Ft,St,Wt,Pt,It,Rt,Vt)):(Kt=new Date(Ft,St,Wt,Pt,It,Rt,Vt),qt&&(Kt=wt(Kt).week(qt).toDate()),Kt)}catch(ye){return new Date("")}}(C,E,m,K),this.init(),B&&B!==!0&&(this.$L=this.locale(B).$L),R&&C!=this.format(E)&&(this.$d=new Date("")),Z={}}else if(E instanceof Array)for(var j=E.length,Q=1;Q<=j;Q+=1){d[1]=E[Q-1];var nt=K.apply(this,d);if(nt.isValid()){this.$d=nt.$d,this.$L=nt.$L,this.init();break}Q===j&&(this.$d=new Date(""))}else et.call(this,st)}}})},43522:function(_t){(function(it,S){_t.exports=S()})(this,function(){"use strict";var it,S,ut=1e3,O=6e4,F=36e5,e=864e5,Z=31536e6,b=2628e6,P=/^(-|\+)?P(?:([-+]?[0-9,.]*)Y)?(?:([-+]?[0-9,.]*)M)?(?:([-+]?[0-9,.]*)W)?(?:([-+]?[0-9,.]*)D)?(?:T(?:([-+]?[0-9,.]*)H)?(?:([-+]?[0-9,.]*)M)?(?:([-+]?[0-9,.]*)S)?)?$/,q=/\[([^\]]+)]|YYYY|YY|Y|M{1,2}|D{1,2}|H{1,2}|m{1,2}|s{1,2}|SSS/g,tt={years:Z,months:b,days:e,hours:F,minutes:O,seconds:ut,milliseconds:1,weeks:6048e5},dt=function(C){return C instanceof et},T=function(C,m,d){return new et(C,d,m.$l)},ft=function(C){return S.p(C)+"s"},v=function(C){return C<0},D=function(C){return v(C)?Math.ceil(C):Math.floor(C)},K=function(C){return Math.abs(C)},Y=function(C,m){return C?v(C)?{negative:!0,format:""+K(C)+m}:{negative:!1,format:""+C+m}:{negative:!1,format:""}},et=function(){function C(d,E,$){var I=this;if(this.$d={},this.$l=$,d===void 0&&(this.$ms=0,this.parseFromMilliseconds()),E)return T(d*tt[ft(E)],this);if(typeof d=="number")return this.$ms=d,this.parseFromMilliseconds(),this;if(typeof d=="object")return Object.keys(d).forEach(function(j){I.$d[ft(j)]=d[j]}),this.calMilliseconds(),this;if(typeof d=="string"){var R=d.match(P);if(R){var B=R.slice(2).map(function(j){return j!=null?Number(j):0});return this.$d.years=B[0],this.$d.months=B[1],this.$d.weeks=B[2],this.$d.days=B[3],this.$d.hours=B[4],this.$d.minutes=B[5],this.$d.seconds=B[6],this.calMilliseconds(),this}}return this}var m=C.prototype;return m.calMilliseconds=function(){var d=this;this.$ms=Object.keys(this.$d).reduce(function(E,$){return E+(d.$d[$]||0)*tt[$]},0)},m.parseFromMilliseconds=function(){var d=this.$ms;this.$d.years=D(d/Z),d%=Z,this.$d.months=D(d/b),d%=b,this.$d.days=D(d/e),d%=e,this.$d.hours=D(d/F),d%=F,this.$d.minutes=D(d/O),d%=O,this.$d.seconds=D(d/ut),d%=ut,this.$d.milliseconds=d},m.toISOString=function(){var d=Y(this.$d.years,"Y"),E=Y(this.$d.months,"M"),$=+this.$d.days||0;this.$d.weeks&&($+=7*this.$d.weeks);var I=Y($,"D"),R=Y(this.$d.hours,"H"),B=Y(this.$d.minutes,"M"),j=this.$d.seconds||0;this.$d.milliseconds&&(j+=this.$d.milliseconds/1e3,j=Math.round(1e3*j)/1e3);var Q=Y(j,"S"),nt=d.negative||E.negative||I.negative||R.negative||B.negative||Q.negative,vt=R.format||B.format||Q.format?"T":"",ot=(nt?"-":"")+"P"+d.format+E.format+I.format+vt+R.format+B.format+Q.format;return ot==="P"||ot==="-P"?"P0D":ot},m.toJSON=function(){return this.toISOString()},m.format=function(d){var E=d||"YYYY-MM-DDTHH:mm:ss",$={Y:this.$d.years,YY:S.s(this.$d.years,2,"0"),YYYY:S.s(this.$d.years,4,"0"),M:this.$d.months,MM:S.s(this.$d.months,2,"0"),D:this.$d.days,DD:S.s(this.$d.days,2,"0"),H:this.$d.hours,HH:S.s(this.$d.hours,2,"0"),m:this.$d.minutes,mm:S.s(this.$d.minutes,2,"0"),s:this.$d.seconds,ss:S.s(this.$d.seconds,2,"0"),SSS:S.s(this.$d.milliseconds,3,"0")};return E.replace(q,function(I,R){return R||String($[I])})},m.as=function(d){return this.$ms/tt[ft(d)]},m.get=function(d){var E=this.$ms,$=ft(d);return $==="milliseconds"?E%=1e3:E=$==="weeks"?D(E/tt[$]):this.$d[$],E||0},m.add=function(d,E,$){var I;return I=E?d*tt[ft(E)]:dt(d)?d.$ms:T(d,this).$ms,T(this.$ms+I*($?-1:1),this)},m.subtract=function(d,E){return this.add(d,E,!0)},m.locale=function(d){var E=this.clone();return E.$l=d,E},m.clone=function(){return T(this.$ms,this)},m.humanize=function(d){return it().add(this.$ms,"ms").locale(this.$l).fromNow(!d)},m.valueOf=function(){return this.asMilliseconds()},m.milliseconds=function(){return this.get("milliseconds")},m.asMilliseconds=function(){return this.as("milliseconds")},m.seconds=function(){return this.get("seconds")},m.asSeconds=function(){return this.as("seconds")},m.minutes=function(){return this.get("minutes")},m.asMinutes=function(){return this.as("minutes")},m.hours=function(){return this.get("hours")},m.asHours=function(){return this.as("hours")},m.days=function(){return this.get("days")},m.asDays=function(){return this.as("days")},m.weeks=function(){return this.get("weeks")},m.asWeeks=function(){return this.as("weeks")},m.months=function(){return this.get("months")},m.asMonths=function(){return this.as("months")},m.years=function(){return this.get("years")},m.asYears=function(){return this.as("years")},C}(),st=function(C,m,d){return C.add(m.years()*d,"y").add(m.months()*d,"M").add(m.days()*d,"d").add(m.hours()*d,"h").add(m.minutes()*d,"m").add(m.seconds()*d,"s").add(m.milliseconds()*d,"ms")};return function(C,m,d){it=d,S=d().$utils(),d.duration=function(I,R){var B=d.locale();return T(I,{$l:B},R)},d.isDuration=dt;var E=m.prototype.add,$=m.prototype.subtract;m.prototype.add=function(I,R){return dt(I)?st(this,I,1):E.bind(this)(I,R)},m.prototype.subtract=function(I,R){return dt(I)?st(this,I,-1):$.bind(this)(I,R)}}})},68313:function(_t){(function(it,S){_t.exports=S()})(this,function(){"use strict";var it="day";return function(S,ut,O){var F=function(b){return b.add(4-b.isoWeekday(),it)},e=ut.prototype;e.isoWeekYear=function(){return F(this).year()},e.isoWeek=function(b){if(!this.$utils().u(b))return this.add(7*(b-this.isoWeek()),it);var P,q,tt,dt,T=F(this),ft=(P=this.isoWeekYear(),q=this.$u,tt=(q?O.utc:O)().year(P).startOf("year"),dt=4-tt.isoWeekday(),tt.isoWeekday()>4&&(dt+=7),tt.add(dt,it));return T.diff(ft,"week")+1},e.isoWeekday=function(b){return this.$utils().u(b)?this.day()||7:this.day(this.day()%7?b:b-7)};var Z=e.startOf;e.startOf=function(b,P){var q=this.$utils(),tt=!!q.u(P)||P;return q.p(b)==="isoweek"?tt?this.date(this.date()-(this.isoWeekday()-1)).startOf("day"):this.date(this.date()-1-(this.isoWeekday()-1)+7).endOf("day"):Z.bind(this)(b,P)}}})},92822:function(_t,it,S){"use strict";S.d(it,{diagram:function(){return Je}});var ut=S(16459),O=S(76385),F=S(31293),e=S(86827),Z=S(16750),b=S(74353),P=S(68313),q=S(90445),tt=S(97375),dt=S(43522),T=S(12300),ft=function(){var t=(0,e.K)(function(g,o,f,h){for(f=f||{},h=g.length;h--;f[g[h]]=o);return f},"o"),i=[6,8,10,12,13,14,15,16,17,18,20,21,22,23,24,25,26,27,28,29,30,31,33,35,36,38,40],n=[1,26],r=[1,27],a=[1,28],k=[1,29],p=[1,30],U=[1,31],rt=[1,32],xt=[1,33],G=[1,34],pt=[1,9],lt=[1,10],gt=[1,11],Dt=[1,12],kt=[1,13],W=[1,14],Bt=[1,15],Nt=[1,16],zt=[1,19],Ut=[1,20],At=[1,21],Ht=[1,22],jt=[1,23],Gt=[1,25],Xt=[1,35],y={trace:(0,e.K)(function(){},"trace"),yy:{},symbols_:{error:2,start:3,gantt:4,document:5,EOF:6,line:7,SPACE:8,statement:9,NL:10,weekday:11,weekday_monday:12,weekday_tuesday:13,weekday_wednesday:14,weekday_thursday:15,weekday_friday:16,weekday_saturday:17,weekday_sunday:18,weekend:19,weekend_friday:20,weekend_saturday:21,dateFormat:22,inclusiveEndDates:23,topAxis:24,axisFormat:25,tickInterval:26,excludes:27,includes:28,todayMarker:29,title:30,acc_title:31,acc_title_value:32,acc_descr:33,acc_descr_value:34,acc_descr_multiline_value:35,section:36,clickStatement:37,taskTxt:38,taskData:39,click:40,callbackname:41,callbackargs:42,href:43,clickStatementDebug:44,$accept:0,$end:1},terminals_:{2:"error",4:"gantt",6:"EOF",8:"SPACE",10:"NL",12:"weekday_monday",13:"weekday_tuesday",14:"weekday_wednesday",15:"weekday_thursday",16:"weekday_friday",17:"weekday_saturday",18:"weekday_sunday",20:"weekend_friday",21:"weekend_saturday",22:"dateFormat",23:"inclusiveEndDates",24:"topAxis",25:"axisFormat",26:"tickInterval",27:"excludes",28:"includes",29:"todayMarker",30:"title",31:"acc_title",32:"acc_title_value",33:"acc_descr",34:"acc_descr_value",35:"acc_descr_multiline_value",36:"section",38:"taskTxt",39:"taskData",40:"click",41:"callbackname",42:"callbackargs",43:"href"},productions_:[0,[3,3],[5,0],[5,2],[7,2],[7,1],[7,1],[7,1],[11,1],[11,1],[11,1],[11,1],[11,1],[11,1],[11,1],[19,1],[19,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,2],[9,2],[9,1],[9,1],[9,1],[9,2],[37,2],[37,3],[37,3],[37,4],[37,3],[37,4],[37,2],[44,2],[44,3],[44,3],[44,4],[44,3],[44,4],[44,2]],performAction:(0,e.K)(function(o,f,h,u,M,s,X){var c=s.length-1;switch(M){case 1:return s[c-1];case 2:this.$=[];break;case 3:s[c-1].push(s[c]),this.$=s[c-1];break;case 4:case 5:this.$=s[c];break;case 6:case 7:this.$=[];break;case 8:u.setWeekday("monday");break;case 9:u.setWeekday("tuesday");break;case 10:u.setWeekday("wednesday");break;case 11:u.setWeekday("thursday");break;case 12:u.setWeekday("friday");break;case 13:u.setWeekday("saturday");break;case 14:u.setWeekday("sunday");break;case 15:u.setWeekend("friday");break;case 16:u.setWeekend("saturday");break;case 17:u.setDateFormat(s[c].substr(11)),this.$=s[c].substr(11);break;case 18:u.enableInclusiveEndDates(),this.$=s[c].substr(18);break;case 19:u.TopAxis(),this.$=s[c].substr(8);break;case 20:u.setAxisFormat(s[c].substr(11)),this.$=s[c].substr(11);break;case 21:u.setTickInterval(s[c].substr(13)),this.$=s[c].substr(13);break;case 22:u.setExcludes(s[c].substr(9)),this.$=s[c].substr(9);break;case 23:u.setIncludes(s[c].substr(9)),this.$=s[c].substr(9);break;case 24:u.setTodayMarker(s[c].substr(12)),this.$=s[c].substr(12);break;case 27:u.setDiagramTitle(s[c].substr(6)),this.$=s[c].substr(6);break;case 28:this.$=s[c].trim(),u.setAccTitle(this.$);break;case 29:case 30:this.$=s[c].trim(),u.setAccDescription(this.$);break;case 31:u.addSection(s[c].substr(8)),this.$=s[c].substr(8);break;case 33:u.addTask(s[c-1],s[c]),this.$="task";break;case 34:this.$=s[c-1],u.setClickEvent(s[c-1],s[c],null);break;case 35:this.$=s[c-2],u.setClickEvent(s[c-2],s[c-1],s[c]);break;case 36:this.$=s[c-2],u.setClickEvent(s[c-2],s[c-1],null),u.setLink(s[c-2],s[c]);break;case 37:this.$=s[c-3],u.setClickEvent(s[c-3],s[c-2],s[c-1]),u.setLink(s[c-3],s[c]);break;case 38:this.$=s[c-2],u.setClickEvent(s[c-2],s[c],null),u.setLink(s[c-2],s[c-1]);break;case 39:this.$=s[c-3],u.setClickEvent(s[c-3],s[c-1],s[c]),u.setLink(s[c-3],s[c-2]);break;case 40:this.$=s[c-1],u.setLink(s[c-1],s[c]);break;case 41:case 47:this.$=s[c-1]+" "+s[c];break;case 42:case 43:case 45:this.$=s[c-2]+" "+s[c-1]+" "+s[c];break;case 44:case 46:this.$=s[c-3]+" "+s[c-2]+" "+s[c-1]+" "+s[c];break}},"anonymous"),table:[{3:1,4:[1,2]},{1:[3]},t(i,[2,2],{5:3}),{6:[1,4],7:5,8:[1,6],9:7,10:[1,8],11:17,12:n,13:r,14:a,15:k,16:p,17:U,18:rt,19:18,20:xt,21:G,22:pt,23:lt,24:gt,25:Dt,26:kt,27:W,28:Bt,29:Nt,30:zt,31:Ut,33:At,35:Ht,36:jt,37:24,38:Gt,40:Xt},t(i,[2,7],{1:[2,1]}),t(i,[2,3]),{9:36,11:17,12:n,13:r,14:a,15:k,16:p,17:U,18:rt,19:18,20:xt,21:G,22:pt,23:lt,24:gt,25:Dt,26:kt,27:W,28:Bt,29:Nt,30:zt,31:Ut,33:At,35:Ht,36:jt,37:24,38:Gt,40:Xt},t(i,[2,5]),t(i,[2,6]),t(i,[2,17]),t(i,[2,18]),t(i,[2,19]),t(i,[2,20]),t(i,[2,21]),t(i,[2,22]),t(i,[2,23]),t(i,[2,24]),t(i,[2,25]),t(i,[2,26]),t(i,[2,27]),{32:[1,37]},{34:[1,38]},t(i,[2,30]),t(i,[2,31]),t(i,[2,32]),{39:[1,39]},t(i,[2,8]),t(i,[2,9]),t(i,[2,10]),t(i,[2,11]),t(i,[2,12]),t(i,[2,13]),t(i,[2,14]),t(i,[2,15]),t(i,[2,16]),{41:[1,40],43:[1,41]},t(i,[2,4]),t(i,[2,28]),t(i,[2,29]),t(i,[2,33]),t(i,[2,34],{42:[1,42],43:[1,43]}),t(i,[2,40],{41:[1,44]}),t(i,[2,35],{43:[1,45]}),t(i,[2,36]),t(i,[2,38],{42:[1,46]}),t(i,[2,37]),t(i,[2,39])],defaultActions:{},parseError:(0,e.K)(function(o,f){if(f.recoverable)this.trace(o);else{var h=new Error(o);throw h.hash=f,h}},"parseError"),parse:(0,e.K)(function(o){var f=this,h=[0],u=[],M=[null],s=[],X=this.table,c="",z=0,l=0,x=0,_=2,H=1,N=s.slice.call(arguments,1),A=Object.create(this.lexer),V={yy:{}};for(var Zt in this.yy)Object.prototype.hasOwnProperty.call(this.yy,Zt)&&(V.yy[Zt]=this.yy[Zt]);A.setInput(o,V.yy),V.yy.lexer=A,V.yy.parser=this,typeof A.yylloc=="undefined"&&(A.yylloc={});var Qt=A.yylloc;s.push(Qt);var qe=A.options&&A.options.ranges;typeof V.yy.parseError=="function"?this.parseError=V.yy.parseError:this.parseError=Object.getPrototypeOf(this).parseError;function ts(ht){h.length=h.length-2*ht,M.length=M.length-ht,s.length=s.length-ht}(0,e.K)(ts,"popStack");function Ee(){var ht;return ht=u.pop()||A.lex()||H,typeof ht!="number"&&(ht instanceof Array&&(u=ht,ht=u.pop()),ht=f.symbols_[ht]||ht),ht}(0,e.K)(Ee,"lex");for(var at,he,Ct,yt,es,me,Yt={},se,bt,Ce,ie;;){if(Ct=h[h.length-1],this.defaultActions[Ct]?yt=this.defaultActions[Ct]:((at===null||typeof at=="undefined")&&(at=Ee()),yt=X[Ct]&&X[Ct][at]),typeof yt=="undefined"||!yt.length||!yt[0]){var ke="";ie=[];for(se in X[Ct])this.terminals_[se]&&se>_&&ie.push("'"+this.terminals_[se]+"'");A.showPosition?ke="Parse error on line "+(z+1)+`:
`+A.showPosition()+`
Expecting `+ie.join(", ")+", got '"+(this.terminals_[at]||at)+"'":ke="Parse error on line "+(z+1)+": Unexpected "+(at==H?"end of input":"'"+(this.terminals_[at]||at)+"'"),this.parseError(ke,{text:A.match,token:this.terminals_[at]||at,line:A.yylineno,loc:Qt,expected:ie})}if(yt[0]instanceof Array&&yt.length>1)throw new Error("Parse Error: multiple actions possible at state: "+Ct+", token: "+at);switch(yt[0]){case 1:h.push(at),M.push(A.yytext),s.push(A.yylloc),h.push(yt[1]),at=null,he?(at=he,he=null):(l=A.yyleng,c=A.yytext,z=A.yylineno,Qt=A.yylloc,x>0&&x--);break;case 2:if(bt=this.productions_[yt[1]][1],Yt.$=M[M.length-bt],Yt._$={first_line:s[s.length-(bt||1)].first_line,last_line:s[s.length-1].last_line,first_column:s[s.length-(bt||1)].first_column,last_column:s[s.length-1].last_column},qe&&(Yt._$.range=[s[s.length-(bt||1)].range[0],s[s.length-1].range[1]]),me=this.performAction.apply(Yt,[c,l,z,V.yy,yt[1],M,s].concat(N)),typeof me!="undefined")return me;bt&&(h=h.slice(0,-1*bt*2),M=M.slice(0,-1*bt),s=s.slice(0,-1*bt)),h.push(this.productions_[yt[1]][0]),M.push(Yt.$),s.push(Yt._$),Ce=X[h[h.length-2]][h[h.length-1]],h.push(Ce);break;case 3:return!0}}return!0},"parse")},L=function(){var g={EOF:1,parseError:(0,e.K)(function(f,h){if(this.yy.parser)this.yy.parser.parseError(f,h);else throw new Error(f)},"parseError"),setInput:(0,e.K)(function(o,f){return this.yy=f||this.yy||{},this._input=o,this._more=this._backtrack=this.done=!1,this.yylineno=this.yyleng=0,this.yytext=this.matched=this.match="",this.conditionStack=["INITIAL"],this.yylloc={first_line:1,first_column:0,last_line:1,last_column:0},this.options.ranges&&(this.yylloc.range=[0,0]),this.offset=0,this},"setInput"),input:(0,e.K)(function(){var o=this._input[0];this.yytext+=o,this.yyleng++,this.offset++,this.match+=o,this.matched+=o;var f=o.match(/(?:\r\n?|\n).*/g);return f?(this.yylineno++,this.yylloc.last_line++):this.yylloc.last_column++,this.options.ranges&&this.yylloc.range[1]++,this._input=this._input.slice(1),o},"input"),unput:(0,e.K)(function(o){var f=o.length,h=o.split(/(?:\r\n?|\n)/g);this._input=o+this._input,this.yytext=this.yytext.substr(0,this.yytext.length-f),this.offset-=f;var u=this.match.split(/(?:\r\n?|\n)/g);this.match=this.match.substr(0,this.match.length-1),this.matched=this.matched.substr(0,this.matched.length-1),h.length-1&&(this.yylineno-=h.length-1);var M=this.yylloc.range;return this.yylloc={first_line:this.yylloc.first_line,last_line:this.yylineno+1,first_column:this.yylloc.first_column,last_column:h?(h.length===u.length?this.yylloc.first_column:0)+u[u.length-h.length].length-h[0].length:this.yylloc.first_column-f},this.options.ranges&&(this.yylloc.range=[M[0],M[0]+this.yyleng-f]),this.yyleng=this.yytext.length,this},"unput"),more:(0,e.K)(function(){return this._more=!0,this},"more"),reject:(0,e.K)(function(){if(this.options.backtrack_lexer)this._backtrack=!0;else return this.parseError("Lexical error on line "+(this.yylineno+1)+`. You can only invoke reject() in the lexer when the lexer is of the backtracking persuasion (options.backtrack_lexer = true).
`+this.showPosition(),{text:"",token:null,line:this.yylineno});return this},"reject"),less:(0,e.K)(function(o){this.unput(this.match.slice(o))},"less"),pastInput:(0,e.K)(function(){var o=this.matched.substr(0,this.matched.length-this.match.length);return(o.length>20?"...":"")+o.substr(-20).replace(/\n/g,"")},"pastInput"),upcomingInput:(0,e.K)(function(){var o=this.match;return o.length<20&&(o+=this._input.substr(0,20-o.length)),(o.substr(0,20)+(o.length>20?"...":"")).replace(/\n/g,"")},"upcomingInput"),showPosition:(0,e.K)(function(){var o=this.pastInput(),f=new Array(o.length+1).join("-");return o+this.upcomingInput()+`
`+f+"^"},"showPosition"),test_match:(0,e.K)(function(o,f){var h,u,M;if(this.options.backtrack_lexer&&(M={yylineno:this.yylineno,yylloc:{first_line:this.yylloc.first_line,last_line:this.last_line,first_column:this.yylloc.first_column,last_column:this.yylloc.last_column},yytext:this.yytext,match:this.match,matches:this.matches,matched:this.matched,yyleng:this.yyleng,offset:this.offset,_more:this._more,_input:this._input,yy:this.yy,conditionStack:this.conditionStack.slice(0),done:this.done},this.options.ranges&&(M.yylloc.range=this.yylloc.range.slice(0))),u=o[0].match(/(?:\r\n?|\n).*/g),u&&(this.yylineno+=u.length),this.yylloc={first_line:this.yylloc.last_line,last_line:this.yylineno+1,first_column:this.yylloc.last_column,last_column:u?u[u.length-1].length-u[u.length-1].match(/\r?\n?/)[0].length:this.yylloc.last_column+o[0].length},this.yytext+=o[0],this.match+=o[0],this.matches=o,this.yyleng=this.yytext.length,this.options.ranges&&(this.yylloc.range=[this.offset,this.offset+=this.yyleng]),this._more=!1,this._backtrack=!1,this._input=this._input.slice(o[0].length),this.matched+=o[0],h=this.performAction.call(this,this.yy,this,f,this.conditionStack[this.conditionStack.length-1]),this.done&&this._input&&(this.done=!1),h)return h;if(this._backtrack){for(var s in M)this[s]=M[s];return!1}return!1},"test_match"),next:(0,e.K)(function(){if(this.done)return this.EOF;this._input||(this.done=!0);var o,f,h,u;this._more||(this.yytext="",this.match="");for(var M=this._currentRules(),s=0;s<M.length;s++)if(h=this._input.match(this.rules[M[s]]),h&&(!f||h[0].length>f[0].length)){if(f=h,u=s,this.options.backtrack_lexer){if(o=this.test_match(h,M[s]),o!==!1)return o;if(this._backtrack){f=!1;continue}else return!1}else if(!this.options.flex)break}return f?(o=this.test_match(f,M[u]),o!==!1?o:!1):this._input===""?this.EOF:this.parseError("Lexical error on line "+(this.yylineno+1)+`. Unrecognized text.
`+this.showPosition(),{text:"",token:null,line:this.yylineno})},"next"),lex:(0,e.K)(function(){var f=this.next();return f||this.lex()},"lex"),begin:(0,e.K)(function(f){this.conditionStack.push(f)},"begin"),popState:(0,e.K)(function(){var f=this.conditionStack.length-1;return f>0?this.conditionStack.pop():this.conditionStack[0]},"popState"),_currentRules:(0,e.K)(function(){return this.conditionStack.length&&this.conditionStack[this.conditionStack.length-1]?this.conditions[this.conditionStack[this.conditionStack.length-1]].rules:this.conditions.INITIAL.rules},"_currentRules"),topState:(0,e.K)(function(f){return f=this.conditionStack.length-1-Math.abs(f||0),f>=0?this.conditionStack[f]:"INITIAL"},"topState"),pushState:(0,e.K)(function(f){this.begin(f)},"pushState"),stateStackSize:(0,e.K)(function(){return this.conditionStack.length},"stateStackSize"),options:{"case-insensitive":!0},performAction:(0,e.K)(function(f,h,u,M){var s=M;switch(u){case 0:return this.begin("open_directive"),"open_directive";case 1:return this.begin("acc_title"),31;case 2:return this.popState(),"acc_title_value";case 3:return this.begin("acc_descr"),33;case 4:return this.popState(),"acc_descr_value";case 5:this.begin("acc_descr_multiline");break;case 6:this.popState();break;case 7:return"acc_descr_multiline_value";case 8:break;case 9:break;case 10:break;case 11:return 10;case 12:break;case 13:break;case 14:this.begin("href");break;case 15:this.popState();break;case 16:return 43;case 17:this.begin("callbackname");break;case 18:this.popState();break;case 19:this.popState(),this.begin("callbackargs");break;case 20:return 41;case 21:this.popState();break;case 22:return 42;case 23:this.begin("click");break;case 24:this.popState();break;case 25:return 40;case 26:return 4;case 27:return 22;case 28:return 23;case 29:return 24;case 30:return 25;case 31:return 26;case 32:return 28;case 33:return 27;case 34:return 29;case 35:return 12;case 36:return 13;case 37:return 14;case 38:return 15;case 39:return 16;case 40:return 17;case 41:return 18;case 42:return 20;case 43:return 21;case 44:return"date";case 45:return 30;case 46:return"accDescription";case 47:return 36;case 48:return 38;case 49:return 39;case 50:return":";case 51:return 6;case 52:return"INVALID"}},"anonymous"),rules:[/^(?:%%\{)/i,/^(?:accTitle\s*:\s*)/i,/^(?:(?!\n||)*[^\n]*)/i,/^(?:accDescr\s*:\s*)/i,/^(?:(?!\n||)*[^\n]*)/i,/^(?:accDescr\s*\{\s*)/i,/^(?:[\}])/i,/^(?:[^\}]*)/i,/^(?:%%(?!\{)*[^\n]*)/i,/^(?:[^\}]%%*[^\n]*)/i,/^(?:%%*[^\n]*[\n]*)/i,/^(?:[\n]+)/i,/^(?:\s+)/i,/^(?:%[^\n]*)/i,/^(?:href[\s]+["])/i,/^(?:["])/i,/^(?:[^"]*)/i,/^(?:call[\s]+)/i,/^(?:\([\s]*\))/i,/^(?:\()/i,/^(?:[^(]*)/i,/^(?:\))/i,/^(?:[^)]*)/i,/^(?:click[\s]+)/i,/^(?:[\s\n])/i,/^(?:[^\s\n]*)/i,/^(?:gantt\b)/i,/^(?:dateFormat\s[^#\n;]+)/i,/^(?:inclusiveEndDates\b)/i,/^(?:topAxis\b)/i,/^(?:axisFormat\s[^#\n;]+)/i,/^(?:tickInterval\s[^#\n;]+)/i,/^(?:includes\s[^#\n;]+)/i,/^(?:excludes\s[^#\n;]+)/i,/^(?:todayMarker\s[^\n;]+)/i,/^(?:weekday\s+monday\b)/i,/^(?:weekday\s+tuesday\b)/i,/^(?:weekday\s+wednesday\b)/i,/^(?:weekday\s+thursday\b)/i,/^(?:weekday\s+friday\b)/i,/^(?:weekday\s+saturday\b)/i,/^(?:weekday\s+sunday\b)/i,/^(?:weekend\s+friday\b)/i,/^(?:weekend\s+saturday\b)/i,/^(?:\d\d\d\d-\d\d-\d\d\b)/i,/^(?:title\s[^\n]+)/i,/^(?:accDescription\s[^#\n;]+)/i,/^(?:section\s[^\n]+)/i,/^(?:[^:\n]+)/i,/^(?::[^#\n;]+)/i,/^(?::)/i,/^(?:$)/i,/^(?:.)/i],conditions:{acc_descr_multiline:{rules:[6,7],inclusive:!1},acc_descr:{rules:[4],inclusive:!1},acc_title:{rules:[2],inclusive:!1},callbackargs:{rules:[21,22],inclusive:!1},callbackname:{rules:[18,19,20],inclusive:!1},href:{rules:[15,16],inclusive:!1},click:{rules:[24,25],inclusive:!1},INITIAL:{rules:[0,1,3,5,8,9,10,11,12,13,14,17,23,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52],inclusive:!0}}};return g}();y.lexer=L;function w(){this.yy={}}return(0,e.K)(w,"Parser"),w.prototype=y,y.Parser=w,new w}();ft.parser=ft;var v=ft;b.extend(P),b.extend(q),b.extend(tt);var D={friday:5,saturday:6},K="",Y="",et=void 0,st="",C=[],m=[],d=new Map,E=[],$=[],I="",R="",B=["active","done","crit","milestone","vert"],j=[],Q="",nt=!1,vt=!1,ot="sunday",mt="saturday",wt=0,ct=(0,e.K)(function(){E=[],$=[],I="",j=[],te=0,ue=void 0,ee=void 0,J=[],K="",Y="",R="",et=void 0,st="",C=[],m=[],nt=!1,vt=!1,wt=0,d=new Map,Q="",(0,O.IU)(),ot="sunday",mt="saturday"},"clear"),Ot=(0,e.K)(function(t){Q=t},"setDiagramId"),Mt=(0,e.K)(function(t){Y=t},"setAxisFormat"),ne=(0,e.K)(function(){return Y},"getAxisFormat"),re=(0,e.K)(function(t){et=t},"setTickInterval"),ae=(0,e.K)(function(){return et},"getTickInterval"),oe=(0,e.K)(function(t){st=t},"setTodayMarker"),ce=(0,e.K)(function(){return st},"getTodayMarker"),Jt=(0,e.K)(function(t){K=t},"setDateFormat"),qt=(0,e.K)(function(){nt=!0},"enableInclusiveEndDates"),$t=(0,e.K)(function(){return nt},"endDatesAreInclusive"),Wt=(0,e.K)(function(){vt=!0},"enableTopAxis"),Ft=(0,e.K)(function(){return vt},"topAxisEnabled"),St=(0,e.K)(function(t){R=t},"setDisplayMode"),Kt=(0,e.K)(function(){return R},"getDisplayMode"),Pt=(0,e.K)(function(){return K},"getDateFormat"),It=(0,e.K)((t,i)=>{const n=i.toLowerCase().split(/[\s,]+/).filter(r=>r!=="");return[...new Set([...t,...n])]},"mergeTokens"),Rt=(0,e.K)(function(t){C=It(C,t)},"setIncludes"),Vt=(0,e.K)(function(){return C},"getIncludes"),ye=(0,e.K)(function(t){m=It(m,t)},"setExcludes"),Me=(0,e.K)(function(){return m},"getExcludes"),Se=(0,e.K)(function(){return d},"getLinks"),Ke=(0,e.K)(function(t){I=t,E.push(t)},"addSection"),Ie=(0,e.K)(function(){return E},"getSections"),Le=(0,e.K)(function(){let t=be();const i=10;let n=0;for(;!t&&n<i;)t=be(),n++;return $=J,$},"getTasks"),ge=(0,e.K)(function(t,i,n,r){const a=t.format(i.trim()),k=t.format("YYYY-MM-DD");return r.includes(a)||r.includes(k)?!1:n.includes("weekends")&&(t.isoWeekday()===D[mt]||t.isoWeekday()===D[mt]+1)||n.includes(t.format("dddd").toLowerCase())?!0:n.includes(a)||n.includes(k)},"isInvalidDate"),Ae=(0,e.K)(function(t){ot=t},"setWeekday"),Ye=(0,e.K)(function(){return ot},"getWeekday"),Oe=(0,e.K)(function(t){mt=t},"setWeekend"),ve=(0,e.K)(function(t,i,n,r){if(!n.length||t.manualEndTime)return;let a;t.startTime instanceof Date?a=b(t.startTime):a=b(t.startTime,i,!0),a=a.add(1,"d");let k;t.endTime instanceof Date?k=b(t.endTime):k=b(t.endTime,i,!0);const[p,U]=$e(a,k,i,n,r);t.endTime=p.toDate(),t.renderEndTime=U},"checkTaskDates"),$e=(0,e.K)(function(t,i,n,r,a){let k=!1,p=null;const U=i.add(1e4,"d");for(;t<=i;){if(k||(p=i.toDate()),k=ge(t,n,r,a),k&&(i=i.add(1,"d"),i>U))throw new Error("Failed to find a valid date that was not excluded by `excludes` after 10,000 iterations.");t=t.add(1,"d")}return[i,p]},"fixTaskDates"),le=(0,e.K)(function(t,i,n){if(n=n.trim(),(0,e.K)(U=>{const rt=U.trim();return rt==="x"||rt==="X"},"isTimestampFormat")(i)&&/^\d+$/.test(n))return new Date(Number(n));const k=new RegExp("^after\\s+(?<ids>[\\d\\w- ]+)").exec(n);if(k!==null){let U=null;for(const xt of k.groups.ids.split(" ")){let G=Et(xt);G!==void 0&&(!U||G.endTime>U.endTime)&&(U=G)}if(U)return U.endTime;const rt=new Date;return rt.setHours(0,0,0,0),rt}let p=b(n,i.trim(),!0);if(p.isValid())return p.toDate();{F.R.debug("Invalid date:"+n),F.R.debug("With date format:"+i.trim());const U=new Date(n);if(U===void 0||isNaN(U.getTime())||U.getFullYear()<-1e4||U.getFullYear()>1e4)throw new Error("Invalid date:"+n);return U}},"getStartDate"),pe=(0,e.K)(function(t){const i=/^(\d+(?:\.\d+)?)([Mdhmswy]|ms)$/.exec(t.trim());return i!==null?[Number.parseFloat(i[1]),i[2]]:[NaN,"ms"]},"parseDuration"),Te=(0,e.K)(function(t,i,n,r=!1){n=n.trim();const k=new RegExp("^until\\s+(?<ids>[\\d\\w- ]+)").exec(n);if(k!==null){let G=null;for(const lt of k.groups.ids.split(" ")){let gt=Et(lt);gt!==void 0&&(!G||gt.startTime<G.startTime)&&(G=gt)}if(G)return G.startTime;const pt=new Date;return pt.setHours(0,0,0,0),pt}let p=b(n,i.trim(),!0);if(p.isValid())return r&&(p=p.add(1,"d")),p.toDate();let U=b(t);const[rt,xt]=pe(n);if(!Number.isNaN(rt)){const G=U.add(rt,xt);G.isValid()&&(U=G)}return U.toDate()},"getEndDate"),te=0,Lt=(0,e.K)(function(t){return t===void 0?(te=te+1,"task"+te):t},"parseId"),We=(0,e.K)(function(t,i){let n;i.substr(0,1)===":"?n=i.substr(1,i.length):n=i;const r=n.split(","),a={};de(r,a,B);for(let p=0;p<r.length;p++)r[p]=r[p].trim();let k="";switch(r.length){case 1:a.id=Lt(),a.startTime=t.endTime,k=r[0];break;case 2:a.id=Lt(),a.startTime=le(void 0,K,r[0]),k=r[1];break;case 3:a.id=Lt(r[0]),a.startTime=le(void 0,K,r[1]),k=r[2];break;default:}return k&&(a.endTime=Te(a.startTime,K,k,nt),a.manualEndTime=b(k,"YYYY-MM-DD",!0).isValid(),ve(a,K,m,C)),a},"compileData"),Fe=(0,e.K)(function(t,i){let n;i.substr(0,1)===":"?n=i.substr(1,i.length):n=i;const r=n.split(","),a={};de(r,a,B);for(let k=0;k<r.length;k++)r[k]=r[k].trim();switch(r.length){case 1:a.id=Lt(),a.startTime={type:"prevTaskEnd",id:t},a.endTime={data:r[0]};break;case 2:a.id=Lt(),a.startTime={type:"getStartDate",startData:r[0]},a.endTime={data:r[1]};break;case 3:a.id=Lt(r[0]),a.startTime={type:"getStartDate",startData:r[1]},a.endTime={data:r[2]};break;default:}return a},"parseData"),ue,ee,J=[],xe={},Pe=(0,e.K)(function(t,i){const n={section:I,type:I,processed:!1,manualEndTime:!1,renderEndTime:null,raw:{data:i},task:t,classes:[]},r=Fe(ee,i);n.raw.startTime=r.startTime,n.raw.endTime=r.endTime,n.id=r.id,n.prevTaskId=ee,n.active=r.active,n.done=r.done,n.crit=r.crit,n.milestone=r.milestone,n.vert=r.vert,n.vert?n.order=-1:(n.order=wt,wt++);const a=J.push(n);ee=n.id,xe[n.id]=a-1},"addTask"),Et=(0,e.K)(function(t){const i=xe[t];return J[i]},"findTaskById"),Re=(0,e.K)(function(t,i){const n={section:I,type:I,description:t,task:t,classes:[]},r=We(ue,i);n.startTime=r.startTime,n.endTime=r.endTime,n.id=r.id,n.active=r.active,n.done=r.done,n.crit=r.crit,n.milestone=r.milestone,n.vert=r.vert,ue=n,$.push(n)},"addTaskOrg"),be=(0,e.K)(function(){const t=(0,e.K)(function(n){const r=J[n];let a="";switch(J[n].raw.startTime.type){case"prevTaskEnd":{const k=Et(r.prevTaskId);r.startTime=k.endTime;break}case"getStartDate":a=le(void 0,K,J[n].raw.startTime.startData),a&&(J[n].startTime=a);break}return J[n].startTime&&(J[n].endTime=Te(J[n].startTime,K,J[n].raw.endTime.data,nt),J[n].endTime&&(J[n].processed=!0,J[n].manualEndTime=b(J[n].raw.endTime.data,"YYYY-MM-DD",!0).isValid(),ve(J[n],K,m,C))),J[n].processed},"compileTask");let i=!0;for(const[n,r]of J.entries())t(n),i=i&&r.processed;return i},"compileTasks"),Ve=(0,e.K)(function(t,i){let n=i;(0,O.D7)().securityLevel!=="loose"&&(n=(0,Z.J)(i)),t.split(",").forEach(function(r){Et(r)!==void 0&&(we(r,()=>{window.open(n,"_self")}),d.set(r,n))}),_e(t,"clickable")},"setLink"),_e=(0,e.K)(function(t,i){t.split(",").forEach(function(n){let r=Et(n);r!==void 0&&r.classes.push(i)})},"setClass"),Be=(0,e.K)(function(t,i,n){if((0,O.D7)().securityLevel!=="loose"||i===void 0)return;let r=[];if(typeof n=="string"){r=n.split(/,(?=(?:(?:[^"]*"){2})*[^"]*$)/);for(let k=0;k<r.length;k++){let p=r[k].trim();p.startsWith('"')&&p.endsWith('"')&&(p=p.substr(1,p.length-2)),r[k]=p}}r.length===0&&r.push(t),Et(t)!==void 0&&we(t,()=>{ut._K.runFunc(i,...r)})},"setClickFun"),we=(0,e.K)(function(t,i){j.push(function(){const n=Q?`${Q}-${t}`:t,r=document.querySelector(`[id="${n}"]`);r!==null&&r.addEventListener("click",function(){i()})},function(){const n=Q?`${Q}-${t}`:t,r=document.querySelector(`[id="${n}-text"]`);r!==null&&r.addEventListener("click",function(){i()})})},"pushFun"),Ne=(0,e.K)(function(t,i,n){t.split(",").forEach(function(r){Be(r,i,n)}),_e(t,"clickable")},"setClickEvent"),ze=(0,e.K)(function(t){j.forEach(function(i){i(t)})},"bindFunctions"),Ue={getConfig:(0,e.K)(()=>(0,O.D7)().gantt,"getConfig"),clear:ct,setDateFormat:Jt,getDateFormat:Pt,enableInclusiveEndDates:qt,endDatesAreInclusive:$t,enableTopAxis:Wt,topAxisEnabled:Ft,setAxisFormat:Mt,getAxisFormat:ne,setTickInterval:re,getTickInterval:ae,setTodayMarker:oe,getTodayMarker:ce,setAccTitle:O.SV,getAccTitle:O.iN,setDiagramTitle:O.ke,getDiagramTitle:O.ab,setDiagramId:Ot,setDisplayMode:St,getDisplayMode:Kt,setAccDescription:O.EI,getAccDescription:O.m7,addSection:Ke,getSections:Ie,getTasks:Le,addTask:Pe,findTaskById:Et,addTaskOrg:Re,setIncludes:Rt,getIncludes:Vt,setExcludes:ye,getExcludes:Me,setClickEvent:Ne,setLink:Ve,getLinks:Se,bindFunctions:ze,parseDuration:pe,isInvalidDate:ge,setWeekday:Ae,getWeekday:Ye,setWeekend:Oe};function de(t,i,n){let r=!0;for(;r;)r=!1,n.forEach(function(a){const k="^\\s*"+a+"\\s*$",p=new RegExp(k);t[0].match(p)&&(i[a]=!0,t.shift(1),r=!0)})}(0,e.K)(de,"getTaskTags"),b.extend(dt);var He=(0,e.K)(function(){F.R.debug("Something is calling, setConf, remove the call")},"setConf"),De={monday:T.ABi,tuesday:T.PGu,wednesday:T.GuW,thursday:T.Mol,friday:T.TUC,saturday:T.rGn,sunday:T.YPH},je=(0,e.K)((t,i)=>{let n=[...t].map(()=>-1/0),r=[...t].sort((k,p)=>k.startTime-p.startTime||k.order-p.order),a=0;for(const k of r)for(let p=0;p<n.length;p++)if(k.startTime>=n[p]){n[p]=k.endTime,k.order=p+i,p>a&&(a=p);break}return a},"getMaxIntersections"),Tt,fe=1e4,Ge=(0,e.K)(function(t,i,n,r){const a=(0,O.D7)().gantt;r.db.setDiagramId(i);const k=(0,O.D7)().securityLevel;let p;k==="sandbox"&&(p=(0,T.Ltv)("#i"+i));const U=k==="sandbox"?(0,T.Ltv)(p.nodes()[0].contentDocument.body):(0,T.Ltv)("body"),rt=k==="sandbox"?p.nodes()[0].contentDocument:document,xt=rt.getElementById(i);Tt=xt.parentElement.offsetWidth,Tt===void 0&&(Tt=1200),a.useWidth!==void 0&&(Tt=a.useWidth);const G=r.db.getTasks(),pt=G.filter(y=>!y.vert);let lt=[];for(const y of pt)lt.push(y.type);lt=Xt(lt);const gt={};let Dt=2*a.topPadding;if(r.db.getDisplayMode()==="compact"||a.displayMode==="compact"){const y={};for(const w of pt)y[w.section]===void 0?y[w.section]=[w]:y[w.section].push(w);let L=0;for(const w of Object.keys(y)){const g=je(y[w],L)+1;L+=g,Dt+=g*(a.barHeight+a.barGap),gt[w]=g}}else{Dt+=pt.length*(a.barHeight+a.barGap);for(const y of lt)gt[y]=pt.filter(L=>L.type===y).length}xt.setAttribute("viewBox","0 0 "+Tt+" "+Dt);const kt=U.select(`[id="${i}"]`),W=(0,T.w7C)().domain([(0,T.jkA)(G,function(y){return y.startTime}),(0,T.T9B)(G,function(y){return y.endTime})]).rangeRound([0,Tt-a.leftPadding-a.rightPadding]);function Bt(y,L){const w=y.startTime,g=L.startTime;let o=0;return w>g?o=1:w<g&&(o=-1),o}(0,e.K)(Bt,"taskCompare"),G.sort(Bt),Nt(G,Tt,Dt),(0,O.a$)(kt,Dt,Tt,a.useMaxWidth),kt.append("text").text(r.db.getDiagramTitle()).attr("x",Tt/2).attr("y",a.titleTopMargin).attr("class","titleText");function Nt(y,L,w){const g=a.barHeight,o=g+a.barGap,f=a.topPadding,h=a.leftPadding,u=(0,T.m4Y)().domain([0,lt.length]).range(["#00B9FA","#F95002"]).interpolate(T.bEH);Ut(o,f,h,L,w,y,r.db.getExcludes(),r.db.getIncludes()),Ht(h,f,L,w),zt(y,o,f,h,g,u,L,w),jt(o,f,h,g,u),Gt(h,f,L,w)}(0,e.K)(Nt,"makeGantt");function zt(y,L,w,g,o,f,h){y.sort((l,x)=>l.vert===x.vert?0:l.vert?1:-1);const u=y.filter(l=>!l.vert),s=[...new Set(u.map(l=>l.order))].map(l=>u.find(x=>x.order===l));kt.append("g").selectAll("rect").data(s).enter().append("rect").attr("x",0).attr("y",function(l,x){return x=l.order,x*L+w-2}).attr("width",function(){return h-a.rightPadding/2}).attr("height",L).attr("class",function(l){for(const[x,_]of lt.entries())if(l.type===_)return"section section"+x%a.numberSectionStyles;return"section section0"}).enter();const X=kt.append("g").selectAll("rect").data(y).enter(),c=r.db.getLinks();if(X.append("rect").attr("id",function(l){return i+"-"+l.id}).attr("rx",3).attr("ry",3).attr("x",function(l){return l.milestone?W(l.startTime)+g+.5*(W(l.endTime)-W(l.startTime))-.5*o:W(l.startTime)+g}).attr("y",function(l,x){return x=l.order,l.vert?a.gridLineStartPadding:x*L+w}).attr("width",function(l){return l.milestone?o:l.vert?.08*o:W(l.renderEndTime||l.endTime)-W(l.startTime)}).attr("height",function(l){return l.vert?u.length*(a.barHeight+a.barGap)+a.barHeight*2:o}).attr("transform-origin",function(l,x){return x=l.order,(W(l.startTime)+g+.5*(W(l.endTime)-W(l.startTime))).toString()+"px "+(x*L+w+.5*o).toString()+"px"}).attr("class",function(l){const x="task";let _="";l.classes.length>0&&(_=l.classes.join(" "));let H=0;for(const[A,V]of lt.entries())l.type===V&&(H=A%a.numberSectionStyles);let N="";return l.active?l.crit?N+=" activeCrit":N=" active":l.done?l.crit?N=" doneCrit":N=" done":l.crit&&(N+=" crit"),N.length===0&&(N=" task"),l.milestone&&(N=" milestone "+N),l.vert&&(N=" vert "+N),N+=H,N+=" "+_,x+N}),X.append("text").attr("id",function(l){return i+"-"+l.id+"-text"}).text(function(l){return l.task}).attr("font-size",a.fontSize).attr("x",function(l){let x=W(l.startTime),_=W(l.renderEndTime||l.endTime);if(l.milestone&&(x+=.5*(W(l.endTime)-W(l.startTime))-.5*o,_=x+o),l.vert)return W(l.startTime)+g;const H=this.getBBox().width;return H>_-x?_+H+1.5*a.leftPadding>h?x+g-5:_+g+5:(_-x)/2+x+g}).attr("y",function(l,x){return l.vert?a.gridLineStartPadding+u.length*(a.barHeight+a.barGap)+60:(x=l.order,x*L+a.barHeight/2+(a.fontSize/2-2)+w)}).attr("text-height",o).attr("class",function(l){const x=W(l.startTime);let _=W(l.endTime);l.milestone&&(_=x+o);const H=this.getBBox().width;let N="";l.classes.length>0&&(N=l.classes.join(" "));let A=0;for(const[Zt,Qt]of lt.entries())l.type===Qt&&(A=Zt%a.numberSectionStyles);let V="";return l.active&&(l.crit?V="activeCritText"+A:V="activeText"+A),l.done?l.crit?V=V+" doneCritText"+A:V=V+" doneText"+A:l.crit&&(V=V+" critText"+A),l.milestone&&(V+=" milestoneText"),l.vert&&(V+=" vertText"),H>_-x?_+H+1.5*a.leftPadding>h?N+" taskTextOutsideLeft taskTextOutside"+A+" "+V:N+" taskTextOutsideRight taskTextOutside"+A+" "+V+" width-"+H:N+" taskText taskText"+A+" "+V+" width-"+H}),(0,O.D7)().securityLevel==="sandbox"){let l;l=(0,T.Ltv)("#i"+i);const x=l.nodes()[0].contentDocument;X.filter(function(_){return c.has(_.id)}).each(function(_){var H=x.querySelector("#"+CSS.escape(i+"-"+_.id)),N=x.querySelector("#"+CSS.escape(i+"-"+_.id+"-text"));const A=H.parentNode;var V=x.createElement("a");V.setAttribute("xlink:href",c.get(_.id)),V.setAttribute("target","_top"),A.appendChild(V),V.appendChild(H),V.appendChild(N)})}}(0,e.K)(zt,"drawRects");function Ut(y,L,w,g,o,f,h,u){if(h.length===0&&u.length===0)return;let M,s;for(const{startTime:_,endTime:H}of f)(M===void 0||_<M)&&(M=_),(s===void 0||H>s)&&(s=H);if(!M||!s)return;if(b(s).diff(b(M),"year")>5){F.R.warn("The difference between the min and max time is more than 5 years. This will cause performance issues. Skipping drawing exclude days.");return}const X=r.db.getDateFormat(),c=[];let z=null,l=b(M);for(;l.valueOf()<=s;)r.db.isInvalidDate(l,X,h,u)?z?z.end=l:z={start:l,end:l}:z&&(c.push(z),z=null),l=l.add(1,"d");kt.append("g").selectAll("rect").data(c).enter().append("rect").attr("id",_=>i+"-exclude-"+_.start.format("YYYY-MM-DD")).attr("x",_=>W(_.start.startOf("day"))+w).attr("y",a.gridLineStartPadding).attr("width",_=>W(_.end.endOf("day"))-W(_.start.startOf("day"))).attr("height",o-L-a.gridLineStartPadding).attr("transform-origin",function(_,H){return(W(_.start)+w+.5*(W(_.end)-W(_.start))).toString()+"px "+(H*y+.5*o).toString()+"px"}).attr("class","exclude-range")}(0,e.K)(Ut,"drawExcludeDays");function At(y,L,w,g){if(w<=0||y>L)return 1/0;const o=L-y,f=b.duration({[g!=null?g:"day"]:w}).asMilliseconds();return f<=0?1/0:Math.ceil(o/f)}(0,e.K)(At,"getEstimatedTickCount");function Ht(y,L,w,g){var X;const o=r.db.getDateFormat(),f=r.db.getAxisFormat();let h;f?h=f:o==="D"?h="%d":h=(X=a.axisFormat)!=null?X:"%Y-%m-%d";let u=(0,T.l78)(W).tickSize(-g+L+a.gridLineStartPadding).tickFormat((0,T.DCK)(h));const s=/^([1-9]\d*)(millisecond|second|minute|hour|day|week|month)$/.exec(r.db.getTickInterval()||a.tickInterval);if(s!==null){const c=parseInt(s[1],10);if(isNaN(c)||c<=0)F.R.warn(`Invalid tick interval value: "${s[1]}". Skipping custom tick interval.`);else{const z=s[2],l=r.db.getWeekday()||a.weekday,x=W.domain(),_=x[0],H=x[1],N=At(_,H,c,z);if(N>fe)F.R.warn(`The tick interval "${c}${z}" would generate ${N} ticks, which exceeds the maximum allowed (${fe}). This may indicate an invalid date or time range. Skipping custom tick interval.`);else switch(z){case"millisecond":u.ticks(T.t6C.every(c));break;case"second":u.ticks(T.ucG.every(c));break;case"minute":u.ticks(T.wXd.every(c));break;case"hour":u.ticks(T.Agd.every(c));break;case"day":u.ticks(T.UAC.every(c));break;case"week":u.ticks(De[l].every(c));break;case"month":u.ticks(T.Ui6.every(c));break}}}if(kt.append("g").attr("class","grid").attr("transform","translate("+y+", "+(g-50)+")").call(u).selectAll("text").style("text-anchor","middle").attr("fill","#000").attr("stroke","none").attr("font-size",10).attr("dy","1em"),r.db.topAxisEnabled()||a.topAxis){let c=(0,T.tlR)(W).tickSize(-g+L+a.gridLineStartPadding).tickFormat((0,T.DCK)(h));if(s!==null){const z=parseInt(s[1],10);if(isNaN(z)||z<=0)F.R.warn(`Invalid tick interval value: "${s[1]}". Skipping custom tick interval.`);else{const l=s[2],x=r.db.getWeekday()||a.weekday,_=W.domain(),H=_[0],N=_[1];if(At(H,N,z,l)<=fe)switch(l){case"millisecond":c.ticks(T.t6C.every(z));break;case"second":c.ticks(T.ucG.every(z));break;case"minute":c.ticks(T.wXd.every(z));break;case"hour":c.ticks(T.Agd.every(z));break;case"day":c.ticks(T.UAC.every(z));break;case"week":c.ticks(De[x].every(z));break;case"month":c.ticks(T.Ui6.every(z));break}}}kt.append("g").attr("class","grid").attr("transform","translate("+y+", "+L+")").call(c).selectAll("text").style("text-anchor","middle").attr("fill","#000").attr("stroke","none").attr("font-size",10)}}(0,e.K)(Ht,"makeGrid");function jt(y,L){let w=0;const g=Object.keys(gt).map(o=>[o,gt[o]]);kt.append("g").selectAll("text").data(g).enter().append(function(o){const f=o[0].split(O.Y2.lineBreakRegex),h=-(f.length-1)/2,u=rt.createElementNS("http://www.w3.org/2000/svg","text");u.setAttribute("dy",h+"em");for(const[M,s]of f.entries()){const X=rt.createElementNS("http://www.w3.org/2000/svg","tspan");X.setAttribute("alignment-baseline","central"),X.setAttribute("x","10"),M>0&&X.setAttribute("dy","1em"),X.textContent=s,u.appendChild(X)}return u}).attr("x",10).attr("y",function(o,f){if(f>0)for(let h=0;h<f;h++)return w+=g[f-1][1],o[1]*y/2+w*y+L;else return o[1]*y/2+L}).attr("font-size",a.sectionFontSize).attr("class",function(o){for(const[f,h]of lt.entries())if(o[0]===h)return"sectionTitle sectionTitle"+f%a.numberSectionStyles;return"sectionTitle"})}(0,e.K)(jt,"vertLabels");function Gt(y,L,w,g){const o=r.db.getTodayMarker();if(o==="off")return;const f=kt.append("g").attr("class","today"),h=new Date,u=f.append("line");u.attr("x1",W(h)+y).attr("x2",W(h)+y).attr("y1",a.titleTopMargin).attr("y2",g-a.titleTopMargin).attr("class","today"),o!==""&&u.attr("style",o.replace(/,/g,";"))}(0,e.K)(Gt,"drawToday");function Xt(y){const L={},w=[];for(let g=0,o=y.length;g<o;++g)Object.prototype.hasOwnProperty.call(L,y[g])||(L[y[g]]=!0,w.push(y[g]));return w}(0,e.K)(Xt,"checkUnique")},"draw"),Xe={setConf:He,draw:Ge},Ze=(0,e.K)(t=>`
  .mermaid-main-font {
        font-family: ${t.fontFamily};
  }

  .exclude-range {
    fill: ${t.excludeBkgColor};
  }

  .section {
    stroke: none;
    opacity: 0.2;
  }

  .section0 {
    fill: ${t.sectionBkgColor};
  }

  .section2 {
    fill: ${t.sectionBkgColor2};
  }

  .section1,
  .section3 {
    fill: ${t.altSectionBkgColor};
    opacity: 0.2;
  }

  .sectionTitle0 {
    fill: ${t.titleColor};
  }

  .sectionTitle1 {
    fill: ${t.titleColor};
  }

  .sectionTitle2 {
    fill: ${t.titleColor};
  }

  .sectionTitle3 {
    fill: ${t.titleColor};
  }

  .sectionTitle {
    text-anchor: start;
    font-family: ${t.fontFamily};
  }


  /* Grid and axis */

  .grid .tick {
    stroke: ${t.gridColor};
    opacity: 0.8;
    shape-rendering: crispEdges;
  }

  .grid .tick text {
    font-family: ${t.fontFamily};
    fill: ${t.textColor};
  }

  .grid path {
    stroke-width: 0;
  }


  /* Today line */

  .today {
    fill: none;
    stroke: ${t.todayLineColor};
    stroke-width: 2px;
  }


  /* Task styling */

  /* Default task */

  .task {
    stroke-width: 2;
  }

  .taskText {
    text-anchor: middle;
    font-family: ${t.fontFamily};
  }

  .taskTextOutsideRight {
    fill: ${t.taskTextDarkColor};
    text-anchor: start;
    font-family: ${t.fontFamily};
  }

  .taskTextOutsideLeft {
    fill: ${t.taskTextDarkColor};
    text-anchor: end;
  }


  /* Special case clickable */

  .task.clickable {
    cursor: pointer;
  }

  .taskText.clickable {
    cursor: pointer;
    fill: ${t.taskTextClickableColor} !important;
    font-weight: bold;
  }

  .taskTextOutsideLeft.clickable {
    cursor: pointer;
    fill: ${t.taskTextClickableColor} !important;
    font-weight: bold;
  }

  .taskTextOutsideRight.clickable {
    cursor: pointer;
    fill: ${t.taskTextClickableColor} !important;
    font-weight: bold;
  }


  /* Specific task settings for the sections*/

  .taskText0,
  .taskText1,
  .taskText2,
  .taskText3 {
    fill: ${t.taskTextColor};
  }

  .task0,
  .task1,
  .task2,
  .task3 {
    fill: ${t.taskBkgColor};
    stroke: ${t.taskBorderColor};
  }

  .taskTextOutside0,
  .taskTextOutside2
  {
    fill: ${t.taskTextOutsideColor};
  }

  .taskTextOutside1,
  .taskTextOutside3 {
    fill: ${t.taskTextOutsideColor};
  }


  /* Active task */

  .active0,
  .active1,
  .active2,
  .active3 {
    fill: ${t.activeTaskBkgColor};
    stroke: ${t.activeTaskBorderColor};
  }

  .activeText0,
  .activeText1,
  .activeText2,
  .activeText3 {
    fill: ${t.taskTextDarkColor} !important;
  }


  /* Completed task */

  .done0,
  .done1,
  .done2,
  .done3 {
    stroke: ${t.doneTaskBorderColor};
    fill: ${t.doneTaskBkgColor};
    stroke-width: 2;
  }

  .doneText0,
  .doneText1,
  .doneText2,
  .doneText3 {
    fill: ${t.taskTextDarkColor} !important;
  }

  /* Done task text displayed outside the bar sits against the diagram background,
     not against the done-task bar, so it must use the outside/contrast color. */
  .doneText0.taskTextOutsideLeft,
  .doneText0.taskTextOutsideRight,
  .doneText1.taskTextOutsideLeft,
  .doneText1.taskTextOutsideRight,
  .doneText2.taskTextOutsideLeft,
  .doneText2.taskTextOutsideRight,
  .doneText3.taskTextOutsideLeft,
  .doneText3.taskTextOutsideRight {
    fill: ${t.taskTextOutsideColor} !important;
  }


  /* Tasks on the critical line */

  .crit0,
  .crit1,
  .crit2,
  .crit3 {
    stroke: ${t.critBorderColor};
    fill: ${t.critBkgColor};
    stroke-width: 2;
  }

  .activeCrit0,
  .activeCrit1,
  .activeCrit2,
  .activeCrit3 {
    stroke: ${t.critBorderColor};
    fill: ${t.activeTaskBkgColor};
    stroke-width: 2;
  }

  .doneCrit0,
  .doneCrit1,
  .doneCrit2,
  .doneCrit3 {
    stroke: ${t.critBorderColor};
    fill: ${t.doneTaskBkgColor};
    stroke-width: 2;
    cursor: pointer;
    shape-rendering: crispEdges;
  }

  .milestone {
    transform: rotate(45deg) scale(0.8,0.8);
  }

  .milestoneText {
    font-style: italic;
  }
  .doneCritText0,
  .doneCritText1,
  .doneCritText2,
  .doneCritText3 {
    fill: ${t.taskTextDarkColor} !important;
  }

  /* Done-crit task text outside the bar \u2014 same reasoning as doneText above. */
  .doneCritText0.taskTextOutsideLeft,
  .doneCritText0.taskTextOutsideRight,
  .doneCritText1.taskTextOutsideLeft,
  .doneCritText1.taskTextOutsideRight,
  .doneCritText2.taskTextOutsideLeft,
  .doneCritText2.taskTextOutsideRight,
  .doneCritText3.taskTextOutsideLeft,
  .doneCritText3.taskTextOutsideRight {
    fill: ${t.taskTextOutsideColor} !important;
  }

  .vert {
    stroke: ${t.vertLineColor};
  }

  .vertText {
    font-size: 15px;
    text-anchor: middle;
    fill: ${t.vertLineColor} !important;
  }

  .activeCritText0,
  .activeCritText1,
  .activeCritText2,
  .activeCritText3 {
    fill: ${t.taskTextDarkColor} !important;
  }

  .titleText {
    text-anchor: middle;
    font-size: 18px;
    fill: ${t.titleColor||t.textColor};
    font-family: ${t.fontFamily};
  }
`,"getStyles"),Qe=Ze,Je={parser:v,db:Ue,renderer:Xe,styles:Qe}}}]);
