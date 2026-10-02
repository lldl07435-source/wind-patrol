'use strict';
(() => {
  const ldFetch = window.fetch.bind(window);
  window.fetch = async (...args) => {
    const response = await ldFetch(...args);
    const url = typeof args[0] === 'string' ? args[0] : args[0]?.url || '';
    if (response.status === 401 && url.startsWith('/api/') && !url.startsWith('/api/account/login')) {
      location.replace('/login.html?next=' + encodeURIComponent(location.pathname));
    }
    return response;
  };
  window.ldAccountReady = ldFetch('/api/account').then(r => r.json()).then(info => {
    if (!info.user) { location.replace('/login.html?next=' + encodeURIComponent(location.pathname)); return info; }
    const bar = document.createElement('div'); bar.className = 'account-bar';
    const name = document.createElement('span'); name.textContent = info.user.display_name;
    const link = document.createElement('a'); link.href = '/data.html'; link.textContent = '我的数据';
    const exit = document.createElement('button'); exit.type = 'button'; exit.textContent = '退出登录';
    exit.addEventListener('click', async () => {
      exit.disabled = true;
      try {
        const current = await ldFetch('/api/account').then(r => r.json());
        const response = await ldFetch('/api/account/logout', {method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':current.csrf},body:'{}'});
        if (!response.ok) throw new Error('退出未完成，请刷新后重试');
        location.replace('/login.html');
      } catch (error) { exit.disabled = false; exit.textContent = error.message; }
    });
    bar.append(name,link,exit); document.body.prepend(bar);
    const fitSidebar=()=>{const sidebar=document.querySelector('aside');const width=sidebar&&getComputedStyle(sidebar).position==='fixed'?sidebar.getBoundingClientRect().width:0;bar.style.marginLeft=width+'px';};fitSidebar();window.addEventListener('resize',fitSidebar);return info;
  });
})();
