/* Khung giao diện cửa hàng: biển hiệu (header), giỏ hàng nhanh, thông báo, chân trang */
function renderShell(active = '') {
  const user = Session.user;
  const header = document.createElement('header');
  header.className = 'signboard';
  header.innerHTML = `
    <div class="wrap">
      <a class="brand" href="/" aria-label="Tạp Hóa Xanh - trang chủ"><b>TẠP HÓA XANH</b><span>Đi chợ gần nhà, giao tận cửa</span></a>
      <form class="search" role="search" action="/" method="get">
        <label class="sr-only" for="q">Tìm sản phẩm</label>
        <input id="q" name="q" placeholder="Tìm gạo, mì, nước mắm… (gõ không dấu cũng được)" value="${esc(param('q') || '')}">
        <button type="submit">Tìm</button>
      </form>
      <nav class="top-nav" aria-label="Điều hướng chính">
        ${user ? `<a href="/orders.html" ${active === 'orders' ? 'aria-current="page"' : ''}>📦 <span class="label">Đơn hàng</span></a>` : ''}
        ${user ? `<div style="position:relative"><button type="button" class="nav-btn" id="bell" aria-haspopup="true" aria-expanded="false">🔔 <span class="badge red hidden" id="bell-count">0</span><span class="sr-only">Thông báo</span></button></div>` : ''}
        <a href="/cart.html" ${active === 'cart' ? 'aria-current="page"' : ''}>🧺 <span class="label">Giỏ hàng</span> <span class="badge" id="cart-count">0</span></a>
        ${user
          ? `<div style="position:relative"><button type="button" class="nav-btn" id="account-btn" aria-haspopup="true" aria-expanded="false">👤 <span class="label who">${esc(user.full_name)}</span></button></div>`
          : `<a href="/login.html">Đăng nhập</a>`}
      </nav>
    </div>`;
  const sub = document.createElement('div');
  sub.className = 'subsign';
  sub.innerHTML = `<div class="wrap"><span>Giao nhanh trong 2 giờ quanh khu vực Thủ Đức</span><span>Miễn phí giao hàng cho đơn từ 300.000đ</span><span>Hotline 0900 000 001</span></div>`;
  document.body.prepend(header, sub);

  const footer = document.createElement('footer');
  footer.className = 'footer';
  footer.innerHTML = `<div class="wrap">
      <div><b>Tạp Hóa Xanh</b><p>97 Man Thiện, Hiệp Phú, TP. Thủ Đức. Mở cửa 6:00 – 22:00 mỗi ngày.</p></div>
      <div><p>Hỗ trợ</p><a href="/orders.html">Tra cứu đơn hàng</a><br><a href="/account.html">Tài khoản</a></div>
      <div><p>Dành cho cửa hàng</p><a href="/admin/">Trang quản trị</a><br><a href="/api/health">Trạng thái hệ thống</a><br><a href="/api-docs.html">Hợp đồng dịch vụ (API)</a></div>
    </div>`;
  document.body.append(footer);

  if (user) {
    setupAccountMenu(user);
    setupBell();
  }
  refreshCartCount();
}

async function refreshCartCount() {
  const el = qs('#cart-count');
  if (!el) return;
  if (!Session.token) { el.textContent = '0'; return; }
  try { el.textContent = (await api('/cart/count')).count; } catch { /* bỏ qua */ }
}

function toggleDropdown(button, html, onOpen) {
  const holder = button.parentElement;
  const existing = holder.querySelector('.dropdown');
  qsa('.dropdown').forEach((d) => d.remove());
  qsa('[aria-expanded=true]').forEach((b) => b.setAttribute('aria-expanded', 'false'));
  if (existing) return null;
  const dd = document.createElement('div');
  dd.className = 'dropdown';
  dd.innerHTML = html;
  holder.append(dd);
  button.setAttribute('aria-expanded', 'true');
  onOpen && onOpen(dd);
  return dd;
}
document.addEventListener('click', (e) => {
  if (!e.target.closest('.dropdown') && !e.target.closest('[aria-haspopup]')) {
    qsa('.dropdown').forEach((d) => d.remove());
    qsa('[aria-expanded=true]').forEach((b) => b.setAttribute('aria-expanded', 'false'));
  }
});

function setupAccountMenu(user) {
  const btn = qs('#account-btn');
  btn.addEventListener('click', () => toggleDropdown(btn, `
    <header><span>${esc(user.full_name)}<br><span class="muted small">${esc(user.email)}</span></span></header>
    <a class="menu-link" href="/account.html">Tài khoản & địa chỉ</a>
    <a class="menu-link" href="/orders.html">Đơn hàng của tôi</a>
    ${Session.isStaff ? '<a class="menu-link" href="/admin/">Trang quản trị cửa hàng</a>' : ''}
    <a class="menu-link" href="#" id="logout-link">Đăng xuất</a>`, (dd) => {
    dd.querySelector('#logout-link').addEventListener('click', (e) => { e.preventDefault(); logout(); });
  }));
}

async function refreshBell() {
  const badge = qs('#bell-count');
  if (!badge) return;
  try {
    const { unread } = await api('/notifications/unread-count');
    badge.textContent = unread > 9 ? '9+' : unread;
    badge.classList.toggle('hidden', !unread);
  } catch { /* bỏ qua */ }
}

function setupBell() {
  const btn = qs('#bell');
  refreshBell();
  setInterval(refreshBell, 30000);
  btn.addEventListener('click', () => toggleDropdown(btn, `
    <header><span>Thông báo</span><button class="btn ghost sm" id="read-all">Đánh dấu đã đọc</button></header>
    <div class="list"><div class="spinner"></div></div>`, async (dd) => {
    const render = async () => {
      try {
        const data = await api('/notifications', { params: { page_size: 12 } });
        dd.querySelector('.list').innerHTML = data.items.length ? data.items.map((n) => `
          <a class="item ${n.is_read ? '' : 'unread'}" href="${esc(n.link || '#')}" data-id="${n.id}">
            <b>${esc(n.title)}</b><div>${esc(n.message)}</div><time>${timeAgo(n.created_at)}</time></a>`).join('')
          : '<div class="empty"><strong>Chưa có thông báo</strong>Cập nhật đơn hàng và khuyến mãi sẽ hiện ở đây.</div>';
      } catch (e) { dd.querySelector('.list').innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
    };
    await render();
    dd.querySelector('#read-all').addEventListener('click', async () => {
      await api('/notifications/read-all', { method: 'PUT' }).catch(toastError);
      await render(); refreshBell();
    });
    dd.querySelector('.list').addEventListener('click', (e) => {
      const a = e.target.closest('a.item');
      if (a) api(`/notifications/${a.dataset.id}/read`, { method: 'PUT' }).catch(() => {});
    });
  }));
}

async function addToCart(productId, quantity = 1, btn) {
  if (!Session.token) { toast('Đăng nhập để thêm vào giỏ hàng'); setTimeout(goLogin, 700); return false; }
  setBusy(btn, true, '…');
  try {
    const cart = await api('/cart/items', { method: 'POST', body: { product_id: productId, quantity } });
    qs('#cart-count') && (qs('#cart-count').textContent = cart.item_count);
    toast('Đã thêm vào giỏ hàng');
    return true;
  } catch (e) { toastError(e); return false; } finally { setBusy(btn, false); }
}

function priceBlock(p) {
  return `${priceTag(p.final_price)}${p.sale_price ? ` <span class="was">${money(p.price)}</span>` : ''}`;
}
