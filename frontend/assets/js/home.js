/* Trang chủ: kệ danh mục, lọc / sắp xếp / tìm kiếm sản phẩm, chi tiết sản phẩm, đánh giá */
renderShell('home');

const state = {
  q: param('q') || '',
  category_id: param('category') || '',
  sort: 'popular',
  on_sale: false,
  min_price: '',
  max_price: '',
  page: 1,
};
let categories = [];

function productCard(p) {
  const soldOut = p.available === 0;
  return `
    <article class="card">
      ${p.discount_percent ? `<span class="stamp">-${p.discount_percent}%</span>` : ''}
      <div data-open="${p.id}" role="button" tabindex="0" aria-label="Xem ${esc(p.name)}">${thumb(p)}</div>
      <div class="name" data-open="${p.id}">${esc(p.name)}</div>
      <div class="meta"><span>${esc(p.unit)}</span>${p.rating_count ? `<span class="stars" title="${p.rating_avg}/5">★ ${p.rating_avg}</span>` : ''}</div>
      <div class="price-row">
        <div class="prices">${priceTag(p.final_price)}${p.sale_price ? `<span class="was">${money(p.price)}</span>` : ''}</div>
        <button class="add" data-add="${p.id}" ${soldOut ? 'disabled' : ''} aria-label="Thêm ${esc(p.name)} vào giỏ">+</button>
      </div>
      <div class="meta">${soldOut ? '<span class="soldout">Tạm hết hàng</span>' : p.available !== undefined && p.available <= 5 ? `<span class="soldout">Chỉ còn ${p.available}</span>` : '<span></span>'}
        ${p.sold_count ? `<span>Đã bán ${p.sold_count}</span>` : ''}</div>
    </article>`;
}

async function loadCategories() {
  const data = await api('/categories');
  categories = data.items;
  const shelf = qs('#shelf');
  shelf.innerHTML = `<button data-cat="" aria-pressed="${!state.category_id}"><span class="emo">🛒</span>Tất cả</button>` +
    categories.map((c) => `<button data-cat="${c.id}" aria-pressed="${String(c.id) === String(state.category_id)}"><span class="emo">${c.icon}</span>${esc(c.name)}</button>`).join('');
  shelf.addEventListener('click', (e) => {
    const b = e.target.closest('button[data-cat]');
    if (!b) return;
    state.category_id = b.dataset.cat;
    state.page = 1;
    qsa('button', shelf).forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
    loadProducts();
  });
}

async function loadProducts() {
  const grid = qs('#grid');
  grid.innerHTML = '<div class="spinner"></div>';
  const cat = categories.find((c) => String(c.id) === String(state.category_id));
  qs('#catalog-title').textContent = state.q ? `Kết quả cho "${state.q}"` : state.on_sale ? 'Đang giảm giá' : cat ? cat.name : 'Tất cả sản phẩm';
  try {
    const data = await api('/products', {
      params: { q: state.q, category_id: state.category_id, sort: state.sort, on_sale: state.on_sale ? 1 : '',
        min_price: state.min_price, max_price: state.max_price, page: state.page, page_size: 12 },
    });
    qs('#stock-warning').classList.toggle('hidden', data.stock_available);
    grid.innerHTML = data.items.length ? data.items.map(productCard).join('')
      : `<div class="empty" style="grid-column:1/-1"><strong>Không tìm thấy sản phẩm phù hợp</strong>Thử từ khóa khác hoặc bỏ bớt bộ lọc.</div>`;
    pager(qs('#pager'), data.page, data.total_pages, (p) => { state.page = p; loadProducts(); qs('#catalog').scrollIntoView({ behavior: 'smooth' }); });
  } catch (e) {
    grid.innerHTML = `<div class="empty" style="grid-column:1/-1"><strong>Không tải được sản phẩm</strong>${esc(e.message)}</div>`;
  }
}

async function loadDeals() {
  try {
    const data = await api('/products', { params: { on_sale: 1, sort: 'discount', page_size: 4 } });
    qs('#deals').innerHTML = data.items.map((p) => `
      <div class="deal" data-open="${p.id}" role="button" tabindex="0">
        ${thumb(p, 'sm')}
        <div><div class="name">${esc(p.name)}</div><span class="muted small">${esc(p.unit)}</span></div>
        <div class="prices">${priceTag(p.final_price)}<span class="was">${money(p.price)}</span></div>
      </div>`).join('');
  } catch { qs('#deals').innerHTML = '<p class="muted">Chưa tải được ưu đãi.</p>'; }
}

async function loadCoupons() {
  try {
    const { items } = await api('/coupons/available');
    if (!items.length) return;
    qs('#coupons').innerHTML = items.map((c) => `
      <div class="ticket"><code>${esc(c.code)}</code><button class="btn ghost sm" data-copy="${esc(c.code)}">Sao chép</button>
      <p>${esc(c.description || c.label)}</p></div>`).join('');
    qs('#coupon-section').classList.remove('hidden');
    qs('#coupons').addEventListener('click', (e) => {
      const b = e.target.closest('[data-copy]');
      if (!b) return;
      navigator.clipboard?.writeText(b.dataset.copy).then(() => toast(`Đã sao chép mã ${b.dataset.copy}`), () => toast(`Mã: ${b.dataset.copy}`));
    });
  } catch { /* bỏ qua */ }
}

