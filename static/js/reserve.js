(function () {
  var date = document.getElementById('date'), box = document.getElementById('times'), info = document.getElementById('avail');
  var tb = document.getElementById('tablebox'), list = document.getElementById('tablelist'), zones = document.getElementById('zones'), hint = document.getElementById('tablehint'), seatinfo = document.getElementById('seatinfo');
  if (!date) return;
  var want = box.dataset.selected || '', picked = (tb.dataset.selected || '').split(',').filter(Boolean), zone = 'all', tables = [];
  var D = tb.dataset;
  var tableSvg = '<svg viewBox="0 0 120 80" class="tsvg" aria-hidden="true"><circle cx="60" cy="40" r="20" fill="none" stroke="currentColor" stroke-width="3"/><rect x="52" y="8" width="16" height="9" rx="4" fill="currentColor"/><rect x="52" y="63" width="16" height="9" rx="4" fill="currentColor"/><rect x="22" y="33" width="9" height="14" rx="4" fill="currentColor"/><rect x="89" y="33" width="9" height="14" rx="4" fill="currentColor"/></svg>';
  function guests() { var g = document.querySelector('input[name=guests]:checked'); return g ? +g.value : 2; }
  function time() { var t = box.querySelector('input[name=time]:checked'); return t ? t.value : ''; }
  function mark() { document.querySelectorAll('[data-date]').forEach(function (b) { b.classList.toggle('on', b.dataset.date === date.value); }); }
  function seatLine() {
    var sum = 0; list.querySelectorAll('input:checked').forEach(function (i) { sum += +i.dataset.seats; });
    seatinfo.textContent = tables.length ? D.picked + ': ' + sum + ' / ' + guests() : '';
    seatinfo.classList.toggle('ok', sum >= guests());
  }
  function drawTables() {
    list.innerHTML = ''; zones.innerHTML = '';
    var present = []; tables.forEach(function (t) { if (present.indexOf(t.zone) < 0) present.push(t.zone); });
    if (present.length > 1) {
      [['all', D.all]].concat(present.map(function (z) { return [z, D[z]]; })).forEach(function (z) {
        var b = document.createElement('button'); b.type = 'button'; b.className = 'chip' + (zone === z[0] ? ' on' : ''); b.textContent = z[1];
        b.addEventListener('click', function () { zone = z[0]; drawTables(); }); zones.appendChild(b);
      });
    }
    tables.forEach(function (t) {
      var l = document.createElement('label'), i = document.createElement('input'), img = document.createElement('div'), body = document.createElement('div');
      l.className = 'tcard' + (zone !== 'all' && t.zone !== zone ? ' hide' : '') + (picked.indexOf(String(t.id)) >= 0 ? ' sel' : '');
      i.type = 'checkbox'; i.name = 'tables'; i.value = t.id; i.dataset.seats = t.seats; i.checked = picked.indexOf(String(t.id)) >= 0;
      img.className = 'timg'; if (t.image) { var im = document.createElement('img'); im.src = t.image; im.alt = t.name; im.loading = 'lazy'; img.appendChild(im); } else { img.innerHTML = tableSvg; }
      body.className = 'tbody';
      var n = document.createElement('strong'); n.textContent = t.name;
      var m = document.createElement('span'); m.className = 'tmeta'; m.textContent = D[t.zone] + ' · ' + t.seats + ' ' + D.seats;
      body.appendChild(n); body.appendChild(m);
      if (t.description) { var p = document.createElement('p'); p.textContent = t.description; body.appendChild(p); }
      i.addEventListener('change', function () {
        picked = []; list.querySelectorAll('input:checked').forEach(function (c) { picked.push(c.value); });
        l.classList.toggle('sel', i.checked); seatLine();
      });
      l.appendChild(i); l.appendChild(img); l.appendChild(body); list.appendChild(l);
    });
    seatLine();
  }
  function loadTables() {
    hint.textContent = ''; tables = []; drawTables();
    if (!time()) { hint.textContent = D.hint; return; }
    fetch('/api/tables?date=' + encodeURIComponent(date.value) + '&time=' + encodeURIComponent(time()))
      .then(function (r) { return r.json(); })
      .then(function (rows) {
        tables = rows; var ids = rows.map(function (t) { return String(t.id); });
        picked = picked.filter(function (x) { return ids.indexOf(x) >= 0; });
        if (!rows.length) hint.textContent = D.none;
        drawTables();
      }).catch(function () { hint.textContent = info.dataset.err; });
  }
  function loadSlots() {
    var cur = time(); if (cur) want = cur;
    box.innerHTML = ''; info.textContent = '';
    if (!date.value) return;
    fetch('/api/availability?date=' + encodeURIComponent(date.value) + '&guests=' + guests())
      .then(function (r) { return r.json().then(function (d) { return {ok: r.ok, d: d}; }); })
      .then(function (x) {
        if (!x.ok) { info.textContent = x.d.error; loadTables(); return; }
        if (!x.d.slots.length) { info.textContent = info.dataset.none; loadTables(); return; }
        x.d.slots.forEach(function (sl) {
          var l = document.createElement('label'), i = document.createElement('input'), s = document.createElement('span'), sm = document.createElement('small');
          l.className = 'pick'; i.type = 'radio'; i.name = 'time'; i.value = sl.time; i.required = true; i.disabled = sl.tables === 0; i.checked = sl.time === want && sl.tables > 0;
          s.textContent = sl.time; sm.textContent = sl.tables === 0 ? box.dataset.full : sl.seats + ' ' + box.dataset.seats; s.appendChild(sm); l.appendChild(i); l.appendChild(s); box.appendChild(l);
        });
        loadTables();
      }).catch(function () { info.textContent = info.dataset.err; });
  }
  box.addEventListener('change', function () { want = time(); loadTables(); });
  document.querySelectorAll('[data-date]').forEach(function (b) { b.addEventListener('click', function () { date.value = b.dataset.date; want = ''; mark(); loadSlots(); }); });
  document.querySelectorAll('input[name=guests]').forEach(function (i) { i.addEventListener('change', loadSlots); });
  date.addEventListener('change', function () { want = ''; mark(); loadSlots(); });
  mark(); loadSlots();
})();
