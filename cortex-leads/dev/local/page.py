"""HTML thuần cho Messenger giả. Chữ của khách/Page luôn chèn bằng textContent (không innerHTML)."""

PAGE_HTML = r"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Messenger giả (dev)</title>
<style>
:root{--bg:#f4f5f7;--fg:#1c1e21;--card:#fff;--line:#d8dbe0;--blue:#1877f2;--mute:#65676b;--warn:#8a5a00}
@media (prefers-color-scheme:dark){:root{--bg:#18191a;--fg:#e4e6eb;--card:#242526;--line:#3e4042;--mute:#b0b3b8;--warn:#f0b64a}}
*{box-sizing:border-box}body{margin:0;font:15px/1.4 system-ui,sans-serif;background:var(--bg);color:var(--fg)}
header{padding:10px 16px;background:var(--blue);color:#fff;display:flex;gap:16px;align-items:baseline;flex-wrap:wrap}
header b{font-size:17px}header a{color:#fff}
.wrap{display:grid;grid-template-columns:200px 1fr 280px;gap:12px;padding:12px;max-width:1200px;margin:auto}
@media (max-width:860px){.wrap{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px}
.cust{padding:6px 8px;border-radius:6px;cursor:pointer}.cust.on{background:var(--blue);color:#fff}
#log{height:420px;overflow:auto;display:flex;flex-direction:column;gap:6px;padding:4px}
.m{max-width:75%;padding:7px 11px;border-radius:14px;white-space:pre-wrap;word-break:break-word}
.m small{display:block;font-size:11px;opacity:.75}
.customer{align-self:flex-end;background:var(--blue);color:#fff}
.staff{align-self:flex-start;background:#e4e6eb;color:#000}
.cortex{align-self:flex-start;background:#d6f5dc;color:#000;border:1px solid #6cc47c}
textarea{width:100%;height:60px;font:inherit;padding:6px;background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:6px}
button,input{font:inherit;padding:6px 10px;border-radius:6px;border:1px solid var(--line);background:var(--card);color:var(--fg);cursor:pointer}
button.p{background:var(--blue);color:#fff;border-color:var(--blue)}
.row{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}
dl{margin:0;display:grid;grid-template-columns:auto 1fr;gap:2px 8px;font-size:13px}dt{color:var(--mute)}dd{margin:0;word-break:break-word}
.warn{color:var(--warn);font-size:12px}#msg{font-size:13px;margin-top:6px;min-height:18px}
</style></head><body>
<header><b>Messenger giả</b><span>Page: __PAGE__ (công cụ dev, không phải Facebook)</span>
<a href="__CORE__/staff/login" target="_blank">Trang nhân viên</a></header>
<div class="wrap">
 <div class="card"><b>Khách</b><div id="custs"></div>
  <div class="row"><input id="newname" placeholder="Tên hiển thị" size="12"><button id="add">Tạo</button></div></div>
 <div class="card"><b id="title">Chọn hoặc tạo một khách</b><div id="log"></div>
  <textarea id="txt" placeholder="Gõ tin nhắn..."></textarea>
  <div class="warn">Hệ thống không trả lời từng tin: nó chờ khách nhắn xong rồi mới đáp. Khách nhắn xong ~30 giây mà chưa
   ai trả lời thì có phản hồi (chế độ auto) hoặc nháp ở đầu Trang nhân viên (chế độ manual); nhân viên đang trả lời thì
   hệ thống im. Thử: gửi "xin chào", chờ ~30 giây. Khách hỏi giá rồi im thì tua giờ: gửi "Khoá IELTS giá bao nhiêu ạ?"
   &rarr; Tua 21h &rarr; Chạy đồng hồ ngay.</div>
  <div class="row"><button class="p" id="asCust">Gửi như khách</button>
   <button id="asStaff">Trả lời như nhân viên (hộp thư Page)</button></div><div id="msg"></div></div>
 <div class="card"><b>Trạng thái hội thoại (đọc từ DB)</b><dl id="st"></dl>
  <hr style="border:0;border-top:1px solid var(--line)">
  <b>Công cụ dev</b><div class="warn">Tua thời gian lùi MỌI mốc giờ của hội thoại này trong DB local để giả lập khách im lâu. Không dùng ở đâu khác.</div>
  <div class="row" id="rw"></div>
  <div class="row"><button class="p" id="tick">Chạy đồng hồ ngay</button></div></div>
</div>
<script>
let psid=null;const $=id=>document.getElementById(id);
const note=t=>{$('msg').textContent=t};
async function api(path,body){const r=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});
 const j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(j.detail||r.status);return j}
const WHO={customer:'Khách',staff:'Nhân viên (hộp thư Page)',cortex:'Page gửi (qua Cortex)'};
function fmt(iso){return iso?new Date(iso).toLocaleString('vi-VN'):'-'}
async function custs(){const l=await api('/api/customers');const box=$('custs');box.replaceChildren();
 for(const c of l){const d=document.createElement('div');d.className='cust'+(c.psid===psid?' on':'');
  d.textContent=c.name+' ('+c.psid+')';d.onclick=()=>{psid=c.psid;location.hash=psid;refresh(true)};box.append(d)}}
async function chat(force){if(!psid)return;const j=await api('/api/chat/'+psid);const log=$('log');
 const near=log.scrollTop+log.clientHeight>=log.scrollHeight-40;log.replaceChildren();
 for(const m of j.messages){const d=document.createElement('div');d.className='m '+m.who;
  const s=document.createElement('small');s.textContent=WHO[m.who]+(m.actor?' - '+m.actor:'')+' - '+fmt(m.at);
  const t=document.createElement('span');t.textContent=m.text;d.append(s,t);log.append(d)}
 if(near||force)log.scrollTop=log.scrollHeight;
 const st=$('st');st.replaceChildren();const s=j.status;
 const rows=s?[['Trạng thái',s.state],['Lần chạm',s.touches],['Ý định',s.intent||'-'],['Ngày hẹn',s.promised_date||'-'],
  ['Cửa sổ kênh',s.window],['Khách nhắn cuối',fmt(s.last_customer_at)],['Đồng hồ kế',fmt(s.next_check_at)],
  ['Đã chuyển ngoài kênh',s.offchannel_contact?'có':'không'],['Job',s.jobs.join('; ')||'-'],
  ['Nháp',s.drafts.join('; ')||'-'],['Outbox',s.outbox.join('; ')||'-']]:[['','(chưa có hội thoại trong lõi)']];
 for(const [k,v] of rows){const a=document.createElement('dt'),b=document.createElement('dd');a.textContent=k;b.textContent=v;st.append(a,b)}}
async function refresh(force){try{await custs();await chat(force);const c=(await api('/api/customers')).find(x=>x.psid===psid);
 $('title').textContent=c?c.name+' ('+c.psid+')':'Chọn hoặc tạo một khách'}catch(e){note(String(e))}}
async function send(as){if(!psid){note('Chọn khách trước');return}const t=$('txt').value.trim();if(!t)return;
 try{await api('/api/send',{psid,text:t,as});$('txt').value='';note('Đã gửi');refresh(true)}catch(e){note('Lỗi: '+e.message)}}
$('asCust').onclick=()=>send('customer');$('asStaff').onclick=()=>send('staff');
$('add').onclick=async()=>{const c=await api('/api/customers',{name:$('newname').value});$('newname').value='';psid=c.psid;location.hash=psid;refresh(true)};
$('tick').onclick=async()=>{note('Đang chạy đồng hồ...');try{const r=await api('/api/tick',{});
 note('Đồng hồ: '+JSON.stringify(r));refresh()}catch(e){note('Lỗi: '+e.message)}};
for(const [h,l] of [[1,'1 giờ'],[6,'6 giờ'],[21,'21 giờ'],[25,'25 giờ'],[192,'8 ngày']]){const b=document.createElement('button');
 b.textContent='Tua '+l;b.onclick=async()=>{if(!psid){note('Chọn khách trước');return}
  try{await api('/api/rewind',{psid,hours:h});note('Đã tua '+l+'. Bấm "Chạy đồng hồ ngay".');refresh()}catch(e){note('Lỗi: '+e.message)}};$('rw').append(b)}
psid=location.hash.slice(1)||null;refresh(true);setInterval(refresh,2000);
</script></body></html>"""
