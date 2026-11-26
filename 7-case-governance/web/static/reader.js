"use strict";
// All positions are Unicode code points in the selected verified text.
function readerToolbar(){const disabled=!state.text.available;return `<div class="reader-toolbar"><div class="reader-find"><input id="contract-search" type="search" maxlength="160" placeholder="在合同全文中查找" aria-label="查找合同原文" value="${esc(state.sourceQuery||'')}" ${disabled?'disabled':''}><span id="source-match-count" role="status"></span><button class="icon-btn" id="source-prev" aria-label="上一处匹配" disabled>‹</button><button class="icon-btn" id="source-next" aria-label="下一处匹配" disabled>›</button></div><div class="reader-actions"><button class="btn small" id="font-smaller" aria-label="缩小合同字号" ${disabled?'disabled':''}>A−</button><span id="reader-font-label">${state.readerFont||16}px</span><button class="btn small" id="font-larger" aria-label="放大合同字号" ${disabled?'disabled':''}>A＋</button><button class="btn small" id="reading-mode">${state.readerFocus?'退出专注':'专注阅读'}</button><button class="btn small" id="reader-recenter" ${disabled?'disabled':''}>返回引文</button></div></div>`;}

function searchPositions(text){
  const query=(state.sourceQuery||'').trim();
  if(state.readerCache?.text===text&&state.readerCache.query===query)return state.readerCache.hits;
  const hits=[];
  if(query){
    const re=new RegExp(query.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'),'giu');
    const boundaries=new Map([[0,0]]);let u=0,c=0;
    for(const ch of text){u+=ch.length;boundaries.set(u,++c);}
    for(const m of text.matchAll(re)){const start=boundaries.get(m.index),end=boundaries.get(m.index+m[0].length);if(start!=null&&end!=null)hits.push({start,end});if(hits.length===1000)break;}
  }
  state.readerCache={text,query,hits};return hits;
}

function scrollInReader(node){const reader=$('#contract-reader');if(!reader||!node)return;const a=node.getBoundingClientRect(),b=reader.getBoundingClientRect();reader.scrollTo({top:reader.scrollTop+a.top-b.top-Math.max(28,(reader.clientHeight-Math.min(a.height,reader.clientHeight-60))/2),behavior:'instant'});}

function paintReader(scroll=true,kind='evidence'){
  const reader=$('#contract-reader');if(!reader)return;
  const oldScroll=reader.scrollTop;reader.replaceChildren();reader.style.fontSize=(state.readerFont||16)+'px';
  const text=state.textMode==='raw'?state.text.raw_text:state.text.normalized_text;
  if(!state.text.available||text==null){const note=document.createElement('span');note.className='unavailable-text';note.textContent=state.text.message;reader.append(note);return;}
  const chars=Array.from(text),hits=searchPositions(text);state.sourceIndex=hits.length?((state.sourceIndex||0)%hits.length+hits.length)%hits.length:0;
  const quote=state.text.quotes?.[state.qid]?.[state.quoteIndex];
  const start=state.textMode==='raw'?quote?.raw_start:quote?.normalized_start,end=state.textMode==='raw'?quote?.raw_end:quote?.normalized_end;
  const valid=quote?.position_matches&&start!=null&&end!=null;
  function segment(a,b,parent){let cursor=a;for(let i=0;i<hits.length;i++){const h=hits[i];if(h.end<=a||h.start>=b)continue;const lo=Math.max(h.start,a),hi=Math.min(h.end,b);parent.append(document.createTextNode(chars.slice(cursor,lo).join('')));const mark=document.createElement('mark');mark.className='source-hit'+(i===state.sourceIndex?' current':'');mark.dataset.sourceHit=i;mark.textContent=chars.slice(lo,hi).join('');parent.append(mark);cursor=hi;}parent.append(document.createTextNode(chars.slice(cursor,b).join('')));}
  if(valid){segment(0,start,reader);const mark=document.createElement('mark');mark.id='active-evidence';segment(start,end,mark);reader.append(mark);segment(end,chars.length,reader);}else segment(0,chars.length,reader);
  const counter=$('#source-match-count');if(counter)counter.textContent=(state.sourceQuery||'').trim()?(hits.length?`${state.sourceIndex+1} / ${hits.length}${hits.length===1000?'（显示上限）':''}`:'未找到'):'';
  for(const id of ['source-prev','source-next'])if($('#'+id))$('#'+id).disabled=!hits.length;
  if($('#reader-recenter'))$('#reader-recenter').disabled=!valid;
  const coordinates=$('#reader-coordinates');if(coordinates)coordinates.textContent=`${chars.length.toLocaleString()}字符 · ${state.textMode==='raw'?'原始TXT':'规范化文本'}${valid?` · 当前引文 [${start}, ${end})`:' · 本条款无可定位引文'}`;
  if(!scroll)reader.scrollTop=oldScroll;
  if(scroll||kind==='search')requestAnimationFrame(()=>scrollInReader(kind==='search'?reader.querySelector('.source-hit.current'):$('#active-evidence')));
}

function readerEscape(e){if(e.key==='Escape'&&state.readerFocus){state.readerFocus=false;render();$('#reading-mode')?.focus();}}
function bindReader(){
  const input=$('#contract-search');if(!input)return;
  let timer;
  function find(){clearTimeout(timer);state.sourceQuery=input.value;state.sourceIndex=0;paintReader(false,'search');}
  input.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(find,150);});
  input.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();clearTimeout(timer);const changed=state.sourceQuery!==input.value;state.sourceQuery=input.value;state.sourceIndex=changed?0:e.shiftKey?(state.sourceIndex||0)-1:(state.sourceIndex||0)+1;paintReader(false,'search');}});
  for(const [id,step] of [['source-prev',-1],['source-next',1]])$('#'+id).addEventListener('click',()=>{state.sourceIndex=(state.sourceIndex||0)+step;paintReader(false,'search');});
  for(const [id,step] of [['font-smaller',-1],['font-larger',1]])$('#'+id).addEventListener('click',()=>{state.readerFont=Math.min(22,Math.max(14,(state.readerFont||16)+step));$('#contract-reader').style.fontSize=state.readerFont+'px';$('#reader-font-label').textContent=state.readerFont+'px';});
  $('#reading-mode').addEventListener('click',()=>{state.readerFocus=!state.readerFocus;render();$('#reading-mode')?.focus();});
  $('#reader-recenter').addEventListener('click',()=>scrollInReader($('#active-evidence')));
  document.addEventListener('keydown',readerEscape);
}
