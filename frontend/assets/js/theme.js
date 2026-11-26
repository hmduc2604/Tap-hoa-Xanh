/* Giao diện sáng / tối.
   Nạp ĐỒNG BỘ trong <head> (trước khi trình duyệt vẽ) nên trang không bị nháy sáng rồi mới tối.
   Thứ tự chọn: lựa chọn đã lưu của người dùng, nếu chưa có thì theo cài đặt của hệ điều hành. */
(function () {
  var KEY = 'thx_theme';
  var root = document.documentElement;
  var mq = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

  function saved() {
    try { var v = localStorage.getItem(KEY); return v === 'dark' || v === 'light' ? v : null; } catch (e) { return null; }
  }
  function current() { return saved() || (mq && mq.matches ? 'dark' : 'light'); }

  function themeColorMeta() {
    var m = document.querySelector('meta[name="theme-color"]');
    if (!m) { m = document.createElement('meta'); m.name = 'theme-color'; document.head.appendChild(m); }
    return m;
  }

  function apply(theme) {
    root.setAttribute('data-theme', theme);
    themeColorMeta().setAttribute('content', theme === 'dark' ? '#08130C' : '#12452A');
    var buttons = document.querySelectorAll('[data-theme-toggle]');
    for (var i = 0; i < buttons.length; i++) buttons[i].setAttribute('aria-pressed', String(theme === 'dark'));
  }

  function set(theme, animate) {
    try { localStorage.setItem(KEY, theme); } catch (e) { /* trình duyệt chặn lưu trữ: vẫn đổi cho lần xem này */ }
    if (animate) {
      root.classList.add('theme-anim');
      setTimeout(function () { root.classList.remove('theme-anim'); }, 400);
    }
    apply(theme);
  }

  apply(current());

  /* theo hệ điều hành khi người dùng chưa tự chọn; đồng bộ giữa các tab */
  if (mq && mq.addEventListener) mq.addEventListener('change', function () { if (!saved()) apply(current()); });
  window.addEventListener('storage', function (e) { if (e.key === KEY) apply(current()); });

  document.addEventListener('click', function (e) {
    var btn = e.target.closest && e.target.closest('[data-theme-toggle]');
    if (btn) set(current() === 'dark' ? 'light' : 'dark', true);
  });

  var SUN = '<svg class="i-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
  var MOON = '<svg class="i-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20.5 14.2A8.5 8.5 0 0 1 9.8 3.5a8.5 8.5 0 1 0 10.7 10.7z"/></svg>';

  window.Theme = {
    get: current,
    set: function (t) { set(t, true); },
    toggle: function () { set(current() === 'dark' ? 'light' : 'dark', true); },
    /* mã HTML của nút chuyển, để các khung trang (header cửa hàng, thanh bên quản trị) chèn vào */
    buttonHtml: function (extraClass) {
      return '<button type="button" class="theme-toggle ' + (extraClass || '') + '" data-theme-toggle aria-pressed="' +
        (current() === 'dark') + '" aria-label="Chế độ tối" title="Chế độ tối">' + SUN + MOON + '</button>';
    },
  };
})();