async function openProduct(id) {
  const d = openDialog({ title: 'Chi tiết sản phẩm', body: '<div class="spinner"></div>', wide: true });
  try {
    const [p, reviews] = await Promise.all([api(`/products/${id}`), api(`/products/${id}/reviews`, { params: { page_size: 5 } })]);
    const max = p.available ?? 99;
    d.body.innerHTML = `
      <div class="pd">
        ${thumb(p)}
        <div>
          <p class="muted small" style="margin:0">${esc(p.category_name)}</p>
          <h2>${esc(p.name)}</h2>
          ${p.rating_count ? `<p><span class="stars">${stars(p.rating_avg)}</span> <span class="muted small">${p.rating_avg}/5 từ ${p.rating_count} đánh giá</span></p>` : ''}
          <div style="display:flex;align-items:center;gap:.6rem;margin:.6rem 0">${priceTag(p.final_price, 'lg')}
            ${p.sale_price ? `<span class="was">${money(p.price)}</span><span class="stamp">-${p.discount_percent}%</span>` : ''}</div>
          <dl class="facts">
            <dt>Thương hiệu</dt><dd>${esc(p.brand || '—')}</dd>
            <dt>Quy cách</dt><dd>${esc(p.unit)}</dd>
            <dt>Mã hàng</dt><dd>${esc(p.sku)}</dd>
            <dt>Tình trạng</dt><dd>${p.available === undefined ? 'Đang cập nhật' : p.available > 0 ? `Còn ${p.available} sản phẩm` : '<span class="soldout" style="color:var(--chili)">Tạm hết hàng</span>'}</dd>
          </dl>
          <p>${esc(p.description || '')}</p>
          <div style="display:flex;gap:.6rem;align-items:center;flex-wrap:wrap">
            <div class="qty"><button type="button" data-step="-1" aria-label="Bớt">−</button><input id="pd-qty" type="number" value="1" min="1" max="${max}" aria-label="Số lượng"><button type="button" data-step="1" aria-label="Thêm">+</button></div>
            <button class="btn lg" id="pd-add" ${p.available === 0 ? 'disabled' : ''}>Thêm vào giỏ</button>
          </div>
        </div>
      </div>
      <section class="reviews">
        <h3>Đánh giá từ khách đã mua (${reviews.total})</h3>
        ${reviews.items.length ? reviews.items.map((r) => `<div class="review"><span class="stars">${stars(r.rating)}</span> <b>${esc(r.user_name || 'Khách hàng')}</b> <span class="muted small">${fmtDate(r.created_at, false)}</span><p style="margin:.3rem 0 0">${esc(r.comment || '')}</p></div>`).join('')
          : '<p class="muted">Chưa có đánh giá. Khách đã nhận hàng có thể đánh giá trong mục Đơn hàng.</p>'}
      </section>
      ${p.related.length ? `<section class="reviews"><h3>Cùng danh mục</h3><div class="related">${p.related.map((r) => `
        <div class="mini" data-open="${r.id}" role="button" tabindex="0">${thumb(r)}<div>${esc(r.name)}</div><b>${money(r.final_price)}</b></div>`).join('')}</div></section>` : ''}`;
    const qty = d.body.querySelector('#pd-qty');
    d.body.querySelectorAll('[data-step]').forEach((b) => b.addEventListener('click', () => {
      qty.value = Math.min(max, Math.max(1, Number(qty.value || 1) + Number(b.dataset.step)));
    }));
    d.body.querySelector('#pd-add').addEventListener('click', async (e) => {
      if (await addToCart(p.id, Number(qty.value || 1), e.currentTarget)) d.close();
    });
    d.body.addEventListener('click', (e) => {
      const r = e.target.closest('.related [data-open]');
      if (r) { d.close(); openProduct(r.dataset.open); }
    });
  } catch (e) {
    d.body.innerHTML = `<div class="empty"><strong>Không tải được sản phẩm</strong>${esc(e.message)}</div>`;
  }
}

document.addEventListener('click', (e) => {
  const add = e.target.closest('[data-add]');
  if (add) { addToCart(Number(add.dataset.add), 1, add); return; }
  const open = e.target.closest('main [data-open]');
  if (open && !e.target.closest('.overlay')) openProduct(open.dataset.open);
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && e.target.matches('main [data-open]')) openProduct(e.target.dataset.open);
});

qs('#sort').addEventListener('change', (e) => { state.sort = e.target.value; state.page = 1; loadProducts(); });
qs('#apply-filter').addEventListener('click', () => {
  state.min_price = qs('#min-price').value;
  state.max_price = qs('#max-price').value;
  state.on_sale = qs('#on-sale').checked;
  state.page = 1;
  loadProducts();
});
const showSale = (e) => {
  e.preventDefault();
  state.on_sale = true; qs('#on-sale').checked = true; state.sort = 'discount'; qs('#sort').value = 'discount'; state.page = 1;
  loadProducts();
  qs('#catalog').scrollIntoView({ behavior: 'smooth' });
};
qs('#sale-link').addEventListener('click', showSale);
qs('#all-deals').addEventListener('click', showSale);

(async () => {
  await loadCategories().catch(toastError);
  loadProducts();
  loadDeals();
  loadCoupons();
  if (param('product')) openProduct(param('product'));
})();
