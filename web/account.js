'use strict';
(() => {
  const get = id => document.getElementById(id);
  const statuses={completed:'已完成',running:'运行中',stopped:'已停止',failed:'失败',interrupted:'中断',DONE:'已完成',ABORTED:'已中止',TIMEOUT:'超时'};
  const formatTime=value=>{const date=new Date(value);return Number.isNaN(date.getTime())?value:new Intl.DateTimeFormat('zh-CN',{dateStyle:'medium',timeStyle:'medium',timeZone:'Asia/Shanghai'}).format(date);};
  let csrf = '', registering = false;
  async function call(path, payload) {
    const response = await fetch(path, payload === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':csrf},body:JSON.stringify(payload)});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || '操作未完成');
    if (result.csrf) csrf = result.csrf;
    return result;
  }
  if (get('auth-form')) {
    call('/api/account').then(info => { get('software-name').textContent=info.software;document.title=info.software+' · 登录';get('mode-note').textContent=info.mode==='local'?'当前为本机服务。其他电脑需使用部署后的站点地址。':'当前为在线工作台。'; }).catch(e=>get('auth-status').textContent=e.message);
    function tab(value) {
      registering=value;get('login-tab').setAttribute('aria-selected',String(!value));get('register-tab').setAttribute('aria-selected',String(value));
      ['display-row','confirm-row','password-hint'].forEach(id=>get(id).hidden=!value);
      get('password-confirm').required=value;get('password').autocomplete=value?'new-password':'current-password';get('password').minLength=value?12:1;
      get('form-title').textContent=value?'创建个人工作区':'进入你的工作台';get('submit-auth').textContent=value?'注册并进入':'登录';get('auth-status').textContent='';
    }
    get('login-tab').onclick=()=>tab(false);get('register-tab').onclick=()=>tab(true);
    get('auth-form').addEventListener('submit',async event=>{
      event.preventDefault();get('auth-status').textContent='';const button=get('submit-auth');button.disabled=true;
      try {
        if(registering&&get('password').value!==get('password-confirm').value)throw new Error('两次输入的密码不一致');
        // 每次提交取当前令牌，处理其他标签页登录后令牌旋转的情况。
        await call('/api/account');
        await call('/api/account/'+(registering?'register':'login'),{username:get('username').value,password:get('password').value,display_name:get('display-name').value.trim()||get('username').value});
        const next=new URLSearchParams(location.search).get('next');
        location.replace(['/','/data.html','/engineering.html','/workbench.html'].includes(next)?next:'/');
      }catch(e){get('auth-status').textContent=e.message;button.disabled=false;}
    });
  }
  if (get('data-rows')) {
    const actions={register:'创建账户',login:'登录',logout:'退出',password_changed:'修改密码',workspace_export:'导出工作区',start:'运行仿真',run:'运行巡检仿真',benchmark:'调度对照实验',comparisons:'巡检配对实验','workflow/assets':'登记资产','workflow/defects':'登记缺陷','workflow/transition':'缺陷流转','engineering/records':'新建工程记录'};
    async function load(){
      try{
        const data=await call('/api/account/data?q='+encodeURIComponent(get('data-search').value));
        get('data-capacity').textContent='已使用 '+(data.bytes_used/1048576).toFixed(2)+' MB / '+(data.bytes_limit/1048576).toFixed(0)+' MB · 记录上限 '+data.record_limit+' 条';
        get('record-count').textContent='已保存 '+data.total_records+' 条，匹配 '+data.matching+' 条。最多显示最近100条。';
        get('collections').replaceChildren(...data.collections.map(item=>{const el=document.createElement('article'),label=document.createElement('span'),value=document.createElement('strong');label.textContent=item.name;value.textContent=item.count;el.append(label,value);return el;}));
        get('data-rows').replaceChildren(...data.records.map(row=>{const tr=document.createElement('tr');const name=document.createElement('td');name.textContent=row.name;const id=document.createElement('small');id.textContent=row.id;name.append(id);tr.append(name);for(const value of [formatTime(row.time),statuses[row.status]||row.status]){const td=document.createElement('td');td.textContent=value;tr.append(td);}const td=document.createElement('td'),link=document.createElement('a');link.href=row.download;link.textContent='下载结果';link.download=row.id+'.zip';td.append(link);tr.append(td);return tr;}));
        get('data-status').textContent=data.records.length?'':'还没有匹配的记录。可返回工作台完成一次运行。';
        get('audit-events').replaceChildren(...data.audit.map(row=>{const li=document.createElement('li');li.textContent=formatTime(row.time)+' · '+(actions[row.action]||row.action);return li;}));
      }catch(e){get('data-status').textContent=e.message;}
    }
    get('search-form').addEventListener('submit',event=>{event.preventDefault();load();});
    get('password-form').addEventListener('submit',async event=>{event.preventDefault();try{await call('/api/account');await call('/api/account/password',{current_password:get('current-password').value,new_password:get('new-password').value});get('password-form').reset();get('password-status').textContent='密码已修改，其他登录会话已失效。';}catch(e){get('password-status').textContent=e.message;}});
    Promise.resolve(window.ldAccountReady).then(info=>{if(info?.user){csrf=info.csrf;get('password-username').value=info.user.username;load();}});
  }
})();
