const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const titles = {today:'早上好。',chat:'一起想清楚。',memory:'你的长期记忆。',inbox:'收下，然后整理。',settings:'由你掌控。'};
let currentFile = null, questions = [], questionIndex = 0;

function toast(message){const el=$('#toast');el.textContent=message;el.classList.add('show');setTimeout(()=>el.classList.remove('show'),2200)}
async function api(path, options={}){const response=await fetch(path,{headers:{...(options.body instanceof FormData?{}:{'Content-Type':'application/json'}),...(options.headers||{})},...options});if(!response.ok)throw new Error((await response.json().catch(()=>({detail:'请求失败'}))).detail||'请求失败');return response.json()}

$$('.nav').forEach(button=>button.onclick=()=>{const id=button.dataset.view;$$('.nav,.view').forEach(el=>el.classList.remove('active'));button.classList.add('active');$('#'+id).classList.add('active');$('#page-title').textContent=titles[id];$('.sidebar').classList.remove('open');if(id==='memory')loadFiles();if(id==='settings')loadUsage()});
$('.mobile-menu').onclick=()=>$('.sidebar').classList.toggle('open');

$('#chat-form').onsubmit=async event=>{event.preventDefault();const input=$('#chat-input'),text=input.value.trim();if(!text)return;appendMessage(text,'user');input.value='';const waiting=appendMessage('正在翻阅相关记忆…','assistant');try{const result=await api('/api/chat',{method:'POST',body:JSON.stringify({message:text})});waiting.textContent=result.answer;$('#sources').innerHTML=result.sources.map(s=>`<span>${escapeHtml(s)}</span>`).join('')}catch(error){waiting.textContent='暂时无法处理：'+error.message}};
function appendMessage(text,role){const el=document.createElement('div');el.className='message '+role;el.textContent=text;$('#messages').append(el);el.scrollIntoView({behavior:'smooth'});return el}

async function loadFiles(){const data=await api('/api/memory');$('#files').innerHTML=data.files.map(path=>`<button class="file-item ${path===currentFile?'active':''}" data-file="${escapeHtml(path)}">${escapeHtml(path)}</button>`).join('');$$('.file-item').forEach(el=>el.onclick=()=>openFile(el.dataset.file))}
async function openFile(path){const data=await api('/api/memory/'+encodeURI(path));currentFile=path;$('#current-file').textContent=path;$('#memory-content').value=data.content;$('#save-memory').disabled=false;loadFiles()}
$('#save-memory').onclick=async()=>{try{await api('/api/memory/'+encodeURI(currentFile),{method:'PUT',body:JSON.stringify({content:$('#memory-content').value})});toast('记忆已保存')}catch(error){toast(error.message)}};
$('#search-button').onclick=async()=>{const q=$('#memory-search').value.trim();if(!q)return loadFiles();const data=await api('/api/search?q='+encodeURIComponent(q));$('#files').innerHTML=data.results.map(hit=>`<button class="file-item" data-file="${escapeHtml(hit.path)}">${escapeHtml(hit.path)} · ${hit.score}</button>`).join('');$$('.file-item').forEach(el=>el.onclick=()=>openFile(el.dataset.file))};

const drop=$('#dropzone'),fileInput=$('#file-input');['dragenter','dragover'].forEach(type=>drop.addEventListener(type,e=>{e.preventDefault();drop.classList.add('drag')}));['dragleave','drop'].forEach(type=>drop.addEventListener(type,e=>{e.preventDefault();drop.classList.remove('drag')}));drop.addEventListener('drop',e=>upload(e.dataTransfer.files[0]));fileInput.onchange=()=>upload(fileInput.files[0]);
async function upload(file){if(!file)return;const data=new FormData();data.append('file',file,file.name);$('#upload-result').textContent='正在归档与提取…';try{const result=await api('/api/upload',{method:'POST',body:data});$('#upload-result').textContent=result.duplicate?'这个文件已经收录过。':`已归档：${result.stored_path}\n${result.extracted_text.slice(0,500)}`}catch(error){$('#upload-result').textContent=error.message}}

$('#refresh-morning').onclick=async()=>{const result=await api('/api/reports/morning',{method:'POST'});$('#report-output').textContent=result.content;$('#report-output').classList.remove('hidden')};
$('#start-interview').onclick=async()=>{questions=(await api('/api/interview')).questions;questionIndex=0;showQuestion();$('#interview-dialog').showModal()};
function showQuestion(){const item=questions[questionIndex];$('#interview-domain').textContent=`${questionIndex+1} / ${questions.length} · ${item.domain}`;$('#interview-question').textContent=item.question;$('#interview-answer').value='';$('.progress i').style.width=`${(questionIndex+1)/questions.length*100}%`}
async function nextQuestion(save=true){const answer=$('#interview-answer').value.trim();if(save&&answer)await api('/api/chat',{method:'POST',body:JSON.stringify({message:answer})});questionIndex++;if(questionIndex>=questions.length){$('#interview-dialog').close();toast('采访完成，初版记忆已生成');return}showQuestion()}
$('#next-question').onclick=()=>nextQuestion(true);$('#skip-question').onclick=()=>nextQuestion(false);$('.dialog-close').onclick=()=>$('#interview-dialog').close();

const templates={OpenAI:'https://api.openai.com/v1',DeepSeek:'https://api.deepseek.com/v1','通义千问':'https://dashscope.aliyuncs.com/compatible-mode/v1',Kimi:'https://api.moonshot.cn/v1','智谱':'https://open.bigmodel.cn/api/paas/v4',Gemini:'https://generativelanguage.googleapis.com/v1beta/openai',Ollama:'http://localhost:11434/v1'};
$('#provider-template').onchange=e=>$('#provider-url').value=templates[e.target.value];
$('#provider-form').onsubmit=async e=>{e.preventDefault();const name=$('#provider-template').value,model=$('#provider-model').value.trim();if(!model)return toast('请填写模型名称');await api('/api/providers',{method:'POST',body:JSON.stringify({name,base_url:$('#provider-url').value,api_key:$('#provider-key').value,models:[model]})});await api('/api/routes',{method:'POST',body:JSON.stringify({task:'fast',provider:name,model})});await api('/api/routes',{method:'POST',body:JSON.stringify({task:'smart',provider:name,model})});$('#provider-key').value='';toast('供应商与 fast/smart 路由已保存')};
async function loadUsage(){const data=await api('/api/usage');$('#tokens').textContent=Number(data.prompt_tokens)+Number(data.completion_tokens);$('#cost').textContent='¥'+Number(data.estimated_cost).toFixed(2)}
function escapeHtml(value){return String(value).replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]))}
const now=new Date();$('#eyebrow').textContent=`${now.getFullYear()} · ${now.toLocaleDateString('zh-CN',{weekday:'long'})}`;
