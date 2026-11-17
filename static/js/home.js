(function () {
  var reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  var slides = document.querySelectorAll('.hero .slide');
  if (slides.length > 1 && !reduce) {
    var i = 0;
    setInterval(function () { slides[i].classList.remove('on'); i = (i + 1) % slides.length; slides[i].classList.add('on'); }, 6000);
  }
  var el = document.querySelector('.count-steps');
  if (el && !reduce && 'IntersectionObserver' in window) {
    var to = +el.dataset.to, started = false;
    el.textContent = '0';
    new IntersectionObserver(function (entries, ob) {
      if (!entries[0].isIntersecting || started) return; started = true; ob.disconnect();
      var t0 = null;
      function step(t) { if (!t0) t0 = t; var p = Math.min((t - t0) / 1800, 1); el.textContent = Math.round(to * (1 - Math.pow(1 - p, 3))); if (p < 1) requestAnimationFrame(step); }
      requestAnimationFrame(step);
    }, {threshold: 0.4}).observe(el);
  }
})();
