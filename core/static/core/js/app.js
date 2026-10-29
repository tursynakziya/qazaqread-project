// Shared page behaviour: text size buttons, user menu, flash messages.
(function () {
  const STEPS = [0.9, 1, 1.15];
  const content = document.getElementById('page-content');

  function readScale() {
    try { return parseFloat(localStorage.getItem('qr-scale')) || 1; } catch (e) { return 1; }
  }
  function applyScale(scale) {
    if (content) content.style.zoom = scale;
    document.querySelectorAll('[data-scale]').forEach(btn => {
      const active = parseFloat(btn.dataset.scale) === scale;
      btn.classList.toggle('bg-surface-container-highest', active);
      btn.classList.toggle('font-bold', active);
      btn.setAttribute('aria-pressed', active);
    });
    try { localStorage.setItem('qr-scale', scale); } catch (e) { /* storage unavailable */ }
  }
  document.querySelectorAll('[data-scale]').forEach(btn => {
    btn.addEventListener('click', () => applyScale(parseFloat(btn.dataset.scale)));
  });
  const initial = readScale();
  applyScale(STEPS.includes(initial) ? initial : 1);

  // User menu
  const menuBtn = document.getElementById('user-menu-btn');
  const menu = document.getElementById('user-menu');
  if (menuBtn && menu) {
    menuBtn.addEventListener('click', e => { e.stopPropagation(); menu.classList.toggle('hidden'); });
    document.addEventListener('click', e => { if (!menu.contains(e.target)) menu.classList.add('hidden'); });
  }

  // Mobile sidebar
  const sideBtn = document.getElementById('sidebar-btn');
  const sidebar = document.getElementById('sidebar');
  if (sideBtn && sidebar) {
    sideBtn.addEventListener('click', () => sidebar.classList.toggle('-translate-x-full'));
  }

  // Flash messages fade out
  document.querySelectorAll('[data-flash]').forEach(el => {
    el.querySelector('button')?.addEventListener('click', () => el.remove());
    setTimeout(() => el.remove(), 7000);
  });
})();
