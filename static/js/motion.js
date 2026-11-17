// Motion for the public pages: Lenis smooth scrolling + GSAP reveals.
// Skipped entirely for visitors who ask for reduced motion, or if the CDN scripts did not load
// (then everything simply stays visible and still).
(function () {
  if (!window.gsap || !window.ScrollTrigger || !window.Lenis) return;
  gsap.registerPlugin(ScrollTrigger, window.SplitText);

  gsap.matchMedia().add('(prefers-reduced-motion: no-preference)', function () {
    // Smooth scrolling, driven by GSAP's ticker so ScrollTrigger stays in sync.
    var lenis = new Lenis({ autoRaf: false, anchors: true, prevent: function (node) { return !!node.closest('#chat'); } });
    var raf = function (time) { lenis.raf(time * 1000); };
    lenis.on('scroll', ScrollTrigger.update);
    gsap.ticker.add(raf);
    gsap.ticker.lagSmoothing(0);

    // Page title: letters rise in one after another.
    var title = document.querySelector('.hero h1, .pagehead h1');
    if (title && window.SplitText) {
      gsap.from(SplitText.create(title, { type: 'chars' }).chars,
        { yPercent: 110, autoAlpha: 0, rotateX: -60, duration: 0.9, ease: 'expo.out', stagger: 0.035 });
    }
    gsap.from('.hero .eyebrow, .hero .lead, .hero .herobtns, .pagehead p',
      { y: 24, autoAlpha: 0, duration: 0.8, ease: 'power3.out', stagger: 0.12, delay: 0.25 });

    // Hero photo drifts slower than the page.
    gsap.to('.hero .bg, .hero .scene', {
      yPercent: 12, scale: 1.08, ease: 'none',
      scrollTrigger: { trigger: '.hero', start: 'top top', end: 'bottom top', scrub: true }
    });

    // Section headings: words come out of a blur as they scroll in.
    gsap.utils.toArray('main h2').forEach(function (h) {
      var words = window.SplitText ? SplitText.create(h, { type: 'words' }).words : h;
      gsap.from(words, {
        y: 28, autoAlpha: 0, filter: 'blur(8px)', duration: 0.8, ease: 'power3.out', stagger: 0.06,
        scrollTrigger: { trigger: h, start: 'top 88%', once: true }
      });
    });

    // Cards and photos: fade up in small groups as they arrive.
    var cards = '.sig, .trio figure, .revs blockquote, .dish, .infocard, .cta, .steps .wrap';
    gsap.set(cards, { y: 40, autoAlpha: 0 });
    ScrollTrigger.batch(cards, {
      start: 'top 90%', once: true,
      onEnter: function (els) { gsap.to(els, { y: 0, autoAlpha: 1, duration: 0.8, ease: 'power3.out', stagger: 0.1, overwrite: true }); }
    });

    // Photos inside the "Step inside" cards zoom out gently while scrolling past.
    gsap.utils.toArray('.trio figure img').forEach(function (img) {
      gsap.fromTo(img, { scale: 1.15 }, {
        scale: 1, ease: 'none', scrollTrigger: { trigger: img, start: 'top bottom', end: 'bottom top', scrub: true }
      });
    });

    window.addEventListener('load', function () { ScrollTrigger.refresh(); });  // photos change the layout once loaded

    return function () { gsap.ticker.remove(raf); lenis.destroy(); };
  });
})();
