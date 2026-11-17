(function () {
  var d = document.body.dataset, token = ''; try { token = localStorage.getItem('stairs-chat') || ''; } catch (e) {}
  var last = 0, timer = null, greet = d.greeting || 'Hi! How can we help?', title = d.chatTitle || 'Chat with us';
  var box = document.createElement('div'); box.id = 'chat';
  box.innerHTML = '<section id="chatpanel" hidden><div class="chathead"><strong></strong><button type="button" id="chatx" aria-label="Close">×</button></div><div id="chatlog" aria-live="polite"></div><form id="chatform"><input id="chatin" maxlength="500" autocomplete="off"><button class="btn small" type="submit"></button></form></section><button id="chatbtn" class="btn gold" type="button"></button>';
  document.body.appendChild(box);
  box.querySelector('.chathead strong').textContent = title; box.querySelector('#chatbtn').textContent = title;
  var log = box.querySelector('#chatlog'), panel = box.querySelector('#chatpanel'), btn = box.querySelector('#chatbtn'), inp = box.querySelector('#chatin');
  inp.placeholder = d.chatPh || 'Type your message'; box.querySelector('#chatform button').textContent = d.chatSend || 'Send';
  function bubble(who, text) { var el = document.createElement('div'); el.className = 'bub ' + who; el.textContent = text; log.appendChild(el); log.scrollTop = log.scrollHeight; }
  bubble('admin', greet);
  function poll() {
    if (!token) return;
    fetch('/api/chat/messages?token=' + encodeURIComponent(token) + '&after=' + last).then(function (r) { return r.json(); })
      .then(function (list) { list.forEach(function (m) { last = Math.max(last, m.id); bubble(m.sender === 'admin' ? 'admin' : 'me', m.body); }); }).catch(function () {});
  }
  function open(on) { panel.hidden = !on; btn.hidden = on; document.body.classList.toggle('chatopen', on); clearInterval(timer); if (on) { poll(); timer = setInterval(poll, 4000); inp.focus(); } }
  btn.addEventListener('click', function () { open(true); });
  box.querySelector('#chatx').addEventListener('click', function () { open(false); });
  document.querySelectorAll('[data-open-chat]').forEach(function (b) { b.addEventListener('click', function () { open(true); }); });
  box.querySelector('#chatform').addEventListener('submit', function (e) {
    e.preventDefault(); var text = inp.value.trim(); if (!text) return; inp.value = '';
    fetch('/api/chat/send', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({token: token, body: text})})
      .then(function (r) { return r.json().then(function (x) { return {ok: r.ok, d: x}; }); })
      .then(function (x) {
        if (!x.ok) { bubble('admin', x.d.error || '...'); return; }
        token = x.d.token; try { localStorage.setItem('stairs-chat', token); } catch (e) {} poll();
      }).catch(function () { bubble('admin', '...'); });
  });
})();
