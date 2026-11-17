document.addEventListener('click', function (e) {
  if (e.target.closest('[data-print]')) window.print();
  var b = e.target.closest('[data-confirm]');
  if (b && !confirm(b.dataset.confirm)) e.preventDefault();
});

(function () {  // on the home page, show the mobile booking button only after the top of the page
  var bb = document.querySelector('.bookbar');
  if (!bb || !document.querySelector('.hero')) return;
  bb.classList.add('late');
  function check() { bb.classList.toggle('show', window.scrollY > window.innerHeight * 0.6); }
  window.addEventListener('scroll', check, {passive: true}); check();
})();
