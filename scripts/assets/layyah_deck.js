/* District Layyah deck — viewer
   Fixed 1280x720 slides scaled to fit; arrows / space navigate, P prints,
   F toggles fullscreen, Home/End jump to the ends. */
(function () {
  var slides = Array.prototype.slice.call(document.querySelectorAll('.slide'));
  var stage = document.getElementById('stage');
  var counter = document.querySelector('#nav .count');
  var progress = document.getElementById('progress');
  var i = 0;

  function fit() {
    var pad = 64;
    var s = Math.min((window.innerWidth - pad) / 1280, (window.innerHeight - pad - 42) / 720);
    s = Math.max(0.2, s);
    stage.style.transform = 'scale(' + s + ')';
  }

  function show(n, push) {
    i = Math.max(0, Math.min(slides.length - 1, n));
    slides.forEach(function (el, k) { el.classList.toggle('active', k === i); });
    if (counter) counter.textContent = (i + 1) + ' / ' + slides.length;
    if (progress) progress.style.width = ((i + 1) / slides.length * 100) + '%';
    if (push && history.replaceState) history.replaceState(null, '', '#' + (i + 1));
  }

  function fromHash() {
    var n = parseInt((location.hash || '').replace('#', ''), 10);
    return isNaN(n) ? 1 : n;
  }

  document.addEventListener('keydown', function (e) {
    if (e.key === 'ArrowRight' || e.key === 'PageDown' || e.key === ' ' || e.key === 'Enter') { show(i + 1, true); e.preventDefault(); }
    else if (e.key === 'ArrowLeft' || e.key === 'PageUp') { show(i - 1, true); e.preventDefault(); }
    else if (e.key === 'Home') { show(0, true); }
    else if (e.key === 'End') { show(slides.length - 1, true); }
    else if (e.key === 'p' || e.key === 'P') { window.print(); }
    else if (e.key === 'f' || e.key === 'F') {
      if (!document.fullscreenElement) { document.documentElement.requestFullscreen && document.documentElement.requestFullscreen(); }
      else if (document.exitFullscreen) { document.exitFullscreen(); }
    }
  });

  window.addEventListener('resize', fit);

  /* Click the right two-thirds to advance, the left third to go back. */
  document.getElementById('viewport').addEventListener('click', function (e) {
    if (e.target.closest('#nav')) return;
    if (e.clientX > window.innerWidth * 0.34) show(i + 1, true);
    else show(i - 1, true);
  });
  var prev = document.getElementById('prev');
  var next = document.getElementById('next');
  var printBtn = document.getElementById('print');
  if (prev) prev.onclick = function () { show(i - 1, true); };
  if (next) next.onclick = function () { show(i + 1, true); };
  if (printBtn) printBtn.onclick = function () { window.print(); };

  /* Safety net: if a slide's content is taller than the slide body, scale the
     whole body down uniformly instead of clipping it. Keeps print output intact. */
  function shrink(sl) {
    var body = sl.querySelector('.body');
    var inner = body && body.querySelector('.body-inner');
    if (!inner) return;
    inner.style.transform = 'none';
    inner.style.width = '100%';
    var avail = body.clientHeight;
    var z = 1;
    for (var k = 0; k < 5; k++) {
      var need = inner.getBoundingClientRect().height;
      if (need <= avail + 1) break;
      z *= Math.max(0.86, avail / need);
      inner.style.transform = 'scale(' + z + ')';
      inner.style.width = (100 / z) + '%';
    }
  }

  fit();
  slides.forEach(shrink);
  show(fromHash() - 1);
})();
