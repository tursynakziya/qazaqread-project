// Adds a show/hide eye button to every password field on the page.
document.querySelectorAll('input[type=password]').forEach(input => {
  const wrap = document.createElement('div');
  wrap.className = 'relative';
  input.parentNode.insertBefore(wrap, input);
  wrap.appendChild(input);
  input.classList.add('pr-12');
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'absolute right-2 top-1/2 -translate-y-1/2 w-9 h-9 rounded-lg flex items-center justify-center text-on-surface-variant hover:bg-surface-container-high';
  btn.innerHTML = '<span class="material-symbols-outlined text-[20px]">visibility</span>';
  btn.setAttribute('aria-label', 'Құпиясөзді көрсету');
  btn.addEventListener('click', () => {
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    btn.firstChild.textContent = show ? 'visibility_off' : 'visibility';
    btn.setAttribute('aria-label', show ? 'Құпиясөзді жасыру' : 'Құпиясөзді көрсету');
    input.focus();
  });
  wrap.appendChild(btn);
});
