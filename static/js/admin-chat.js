(function () {
  var box = document.getElementById('msgs'); if (!box) return;
  box.scrollTop = box.scrollHeight;
  var last = 0; Array.prototype.forEach.call(box.children, function (d) { last = Math.max(last, +d.dataset.id); });
  setInterval(function () {
    fetch('/admin/api/chats/' + box.dataset.id + '?after=' + last).then(function (r) { return r.json(); }).then(function (l) {
      l.forEach(function (m) { last = Math.max(last, m.id); var d = document.createElement('div'); d.className = 'bub ' + (m.sender === 'admin' ? 'me' : 'admin'); d.dataset.id = m.id; d.textContent = m.body; box.appendChild(d); box.scrollTop = box.scrollHeight; });
    }).catch(function () {});
  }, 4000);
})();
