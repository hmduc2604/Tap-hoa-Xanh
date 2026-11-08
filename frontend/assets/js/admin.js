/* Trang quản trị cửa hàng (SPA đơn giản theo hash: #dashboard, #orders, #pos, ...) */
if (!Session.token || !Session.isStaff) location.href = '/login.html?next=' + encodeURIComponent('/admin/');

const ME = Session.user || {};
const IS_ADMIN = ME.role === 'admin';
const $view = qs('#view');
const ROLE_LABEL = { admin: 'Quản trị viên', staff: 'Nhân viên', customer: 'Khách hàng' };
const STATUS_ACTION = { CONFIRMED: 'Xác nhận đơn', SHIPPING: 'Giao cho shipper', DELIVERED: 'Đã giao thành công' };
const MOVE_LABEL = { IMPORT: 'Nhập kho', SALE: 'Xuất bán', ADJUST: 'Điều chỉnh', RETURN: 'Hoàn kho', INITIAL: 'Tồn đầu kỳ' };
const STOCK_LABEL = { IN_STOCK: 'Còn hàng', LOW_STOCK: 'Sắp hết', OUT_OF_STOCK: 'Hết hàng' };
let categoriesCache = null;

qsa('.admin-only').forEach((el) => el.classList.toggle('hidden', !IS_ADMIN));
qs('#me').innerHTML = `<b>${esc(ME.full_name || '')}</b><br><span>${esc(ROLE_LABEL[ME.role] || '')}</span><br>
  <a href="/">Xem cửa hàng</a> · <a href="#" id="logout">Đăng xuất</a>`;
qs('#logout').addEventListener('click', (e) => { e.preventDefault(); logout(); });

/* ================================================================ tiện ích giao diện */
function page(title, actions = '') {
  $view.innerHTML = `<div class="topbar"><h1>${esc(title)}</h1><div class="actions">${actions}</div></div><div id="content"><div class="spinner"></div></div>`;
  document.title = `${title} — Quản trị Tạp Hóa Xanh`;
  return qs('#content');
}

function table(cols, rows, { empty = 'Chưa có dữ liệu', rowAttrs = null, rowClass = null } = {}) {
  if (!rows || !rows.length) return `<div class="table-wrap"><div class="empty"><strong>${esc(empty)}</strong></div></div>`;
  return `<div class="table-wrap"><table class="data"><thead><tr>${cols.map((c) => `<th class="${c.cls || ''}">${esc(c.label)}</th>`).join('')}</tr></thead>
    <tbody>${rows.map((r) => `<tr ${rowAttrs ? rowAttrs(r) : ''} class="${rowClass ? rowClass(r) : ''}">${cols.map((c) => `<td class="${c.cls || ''}">${c.render(r)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}

function stat(label, value, sub = '', alert = false) {
  return `<div class="stat ${alert ? 'alert' : ''}"><div class="label">${esc(label)}</div><div class="value">${value}</div><div class="sub">${sub}</div></div>`;
}

function compact(v) {
  v = Number(v || 0);
  if (v >= 1e9) return (v / 1e9).toFixed(1).replace('.0', '') + ' tỷ';
  if (v >= 1e6) return (v / 1e6).toFixed(1).replace('.0', '') + 'tr';
  if (v >= 1e3) return Math.round(v / 1e3) + 'k';
  return String(v);
}

function barChart(days) {
  if (!days || !days.length) return '';
  const max = Math.max(...days.map((d) => d.revenue));
  if (!max) return '<div class="empty"><strong>Chưa có doanh thu trong khoảng này</strong>Doanh thu được tính từ đơn đã giao và đơn bán tại quầy.</div>';
  const W = 640, H = 230, top = 22, bottom = 26, slot = W / days.length, bw = Math.min(46, slot * 0.62);
  const bars = days.map((d, i) => {
    const h = Math.max(d.revenue ? 3 : 0, ((H - top - bottom) * d.revenue) / max);
    const x = i * slot + (slot - bw) / 2, y = H - bottom - h;
    const label = days.length > 16 && i % Math.ceil(days.length / 10) ? '' : fmtDate(d.date, false).slice(0, 5);
    return `<g><rect class="bar" x="${x}" y="${y}" width="${bw}" height="${h}" rx="3"><title>${fmtDate(d.date, false)}: ${money(d.revenue)} · ${d.orders} đơn</title></rect>
      ${d.revenue && days.length <= 16 ? `<text class="val" x="${x + bw / 2}" y="${y - 6}" text-anchor="middle">${compact(d.revenue)}</text>` : ''}
      <text x="${x + bw / 2}" y="${H - 8}" text-anchor="middle">${label}</text></g>`;
  }).join('');
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Biểu đồ doanh thu theo ngày"><line x1="0" x2="${W}" y1="${H - bottom}" y2="${H - bottom}" stroke="#DDE3DA"/>${bars}</svg>`;
}

/* Form tạo / sửa dùng chung. field: {name, label, type, options, required, full, hint, min, step, placeholder} */
function fieldsHtml(fields, v = {}) {
  return fields.map((f) => {
    const val = v[f.name] ?? f.default ?? '';
    const req = f.required ? 'required' : '';
    const attrs = `name="${f.name}" ${req} ${f.min !== undefined ? `min="${f.min}"` : ''} ${f.max !== undefined ? `max="${f.max}"` : ''} ${f.step ? `step="${f.step}"` : ''} placeholder="${esc(f.placeholder || '')}"`;
    let input;
    if (f.type === 'select') {
      input = `<select ${attrs}>${f.options.map(([k, l]) => `<option value="${esc(k)}" ${String(k) === String(val) ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select>`;
    } else if (f.type === 'textarea') {
      input = `<textarea ${attrs} rows="3">${esc(val)}</textarea>`;
    } else if (f.type === 'checkbox') {
      return `<label class="check ${f.full ? 'full' : ''}"><input type="checkbox" name="${f.name}" ${val === true || val === 1 || (val === '' && f.default) ? 'checked' : ''}> ${esc(f.label)}</label>`;
    } else {
      const shown = f.type === 'datetime-local' && val ? String(val).replace(' ', 'T').slice(0, 16) : val;
      input = `<input type="${f.type || 'text'}" value="${esc(shown)}" ${attrs}>`;
    }
    return `<label class="field ${f.full ? 'full' : ''}">${esc(f.label)}${f.hint ? `<span class="hint">${esc(f.hint)}</span>` : ''}${input}</label>`;
  }).join('');
}

function readForm(form, fields) {
  const out = {};
  fields.forEach((f) => {
    const el = form.elements[f.name];
    if (!el) return;
    if (f.type === 'checkbox') out[f.name] = el.checked;
    else if (f.type === 'number') out[f.name] = el.value === '' ? null : Number(el.value);
    else out[f.name] = el.value.trim();
  });
  return out;
}

function openForm({ title, fields, values = {}, submitText = 'Lưu', onSubmit, wide = false }) {
  const d = openDialog({
    title, wide,
    body: `<form class="form-grid" novalidate>${fieldsHtml(fields, values)}</form>`,
    footer: `<button class="btn secondary" data-close>Hủy</button><button class="btn" data-submit>${esc(submitText)}</button>`,
  });
  const form = d.el.querySelector('form');
  const submit = async () => {
    if (!form.reportValidity()) return;
    const btn = d.el.querySelector('[data-submit]');
    setBusy(btn, true);
    try { await onSubmit(readForm(form, fields)); d.close(); }
    catch (e) { toastError(e); setBusy(btn, false); }
  };
  d.el.querySelector('[data-submit]').addEventListener('click', submit);
  form.addEventListener('submit', (e) => { e.preventDefault(); submit(); });
  return d;
}

async function getCategories(force = false) {
  if (!categoriesCache || force) categoriesCache = (await api('/categories', { params: { all: 1 } })).items;
  return categoriesCache;
}

function debounce(fn, ms = 250) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

/* ================================================================ TỔNG QUAN */
async function viewDashboard() {
  const c = page('Tổng quan', `<input type="date" id="d-from" aria-label="Từ ngày"><input type="date" id="d-to" aria-label="Đến ngày"><button class="btn secondary sm" id="d-apply">Xem báo cáo</button>`);
  const load = async () => {
    try {
      const data = await api('/dashboard', { params: { date_from: qs('#d-from').value, date_to: qs('#d-to').value } });
      const r = data.report || { totals: {}, revenue_by_day: [], top_products: [], by_channel: [], by_payment_method: [] };
      const t = (data.today || {}).totals || {};
      const inv = data.inventory || {};
      const recent = (data.recent_orders || {}).items || [];
      if (data.report) { qs('#d-from').value = r.date_from; qs('#d-to').value = r.date_to; }
      c.innerHTML = `
        ${data.partial ? `<div class="banner">Một số dịch vụ không phản hồi (${data.errors.map((e) => esc(e.service)).join(', ')}), số liệu có thể chưa đầy đủ.</div>` : ''}
        <div class="stats">
          ${stat('Doanh thu hôm nay', money(t.revenue), `${t.completed_orders || 0} đơn hoàn tất`)}
          ${stat('Đơn mới hôm nay', t.orders ?? '—', `${t.cancelled_orders || 0} đơn đã hủy`)}
          ${stat('Đơn đang xử lý', r.totals.processing_orders ?? '—', `${money(r.totals.pending_revenue)} chờ hoàn tất`)}
          ${stat('Mặt hàng cần nhập', (inv.low_stock || 0) + (inv.out_of_stock || 0), `${inv.out_of_stock || 0} mặt hàng đã hết`, (inv.out_of_stock || 0) > 0)}
        </div>
        <div class="cols">
          <section class="box chart"><h2>Doanh thu theo ngày <small>${fmtDate(r.date_from, false)} – ${fmtDate(r.date_to, false)}</small></h2>
            ${barChart(r.revenue_by_day)}
            <dl class="kv" style="margin-top:1rem">
              <dt>Doanh thu</dt><dd>${money(r.totals.revenue)}</dd>
              <dt>Đơn hoàn tất</dt><dd>${r.totals.completed_orders ?? 0} đơn, trung bình ${money(r.totals.avg_order_value)}</dd>
              <dt>Sản phẩm đã bán</dt><dd>${r.totals.items_sold ?? 0}</dd>
              <dt>Đã giảm cho khách</dt><dd>${money(r.totals.discount_total)}</dd>
            </dl></section>
          <section class="box"><h2>Bán chạy nhất</h2>
            ${table([
              { label: 'Sản phẩm', render: (p) => `${p.category_icon || ''} ${esc(p.product_name)}` },
              { label: 'SL', cls: 'num', render: (p) => p.quantity },
              { label: 'Doanh thu', cls: 'num', render: (p) => money(p.revenue) },
            ], r.top_products, { empty: 'Chưa có sản phẩm bán ra' })}</section>
        </div>
        <div class="cols">
          <section class="box"><h2>Đơn gần đây <a class="small" href="#orders">Xem tất cả</a></h2>
            ${table([
              { label: 'Mã đơn', render: (o) => `<b>${esc(o.code)}</b>` },
              { label: 'Khách', render: (o) => esc(o.customer_name || '') },
              { label: 'Tổng', cls: 'num', render: (o) => money(o.total) },
              { label: 'Trạng thái', render: (o) => pill(o.status, o.status_label) },
            ], recent, { empty: 'Chưa có đơn hàng', rowAttrs: (o) => `class="clickable" data-order="${o.id}"` })}</section>
          <section class="box"><h2>Kênh bán & thanh toán</h2>
            ${table([
              { label: 'Kênh', render: (x) => x.channel === 'POS' ? 'Tại quầy' : 'Online' },
              { label: 'Đơn', cls: 'num', render: (x) => x.orders },
              { label: 'Doanh thu', cls: 'num', render: (x) => money(x.revenue) },
            ], r.by_channel, { empty: 'Chưa có số liệu' })}
            <div style="height:.8rem"></div>
            ${table([
              { label: 'Phương thức', render: (x) => esc(PAY_METHOD[x.payment_method] || x.payment_method) },
              { label: 'Đơn', cls: 'num', render: (x) => x.orders },
              { label: 'Doanh thu', cls: 'num', render: (x) => money(x.revenue) },
            ], r.by_payment_method, { empty: 'Chưa có số liệu' })}
            <dl class="kv" style="margin-top:1rem">
              <dt>Sản phẩm đang bán</dt><dd>${(data.products || {}).active ?? '—'} / ${(data.products || {}).total ?? '—'}</dd>
              <dt>Khách hàng</dt><dd>${((data.users || {}).by_role || {}).customer ?? '—'} (mới hôm nay: ${(data.users || {}).new_today ?? 0})</dd>
              <dt>Tồn kho</dt><dd>${inv.total_units ?? '—'} đơn vị, ${inv.reserved_units ?? 0} đang giữ cho đơn</dd>
            </dl></section>
        </div>`;
      c.onclick = (e) => { const tr = e.target.closest('[data-order]'); if (tr) openOrderAdmin(tr.dataset.order, load); };
    } catch (e) { c.innerHTML = `<div class="empty"><strong>Không tải được tổng quan</strong>${esc(e.message)}</div>`; }
  };
  qs('#d-apply').addEventListener('click', load);
  load();
}

/* ================================================================ ĐƠN HÀNG */
async function viewOrders() {
  const c = page('Đơn hàng');
  const st = { status: '', channel: '', q: '', date_from: '', date_to: '', page: 1 };
  c.innerHTML = `<div class="status-tabs" id="o-tabs"></div>
    <div class="toolbar">
      <input type="search" id="o-q" placeholder="Mã đơn, tên hoặc SĐT khách">
      <select id="o-channel"><option value="">Mọi kênh bán</option><option value="ONLINE">Online</option><option value="POS">Tại quầy</option></select>
      <input type="date" id="o-from" aria-label="Từ ngày"><input type="date" id="o-to" aria-label="Đến ngày">
      <button class="btn secondary" id="o-go">Lọc</button>
    </div><div id="o-table"></div><nav class="pager" id="o-pager"></nav>`;
  const tabs = [['', 'Tất cả'], ['PENDING', 'Chờ xác nhận'], ['CONFIRMED', 'Đã xác nhận'], ['SHIPPING', 'Đang giao'], ['DELIVERED', 'Đã giao'], ['COMPLETED', 'Tại quầy'], ['CANCELLED', 'Đã hủy']];
  const load = async () => {
    try {
      const data = await api('/orders', { params: { ...st, page_size: 15 } });
      const counts = data.status_counts || {};
      const all = Object.values(counts).reduce((a, b) => a + b, 0);
      qs('#o-tabs').innerHTML = tabs.map(([k, l]) => `<button data-s="${k}" aria-pressed="${st.status === k}">${l}<span class="n">${k ? counts[k] || 0 : all}</span></button>`).join('');
      qs('#o-table').innerHTML = table([
        { label: 'Mã đơn', render: (o) => `<b>${esc(o.code)}</b><br><span class="muted small">${o.channel === 'POS' ? 'Tại quầy' : 'Online'}</span>` },
        { label: 'Khách hàng', render: (o) => `${esc(o.customer_name || '')}<br><span class="muted small">${esc(o.customer_phone || '')}</span>` },
        { label: 'Thời gian', render: (o) => `<span class="nowrap">${fmtDate(o.created_at)}</span>` },
        { label: 'SL', cls: 'num', render: (o) => o.item_count },
        { label: 'Tổng tiền', cls: 'num', render: (o) => `<b>${money(o.total)}</b>` },
        { label: 'Thanh toán', render: (o) => `${esc(PAY_METHOD[o.payment_method] || o.payment_method)}<br>${pill(o.payment_status === 'PAID' ? 'DELIVERED' : o.payment_status, o.payment_status_label)}` },
        { label: 'Trạng thái', render: (o) => pill(o.status, o.status_label) },
      ], data.items, { empty: 'Không có đơn hàng phù hợp', rowAttrs: (o) => `class="clickable" data-id="${o.id}"` });
      pager(qs('#o-pager'), data.page, data.total_pages, (p) => { st.page = p; load(); });
      refreshPendingBadge();
    } catch (e) { qs('#o-table').innerHTML = `<div class="empty"><strong>Không tải được đơn hàng</strong>${esc(e.message)}</div>`; }
  };
  qs('#o-tabs').addEventListener('click', (e) => { const b = e.target.closest('[data-s]'); if (b) { st.status = b.dataset.s; st.page = 1; load(); } });
  const apply = () => { st.q = qs('#o-q').value.trim(); st.channel = qs('#o-channel').value; st.date_from = qs('#o-from').value; st.date_to = qs('#o-to').value; st.page = 1; load(); };
  qs('#o-go').addEventListener('click', apply);
  qs('#o-q').addEventListener('keydown', (e) => { if (e.key === 'Enter') apply(); });
  qs('#o-table').addEventListener('click', (e) => { const tr = e.target.closest('tr[data-id]'); if (tr) openOrderAdmin(tr.dataset.id, load); });
  load();
}

function receiptHtml(o) {
  return `<div class="receipt print-area" style="position:static;box-shadow:none">
    <h2>TẠP HÓA XANH</h2><p class="center small">97 Man Thiện, TP. Thủ Đức<br>Hóa đơn ${esc(o.code)}<br>${fmtDate(o.created_at)} · Thu ngân: ${esc(o.created_by || '')}</p>
    <div class="lines">${o.items.map((i) => `<div class="rline"><span>${esc(i.product_name)}<br><span class="muted small">${i.quantity} × ${money(i.unit_price)}</span></span><span class="amt">${money(i.line_total)}</span></div>`).join('')}</div>
    <div class="sum">
      <div><span>Tạm tính</span><span>${money(o.subtotal)}</span></div>
      ${o.discount ? `<div class="discount"><span>Giảm giá ${esc(o.coupon_code || '')}</span><span>−${money(o.discount)}</span></div>` : ''}
      <div class="grand"><span>Tổng cộng</span><span>${money(o.total)}</span></div>
      ${o.cash_received != null ? `<div><span>Tiền khách đưa</span><span>${money(o.cash_received)}</span></div><div><span>Tiền thối</span><span>${money(o.change_amount)}</span></div>` : ''}
      <div><span>Thanh toán</span><span>${esc(PAY_METHOD[o.payment_method] || o.payment_method)}</span></div>
    </div><p class="center small" style="margin-top:1rem">Cảm ơn quý khách, hẹn gặp lại!</p></div>`;
}

async function openOrderAdmin(id, onChange) {
  const d = openDialog({ title: 'Chi tiết đơn hàng', body: '<div class="spinner"></div>', wide: true });
  const render = async () => {
    try {
      const o = await api(`/orders/${id}`);
      const p = o.payment;
      const next = o.next_statuses || [];
      d.body.innerHTML = `
        <div class="topbar" style="margin-bottom:.8rem"><h2 style="margin:0">#${esc(o.code)}</h2><div class="actions">${pill(o.status, o.status_label)} ${pill(o.payment_status === 'PAID' ? 'DELIVERED' : o.payment_status, o.payment_status_label)}</div></div>
        <div class="detail-grid">
          <div>
            ${table([
              { label: 'Sản phẩm', render: (i) => `${i.category_icon || ''} ${esc(i.product_name)}<br><span class="muted small">${esc(i.sku || '')}</span>` },
              { label: 'Đơn giá', cls: 'num', render: (i) => money(i.unit_price) },
              { label: 'SL', cls: 'num', render: (i) => i.quantity },
              { label: 'Thành tiền', cls: 'num', render: (i) => money(i.line_total) },
            ], o.items)}
            <div class="sum" style="margin:1rem 0">
              <div><span>Tạm tính</span><span>${money(o.subtotal)}</span></div>
              ${o.discount ? `<div class="discount"><span>Giảm giá (${esc(o.coupon_code)})</span><span>−${money(o.discount)}</span></div>` : ''}
              <div><span>Phí giao hàng</span><span>${money(o.shipping_fee)}</span></div>
              <div class="grand"><span>Tổng cộng</span>${priceTag(o.total)}</div>
            </div>
            ${p ? `<div class="box"><h2>Thanh toán</h2><dl class="kv"><dt>Phương thức</dt><dd>${esc(p.method_label)}</dd><dt>Trạng thái</dt><dd>${esc(p.status_label)}</dd>
              ${p.transaction_ref ? `<dt>Mã giao dịch</dt><dd>${esc(p.transaction_ref)}</dd>` : ''}${p.paid_at ? `<dt>Thời gian</dt><dd>${fmtDate(p.paid_at)}</dd>` : ''}</dl></div>` : ''}
          </div>
          <div>
            <dl class="kv"><dt>Khách</dt><dd>${esc(o.customer_name || '')}</dd><dt>SĐT</dt><dd>${esc(o.customer_phone || '—')}</dd>
              ${o.customer_email ? `<dt>Email</dt><dd>${esc(o.customer_email)}</dd>` : ''}
              ${o.shipping_address ? `<dt>Giao đến</dt><dd>${esc(o.shipping_address)}</dd>` : ''}
              ${o.note ? `<dt>Ghi chú</dt><dd>${esc(o.note)}</dd>` : ''}
              ${o.cancel_reason ? `<dt>Lý do hủy</dt><dd>${esc(o.cancel_reason)}</dd>` : ''}</dl>
            <h3 style="margin-top:1rem">Lịch sử xử lý</h3>
            <ol class="timeline">${o.history.map((h) => `<li class="${h.status}"><b>${esc(h.status_label)}</b><div class="small">${esc(h.note || '')}</div><time>${fmtDate(h.created_at)} · ${esc(h.changed_by || '')}</time></li>`).join('')}</ol>
            <div style="display:grid;gap:.5rem">
              ${next.filter((s) => s !== 'CANCELLED').map((s) => `<button class="btn" data-status="${s}">${STATUS_ACTION[s]}</button>`).join('')}
              ${p && p.status === 'PENDING' && p.method === 'BANK_TRANSFER' && o.status !== 'CANCELLED' ? `<button class="btn yellow" data-confirm-pay="${p.id}">Xác nhận đã nhận chuyển khoản</button>` : ''}
              ${next.includes('CANCELLED') ? '<button class="btn danger" data-cancel>Hủy đơn hàng</button>' : ''}
              ${o.channel === 'POS' ? '<button class="btn secondary" data-print>In hóa đơn</button>' : ''}
            </div>
          </div>
        </div>`;
      d.body.onclick = async (e) => {
        const s = e.target.closest('[data-status]');
        try {
          if (s) {
            setBusy(s, true);
            await api(`/orders/${id}/status`, { method: 'PUT', body: { status: s.dataset.status } });
            toast(`Đã cập nhật: ${STATUS[s.dataset.status]}`);
          } else if (e.target.closest('[data-cancel]')) {
            const reason = await confirmDialog('Hủy đơn này? Hàng giữ trong kho sẽ được trả lại, tiền đã thanh toán sẽ được hoàn.', { okText: 'Hủy đơn', danger: true, input: { label: 'Lý do hủy', placeholder: 'Ví dụ: khách không liên lạc được' } });
            if (reason === null) return;
            await api(`/orders/${id}/status`, { method: 'PUT', body: { status: 'CANCELLED', note: reason || undefined } });
            toast('Đã hủy đơn hàng');
          } else if (e.target.closest('[data-confirm-pay]')) {
            await api(`/payments/${e.target.closest('[data-confirm-pay]').dataset.confirmPay}/confirm`, { method: 'POST', body: {} });
            toast('Đã xác nhận thanh toán');
            await new Promise((r) => setTimeout(r, 600));
          } else if (e.target.closest('[data-print]')) {
            const w = openDialog({ title: 'Hóa đơn', body: receiptHtml(o), footer: '<button class="btn" onclick="window.print()">In</button>' });
            return w;
          } else return;
          await render();
          onChange && onChange();
        } catch (err) { toastError(err); render(); }
      };
    } catch (e) { d.body.innerHTML = `<div class="empty"><strong>Không tải được đơn hàng</strong>${esc(e.message)}</div>`; }
  };
  render();
}

/* ================================================================ BÁN TẠI QUẦY */
async function viewPos() {
  const c = page('Bán tại quầy', '<span class="muted small">Quét mã vạch hoặc gõ tên rồi nhấn Enter</span>');
  const bill = new Map();
  let method = 'CASH';
  let coupon = null;
  c.innerHTML = `<div class="pos">
    <section>
      <form class="scan" id="scan"><label class="sr-only" for="scan-input">Mã vạch hoặc tên sản phẩm</label>
        <input id="scan-input" placeholder="Mã vạch / SKU / tên sản phẩm" autocomplete="off"><button class="btn" type="submit">Thêm</button></form>
      <div class="status-tabs" id="pos-cats"></div>
      <div class="pos-results" id="pos-results"><div class="spinner"></div></div>
    </section>
    <aside class="receipt" aria-label="Hóa đơn đang lập">
      <h2>TẠP HÓA XANH</h2><p class="center muted small" style="margin:0">Thu ngân: ${esc(ME.full_name || '')}</p>
      <div class="lines" id="bill-lines"></div>
      <div class="sum" id="bill-sum"></div>
      <div style="display:grid;gap:.7rem;margin-top:.9rem">
        <div class="coupon-row"><input id="pos-coupon" placeholder="Mã giảm giá" aria-label="Mã giảm giá"><button class="btn secondary sm" id="pos-coupon-btn">Áp dụng</button></div>
        <p id="pos-coupon-msg" class="small" style="margin:-.3rem 0 0"></p>
        <div class="form-grid"><label class="field">Tên khách<input id="pos-name" placeholder="Khách lẻ"></label><label class="field">Số điện thoại<input id="pos-phone" inputmode="tel"></label></div>
        <div class="status-tabs" id="pos-method" style="margin:0">
          <button data-m="CASH" aria-pressed="true">Tiền mặt</button><button data-m="CARD" aria-pressed="false">Thẻ</button><button data-m="BANK_TRANSFER" aria-pressed="false">Chuyển khoản</button></div>
        <div id="cash-box"><label class="field">Tiền khách đưa<input id="cash" type="number" min="0" step="1000"></label>
          <div class="cash-quick" id="cash-quick"></div><div class="change"><span>Tiền thối lại</span><span id="change">0đ</span></div></div>
        <button class="btn lg block" id="pos-pay" disabled>Thanh toán</button>
        <button class="btn ghost sm" id="pos-clear">Xóa hóa đơn</button>
      </div>
    </aside></div>`;

  const subtotal = () => [...bill.values()].reduce((s, l) => s + l.product.final_price * l.qty, 0);
  const discount = () => (coupon ? coupon.discount : 0);
  const total = () => Math.max(0, subtotal() - discount());

  function renderBill() {
    const lines = [...bill.values()];
    qs('#bill-lines').innerHTML = lines.length ? lines.map((l) => `
      <div class="rline" data-id="${l.product.id}"><span>${esc(l.product.name)}<br><span class="muted small">${money(l.product.final_price)}</span></span>
        <span class="amt">${money(l.product.final_price * l.qty)}</span>
        <span class="ctrl"><button data-d="-1" aria-label="Bớt">−</button><b>${l.qty}</b><button data-d="1" aria-label="Thêm">+</button></span>
        <span style="text-align:right"><button class="btn ghost sm" data-rm>Bỏ</button></span></div>`).join('')
      : '<p class="center muted" style="margin:1.2rem 0">Chưa có sản phẩm</p>';
    qs('#bill-sum').innerHTML = `<div><span>Tạm tính (${lines.reduce((s, l) => s + l.qty, 0)} món)</span><span>${money(subtotal())}</span></div>
      ${discount() ? `<div class="discount"><span>Giảm giá ${esc(coupon.code)}</span><span>−${money(discount())}</span></div>` : ''}
      <div class="grand"><span>Khách cần trả</span>${priceTag(total(), 'lg')}</div>`;
    const t = total();
    const quick = [t, ...[50000, 100000, 200000, 500000].filter((v) => v > t)].slice(0, 4);
    qs('#cash-quick').innerHTML = t ? quick.map((v, i) => `<button data-cash="${v}">${i === 0 ? 'Đủ tiền' : money(v)}</button>`).join('') : '';
    updateChange();
  }
  function updateChange() {
    const cash = Number(qs('#cash').value || 0);
    const change = cash - total();
    qs('#change').textContent = method === 'CASH' && cash ? (change >= 0 ? money(change) : 'Còn thiếu ' + money(-change)) : '0đ';
    qs('#pos-pay').disabled = !bill.size || (method === 'CASH' && cash < total());
  }
  const revalidateCoupon = debounce(async () => {
    if (!coupon) return renderBill();
    try {
      const v = await api('/coupons/validate', { method: 'POST', body: { code: coupon.code, subtotal: subtotal() } });
      coupon = { code: v.code, discount: v.discount };
      qs('#pos-coupon-msg').innerHTML = `<span class="note-ok">${esc(v.message)}</span>`;
    } catch (e) { qs('#pos-coupon-msg').innerHTML = `<span class="note-err">${esc(e.message)}</span>`; coupon = null; }
    renderBill();
  }, 300);

  function add(p, qty = 1) {
    const line = bill.get(p.id) || { product: p, qty: 0 };
    if (p.available !== undefined && line.qty + qty > p.available) { toast(`${p.name} chỉ còn ${p.available} trong kho`, 'error'); return; }
    line.qty += qty;
    if (line.qty <= 0) bill.delete(p.id); else bill.set(p.id, line);
    coupon ? revalidateCoupon() : renderBill();
  }

  async function search(params) {
    const box = qs('#pos-results');
    try {
      const data = await api('/products', { params: { page_size: 24, sort: 'popular', ...params } });
      box.innerHTML = data.items.length ? data.items.map((p) => `<button class="pos-item" data-p='${esc(JSON.stringify({ id: p.id, name: p.name, final_price: p.final_price, available: p.available }))}' ${p.available === 0 ? 'disabled' : ''}>
        ${thumb(p)}<span class="n">${esc(p.name)}</span><span class="p">${money(p.final_price)}</span><span class="muted small">Còn ${p.available ?? '?'}</span></button>`).join('')
        : '<div class="empty" style="grid-column:1/-1"><strong>Không tìm thấy sản phẩm</strong></div>';
      return data.items;
    } catch (e) { box.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return []; }
  }

  const cats = await getCategories().catch(() => []);
  qs('#pos-cats').innerHTML = `<button data-c="" aria-pressed="true">Bán chạy</button>` + cats.filter((x) => x.is_active).map((x) => `<button data-c="${x.id}" aria-pressed="false">${x.icon} ${esc(x.name)}</button>`).join('');
  qs('#pos-cats').addEventListener('click', (e) => {
    const b = e.target.closest('[data-c]');
    if (!b) return;
    qsa('#pos-cats button').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
    search({ category_id: b.dataset.c });
  });
  qs('#pos-results').addEventListener('click', (e) => { const b = e.target.closest('[data-p]'); if (b) add(JSON.parse(b.dataset.p)); });
  qs('#scan-input').addEventListener('input', debounce((e) => { if (e.target.value.trim().length >= 2) search({ q: e.target.value.trim() }); }, 300));
  qs('#scan').addEventListener('submit', async (e) => {
    e.preventDefault();
    const code = qs('#scan-input').value.trim();
    if (!code) return;
    if (!/\s/.test(code)) {
      try {
        const p = await api(`/products/barcode/${encodeURIComponent(code)}`);
        add({ id: p.id, name: p.name, final_price: p.final_price, available: p.available });
        qs('#scan-input').value = '';
        return;
      } catch (err) { if (err.status !== 404) { toastError(err); return; } }
    }
    const items = await search({ q: code });
    if (items.length === 1) { const p = items[0]; add({ id: p.id, name: p.name, final_price: p.final_price, available: p.available }); qs('#scan-input').value = ''; }
    else if (!items.length) toast(`Không tìm thấy "${code}"`, 'error');
  });
  qs('#bill-lines').addEventListener('click', (e) => {
    const row = e.target.closest('.rline');
    if (!row) return;
    const line = bill.get(Number(row.dataset.id));
    if (e.target.closest('[data-d]')) add(line.product, Number(e.target.closest('[data-d]').dataset.d));
    if (e.target.closest('[data-rm]')) { bill.delete(line.product.id); coupon ? revalidateCoupon() : renderBill(); }
  });
  qs('#pos-method').addEventListener('click', (e) => {
    const b = e.target.closest('[data-m]');
    if (!b) return;
    method = b.dataset.m;
    qsa('#pos-method button').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
    qs('#cash-box').classList.toggle('hidden', method !== 'CASH');
    updateChange();
  });
  qs('#cash').addEventListener('input', updateChange);
  qs('#cash-quick').addEventListener('click', (e) => { const b = e.target.closest('[data-cash]'); if (b) { qs('#cash').value = b.dataset.cash; updateChange(); } });
  qs('#pos-coupon-btn').addEventListener('click', () => {
    const code = qs('#pos-coupon').value.trim().toUpperCase();
    coupon = code ? { code, discount: 0 } : null;
    if (!code) qs('#pos-coupon-msg').textContent = '';
    revalidateCoupon();
  });
  const reset = () => { bill.clear(); coupon = null; ['#pos-coupon', '#pos-name', '#pos-phone', '#cash'].forEach((s) => { qs(s).value = ''; }); qs('#pos-coupon-msg').textContent = ''; renderBill(); qs('#scan-input').focus(); };
  qs('#pos-clear').addEventListener('click', reset);
  qs('#pos-pay').addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    setBusy(btn, true, 'Đang thanh toán…');
    try {
      const o = await api('/pos/orders', { method: 'POST', body: {
        items: [...bill.values()].map((l) => ({ product_id: l.product.id, quantity: l.qty })),
        payment_method: method, cash_received: method === 'CASH' ? Number(qs('#cash').value || 0) : undefined,
        coupon_code: coupon ? coupon.code : undefined, customer_name: qs('#pos-name').value.trim() || undefined,
        customer_phone: qs('#pos-phone').value.trim() || undefined } });
      setBusy(btn, false);
      reset();
      openDialog({ title: 'Thanh toán thành công', body: receiptHtml(o), footer: '<button class="btn secondary" data-close>Đơn mới</button><button class="btn" onclick="window.print()">In hóa đơn</button>' });
      search({});
    } catch (err) { toastError(err); setBusy(btn, false); updateChange(); }
  });
  renderBill();
  search({});
  qs('#scan-input').focus();
}

/* ================================================================ THANH TOÁN */
async function viewPayments() {
  const c = page('Thanh toán');
  const st = { status: '', method: '', q: '', page: 1 };
  c.innerHTML = `<div class="stats" id="p-stats"></div>
    <div class="toolbar"><input type="search" id="p-q" placeholder="Mã đơn hoặc mã giao dịch">
      <select id="p-status"><option value="">Mọi trạng thái</option><option value="PENDING">Chờ thanh toán</option><option value="PAID">Đã thanh toán</option><option value="REFUNDED">Đã hoàn tiền</option><option value="CANCELLED">Đã hủy</option></select>
      <select id="p-method"><option value="">Mọi phương thức</option>${Object.entries(PAY_METHOD).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select>
      <button class="btn secondary" id="p-go">Lọc</button></div>
    <div id="p-table"></div><nav class="pager" id="p-pager"></nav>`;
  const load = async () => {
    try {
      const data = await api('/payments', { params: { ...st, page_size: 15 } });
      qs('#p-stats').innerHTML = stat('Đã thu', money(data.summary.paid_amount)) + stat('Chờ thanh toán', money(data.summary.pending_amount)) +
        stat('Đã hoàn tiền', money(data.summary.refunded_amount)) + stat('Số giao dịch', data.total);
      qs('#p-table').innerHTML = table([
        { label: 'Đơn hàng', render: (p) => `<b>${esc(p.order_code)}</b>` },
        { label: 'Phương thức', render: (p) => esc(p.method_label) },
        { label: 'Số tiền', cls: 'num', render: (p) => money(p.amount) },
        { label: 'Mã giao dịch', render: (p) => esc(p.transaction_ref || '—') },
        { label: 'Tạo lúc', render: (p) => `<span class="nowrap">${fmtDate(p.created_at)}</span>` },
        { label: 'Trạng thái', render: (p) => pill(p.status === 'PAID' ? 'DELIVERED' : p.status, p.status_label) },
        { label: '', cls: 'num', render: (p) => p.status === 'PENDING' && ['BANK_TRANSFER', 'COD'].includes(p.method) ? `<button class="btn sm secondary" data-confirm="${p.id}">Xác nhận đã thu</button>` : '' },
      ], data.items, { empty: 'Chưa có giao dịch' });
      pager(qs('#p-pager'), data.page, data.total_pages, (p) => { st.page = p; load(); });
    } catch (e) { qs('#p-table').innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
  };
  qs('#p-go').addEventListener('click', () => { st.q = qs('#p-q').value.trim(); st.status = qs('#p-status').value; st.method = qs('#p-method').value; st.page = 1; load(); });
  qs('#p-table').addEventListener('click', async (e) => {
    const b = e.target.closest('[data-confirm]');
    if (!b || !(await confirmDialog('Xác nhận cửa hàng đã nhận đủ tiền cho giao dịch này?'))) return;
    try { await api(`/payments/${b.dataset.confirm}/confirm`, { method: 'POST', body: {} }); toast('Đã xác nhận thanh toán'); load(); } catch (err) { toastError(err); }
  });
  load();
}

/* ================================================================ SẢN PHẨM */
async function viewProducts() {
  const c = page('Sản phẩm', '<button class="btn" id="new-product">Thêm sản phẩm</button>');
  const cats = await getCategories(true).catch(() => []);
  const st = { q: '', category_id: '', include_inactive: 1, page: 1, sort: 'newest' };
  c.innerHTML = `<div class="toolbar"><input type="search" id="pr-q" placeholder="Tên, SKU hoặc mã vạch">
      <select id="pr-cat"><option value="">Mọi danh mục</option>${cats.map((x) => `<option value="${x.id}">${x.icon} ${esc(x.name)}</option>`).join('')}</select>
      <select id="pr-sort"><option value="newest">Mới thêm</option><option value="name">Tên A–Z</option><option value="popular">Bán chạy</option><option value="price_desc">Giá cao</option></select>
      <button class="btn secondary" id="pr-go">Lọc</button></div><div id="pr-table"></div><nav class="pager" id="pr-pager"></nav>`;
  const fields = (isNew) => [
    { name: 'name', label: 'Tên sản phẩm', required: true, full: true },
    { name: 'sku', label: 'Mã hàng (SKU)', required: true },
    { name: 'barcode', label: 'Mã vạch', placeholder: '893…' },
    { name: 'category_id', label: 'Danh mục', type: 'select', options: cats.map((x) => [x.id, `${x.icon} ${x.name}`]) },
    { name: 'brand', label: 'Thương hiệu' },
    { name: 'unit', label: 'Quy cách / đơn vị', required: true, placeholder: 'chai 500ml, gói, kg…' },
    { name: 'price', label: 'Giá bán (đ)', type: 'number', required: true, min: 0, step: 500 },
    { name: 'sale_price', label: 'Giá khuyến mãi (đ)', type: 'number', min: 0, step: 500, hint: 'Để trống nếu không giảm giá' },
    { name: 'image_url', label: 'Ảnh (URL)', full: true, placeholder: 'https://… (để trống sẽ dùng biểu tượng danh mục)' },
    { name: 'description', label: 'Mô tả', type: 'textarea', full: true },
    ...(isNew ? [{ name: 'initial_stock', label: 'Tồn đầu kỳ', type: 'number', min: 0, default: 0 }, { name: 'min_quantity', label: 'Ngưỡng cảnh báo hết hàng', type: 'number', min: 0, default: 10 }]
      : [{ name: 'is_active', label: 'Đang kinh doanh', type: 'checkbox', full: true }]),
  ];
  const load = async () => {
    try {
      const data = await api('/products', { params: { ...st, page_size: 15 } });
      qs('#pr-table').innerHTML = table([
        { label: 'Sản phẩm', render: (p) => `<div class="prod-cell">${thumb(p, 'sm')}<div><b>${esc(p.name)}</b><br><span class="muted small">${esc(p.unit)} · ${esc(p.category_name)}</span></div></div>` },
        { label: 'SKU / Mã vạch', render: (p) => `${esc(p.sku)}<br><span class="muted small">${esc(p.barcode || '')}</span>` },
        { label: 'Giá bán', cls: 'num', render: (p) => p.sale_price ? `<b style="color:var(--chili)">${money(p.sale_price)}</b><br><span class="was">${money(p.price)}</span>` : money(p.price) },
        { label: 'Tồn', cls: 'num', render: (p) => p.available ?? '—' },
        { label: 'Đã bán', cls: 'num', render: (p) => p.sold_count },
        { label: 'Đánh giá', cls: 'num', render: (p) => p.rating_count ? `★ ${p.rating_avg} (${p.rating_count})` : '—' },
        { label: 'Trạng thái', render: (p) => p.is_active ? pill('DELIVERED', 'Đang bán') : pill('INACTIVE', 'Ngừng bán') },
        { label: '', cls: 'num', render: (p) => `<div class="row-actions"><button class="btn ghost sm" data-edit="${p.id}">Sửa</button>
            ${p.is_active ? `<button class="btn ghost sm" data-off="${p.id}">Ngừng bán</button>` : `<button class="btn ghost sm" data-on="${p.id}">Bán lại</button>`}</div>` },
      ], data.items, { empty: 'Không có sản phẩm', rowClass: (p) => (p.is_active ? '' : 'inactive') });
      pager(qs('#pr-pager'), data.page, data.total_pages, (p) => { st.page = p; load(); });
    } catch (e) { qs('#pr-table').innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
  };
  qs('#pr-go').addEventListener('click', () => { st.q = qs('#pr-q').value.trim(); st.category_id = qs('#pr-cat').value; st.sort = qs('#pr-sort').value; st.page = 1; load(); });
  qs('#pr-q').addEventListener('keydown', (e) => { if (e.key === 'Enter') qs('#pr-go').click(); });
  qs('#new-product').addEventListener('click', () => openForm({
    title: 'Thêm sản phẩm', wide: true, fields: fields(true), submitText: 'Thêm sản phẩm',
    onSubmit: async (v) => { await api('/products', { method: 'POST', body: v }); toast('Đã thêm sản phẩm'); setTimeout(load, 500); },
  }));
  qs('#pr-table').addEventListener('click', async (e) => {
    const t = e.target.closest('button');
    if (!t) return;
    try {
      if (t.dataset.edit) {
        const p = await api(`/products/${t.dataset.edit}`);
        openForm({ title: `Sửa: ${p.name}`, wide: true, fields: fields(false), values: p,
          onSubmit: async (v) => { await api(`/products/${p.id}`, { method: 'PUT', body: v }); toast('Đã lưu sản phẩm'); load(); } });
      } else if (t.dataset.off) {
        if (!(await confirmDialog('Ngừng kinh doanh sản phẩm này? Khách sẽ không thấy sản phẩm trên cửa hàng.', { okText: 'Ngừng bán', danger: true }))) return;
        await api(`/products/${t.dataset.off}`, { method: 'DELETE' }); toast('Đã ngừng bán'); load();
      } else if (t.dataset.on) {
        await api(`/products/${t.dataset.on}`, { method: 'PUT', body: { is_active: true } }); toast('Sản phẩm đã được bán lại'); load();
      }
    } catch (err) { toastError(err); }
  });
  load();
}

/* ================================================================ DANH MỤC */
async function viewCategories() {
  const c = page('Danh mục', '<button class="btn" id="new-cat">Thêm danh mục</button>');
  const fields = [
    { name: 'name', label: 'Tên danh mục', required: true },
    { name: 'icon', label: 'Biểu tượng (emoji)', placeholder: '🥫' },
    { name: 'description', label: 'Mô tả', full: true },
    { name: 'sort_order', label: 'Thứ tự hiển thị', type: 'number', min: 0, default: 0 },
    { name: 'is_active', label: 'Hiển thị trên cửa hàng', type: 'checkbox', default: true },
  ];
  const load = async () => {
    const cats = await getCategories(true);
    c.innerHTML = table([
      { label: '', render: (x) => `<span style="font-size:1.5rem">${x.icon || ''}</span>` },
      { label: 'Danh mục', render: (x) => `<b>${esc(x.name)}</b><br><span class="muted small">${esc(x.description || '')}</span>` },
      { label: 'Sản phẩm đang bán', cls: 'num', render: (x) => x.product_count },
      { label: 'Thứ tự', cls: 'num', render: (x) => x.sort_order },
      { label: 'Hiển thị', render: (x) => x.is_active ? pill('DELIVERED', 'Hiện') : pill('INACTIVE', 'Ẩn') },
      { label: '', cls: 'num', render: (x) => `<div class="row-actions"><button class="btn ghost sm" data-edit="${x.id}">Sửa</button><button class="btn ghost sm" data-del="${x.id}">Xóa</button></div>` },
    ], cats);
  };
  qs('#new-cat').addEventListener('click', () => openForm({ title: 'Thêm danh mục', fields, onSubmit: async (v) => { await api('/categories', { method: 'POST', body: v }); toast('Đã thêm danh mục'); load(); } }));
  c.addEventListener('click', async (e) => {
    const t = e.target.closest('button');
    if (!t) return;
    const cat = (categoriesCache || []).find((x) => String(x.id) === (t.dataset.edit || t.dataset.del));
    if (t.dataset.edit) openForm({ title: `Sửa: ${cat.name}`, fields, values: cat, onSubmit: async (v) => { await api(`/categories/${cat.id}`, { method: 'PUT', body: v }); toast('Đã lưu'); load(); } });
    if (t.dataset.del && await confirmDialog(`Xóa danh mục "${cat.name}"?`, { okText: 'Xóa', danger: true })) {
      try { await api(`/categories/${cat.id}`, { method: 'DELETE' }); toast('Đã xóa danh mục'); load(); } catch (err) { toastError(err); }
    }
  });
  load().catch((e) => { c.innerHTML = `<div class="empty">${esc(e.message)}</div>`; });
}

/* ================================================================ KHO HÀNG */
async function viewInventory() {
  const c = page('Kho hàng', '<button class="btn secondary" id="all-moves">Lịch sử nhập xuất</button><a class="btn" href="#receipts">Nhập hàng</a>');
  const st = { q: '', status: '', page: 1 };
  c.innerHTML = `<div class="stats" id="i-stats"></div>
    <div class="status-tabs" id="i-tabs">${[['', 'Tất cả'], ['alert', 'Cần nhập thêm'], ['low', 'Sắp hết'], ['out', 'Hết hàng']].map(([k, l]) => `<button data-s="${k}" aria-pressed="${k === ''}">${l}</button>`).join('')}</div>
    <div class="toolbar"><input type="search" id="i-q" placeholder="Tên hoặc SKU"><button class="btn secondary" id="i-go">Tìm</button></div>
    <div id="i-table"></div><nav class="pager" id="i-pager"></nav>`;
  const load = async () => {
    try {
      const [sum, data] = await Promise.all([api('/inventory/summary'), api('/inventory', { params: { ...st, page_size: 20 } })]);
      qs('#i-stats').innerHTML = stat('Mặt hàng trong kho', sum.products) + stat('Tổng số lượng tồn', sum.total_units.toLocaleString('vi-VN'), `${sum.reserved_units} đang giữ cho đơn`) +
        stat('Sắp hết / hết hàng', `${sum.low_stock} / ${sum.out_of_stock}`, 'theo ngưỡng cảnh báo', sum.out_of_stock > 0) + stat('Nhập hàng tháng này', money(sum.imports_this_month));
      qs('#i-table').innerHTML = table([
        { label: 'Sản phẩm', render: (s) => `<b>${esc(s.product_name || '#' + s.product_id)}</b><br><span class="muted small">${esc(s.sku || '')} · ${esc(s.unit || '')}</span>` },
        { label: 'Tồn thực tế', cls: 'num', render: (s) => s.quantity },
        { label: 'Đang giữ', cls: 'num', render: (s) => s.reserved },
        { label: 'Có thể bán', cls: 'num', render: (s) => `<b>${s.available}</b>` },
        { label: 'Ngưỡng', cls: 'num', render: (s) => s.min_quantity },
        { label: 'Trạng thái', render: (s) => pill(s.status === 'IN_STOCK' ? 'DELIVERED' : s.status, STOCK_LABEL[s.status]) },
        { label: '', cls: 'num', render: (s) => `<div class="row-actions"><button class="btn ghost sm" data-adjust="${s.product_id}">Điều chỉnh</button><button class="btn ghost sm" data-min="${s.product_id}" data-v="${s.min_quantity}">Ngưỡng</button><button class="btn ghost sm" data-hist="${s.product_id}">Lịch sử</button></div>` },
      ], data.items, { empty: 'Không có mặt hàng phù hợp' });
      pager(qs('#i-pager'), data.page, data.total_pages, (p) => { st.page = p; load(); });
    } catch (e) { qs('#i-table').innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
  };
  qs('#i-tabs').addEventListener('click', (e) => {
    const b = e.target.closest('[data-s]');
    if (!b) return;
    qsa('#i-tabs button').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
    st.status = b.dataset.s; st.page = 1; load();
  });
  qs('#i-go').addEventListener('click', () => { st.q = qs('#i-q').value.trim(); st.page = 1; load(); });
  qs('#i-q').addEventListener('keydown', (e) => { if (e.key === 'Enter') qs('#i-go').click(); });
  qs('#all-moves').addEventListener('click', () => showMovements());
  qs('#i-table').addEventListener('click', async (e) => {
    const t = e.target.closest('button');
    if (!t) return;
    if (t.dataset.adjust) {
      const s = await api(`/inventory/${t.dataset.adjust}`);
      openForm({
        title: `Kiểm kê: ${s.product_name}`,
        fields: [
          { name: 'new_quantity', label: `Số lượng thực tế (hiện ${s.quantity})`, type: 'number', min: s.reserved, required: true, hint: s.reserved ? `Không nhỏ hơn ${s.reserved} đang giữ cho đơn` : '' },
          { name: 'reason', label: 'Lý do', required: true, placeholder: 'Kiểm kê định kỳ, hàng hư hỏng…', full: true },
        ],
        values: { new_quantity: s.quantity },
        submitText: 'Cập nhật tồn kho',
        onSubmit: async (v) => { await api('/inventory/adjust', { method: 'POST', body: { product_id: s.product_id, ...v } }); toast('Đã cập nhật tồn kho'); load(); },
      });
    }
    if (t.dataset.min) {
      openForm({ title: 'Ngưỡng cảnh báo hết hàng', fields: [{ name: 'min_quantity', label: 'Cảnh báo khi số lượng có thể bán không quá', type: 'number', min: 0, required: true, full: true }],
        values: { min_quantity: t.dataset.v },
        onSubmit: async (v) => { await api(`/inventory/${t.dataset.min}/settings`, { method: 'PUT', body: v }); toast('Đã lưu ngưỡng'); load(); } });
    }
    if (t.dataset.hist) showMovements(t.dataset.hist);
  });
  load();
}

async function showMovements(productId) {
  const d = openDialog({ title: productId ? 'Lịch sử nhập xuất' : 'Lịch sử nhập xuất toàn kho', wide: true, body: '<div class="spinner"></div>' });
  try {
    const data = await api('/inventory/movements', { params: { product_id: productId, page_size: 50 } });
    d.body.innerHTML = table([
      { label: 'Thời gian', render: (m) => `<span class="nowrap">${fmtDate(m.created_at)}</span>` },
      { label: 'Sản phẩm', render: (m) => esc(m.product_name || '#' + m.product_id) },
      { label: 'Loại', render: (m) => esc(MOVE_LABEL[m.type] || m.type) },
      { label: 'Số lượng', cls: 'num', render: (m) => `<b style="color:${m.quantity < 0 ? 'var(--chili)' : 'var(--leaf)'}">${m.quantity > 0 ? '+' : ''}${m.quantity}</b>` },
      { label: 'Tồn sau', cls: 'num', render: (m) => m.balance_after },
      { label: 'Chứng từ', render: (m) => `${esc(m.ref_id || '')}<br><span class="muted small">${esc(m.note || '')}</span>` },
      { label: 'Người thực hiện', render: (m) => esc(m.created_by || '') },
    ], data.items, { empty: 'Chưa có biến động' });
  } catch (e) { d.body.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
}

/* ================================================================ NHẬP HÀNG */
async function viewReceipts() {
  const c = page('Phiếu nhập kho', '<button class="btn" id="new-receipt">Tạo phiếu nhập</button>');
  let pageNo = 1;
  const load = async () => {
    try {
      const data = await api('/stock-receipts', { params: { page: pageNo, page_size: 15 } });
      c.innerHTML = table([
        { label: 'Mã phiếu', render: (r) => `<b>${esc(r.code)}</b>` },
        { label: 'Nhà cung cấp', render: (r) => esc(r.supplier_name || 'Không ghi nhận') },
        { label: 'Số lượng', cls: 'num', render: (r) => r.total_quantity },
        { label: 'Tổng tiền', cls: 'num', render: (r) => money(r.total_cost) },
        { label: 'Người lập', render: (r) => esc(r.created_by || '') },
        { label: 'Thời gian', render: (r) => fmtDate(r.created_at) },
      ], data.items, { empty: 'Chưa có phiếu nhập', rowAttrs: (r) => `class="clickable" data-id="${r.id}"` }) + '<nav class="pager" id="r-pager"></nav>';
      pager(qs('#r-pager'), data.page, data.total_pages, (p) => { pageNo = p; load(); });
    } catch (e) { c.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
  };
  c.addEventListener('click', async (e) => {
    const tr = e.target.closest('tr[data-id]');
    if (!tr) return;
    const r = await api(`/stock-receipts/${tr.dataset.id}`);
    openDialog({ title: `Phiếu nhập ${r.code}`, wide: true, body: `<dl class="kv" style="margin-bottom:1rem"><dt>Nhà cung cấp</dt><dd>${esc(r.supplier_name || '—')}</dd><dt>Người lập</dt><dd>${esc(r.created_by)}</dd><dt>Thời gian</dt><dd>${fmtDate(r.created_at)}</dd>${r.note ? `<dt>Ghi chú</dt><dd>${esc(r.note)}</dd>` : ''}</dl>` +
      table([
        { label: 'Sản phẩm', render: (i) => esc(i.product_name || '#' + i.product_id) },
        { label: 'Số lượng', cls: 'num', render: (i) => i.quantity },
        { label: 'Giá nhập', cls: 'num', render: (i) => money(i.unit_cost) },
        { label: 'Thành tiền', cls: 'num', render: (i) => money(i.line_total) },
      ], r.items) + `<p style="text-align:right;margin-top:1rem">Tổng cộng ${priceTag(r.total_cost)}</p>` });
  });
  qs('#new-receipt').addEventListener('click', () => newReceipt(load));
  load();
}

async function newReceipt(onDone) {
  const suppliers = (await api('/suppliers')).items;
  const lines = new Map();
  const d = openDialog({
    title: 'Tạo phiếu nhập kho', wide: true,
    body: `<div class="form-grid">
        <label class="field">Nhà cung cấp<select id="rc-sup"><option value="">Không chọn</option>${suppliers.map((s) => `<option value="${s.id}">${esc(s.name)}</option>`).join('')}</select></label>
        <label class="field">Ghi chú<input id="rc-note" placeholder="Số hóa đơn NCC, ghi chú…"></label>
        <label class="field full">Thêm sản phẩm<input id="rc-search" placeholder="Gõ tên hoặc SKU để tìm" autocomplete="off"><div class="pick-results hidden" id="rc-results"></div></label>
      </div>
      <div id="rc-lines" style="margin-top:1rem"></div>`,
    footer: '<span id="rc-total" style="margin-right:auto"></span><button class="btn secondary" data-close>Hủy</button><button class="btn" id="rc-save" disabled>Lưu phiếu & nhập kho</button>',
  });
  const render = () => {
    const arr = [...lines.values()];
    d.el.querySelector('#rc-lines').innerHTML = arr.length ? `<div class="table-wrap"><table class="data"><thead><tr><th>Sản phẩm</th><th class="num">Số lượng</th><th class="num">Giá nhập (đ)</th><th class="num">Thành tiền</th><th></th></tr></thead><tbody>
      ${arr.map((l) => `<tr data-id="${l.id}"><td>${esc(l.name)}</td><td class="num"><input type="number" min="1" value="${l.quantity}" data-f="quantity" style="width:90px"></td>
        <td class="num"><input type="number" min="0" step="500" value="${l.unit_cost}" data-f="unit_cost" style="width:120px"></td><td class="num">${money(l.quantity * l.unit_cost)}</td>
        <td><button class="btn ghost sm" data-rm>Bỏ</button></td></tr>`).join('')}</tbody></table></div>`
      : '<div class="empty"><strong>Chưa có sản phẩm</strong>Tìm sản phẩm ở ô phía trên để thêm vào phiếu.</div>';
    const total = arr.reduce((s, l) => s + l.quantity * l.unit_cost, 0);
    d.el.querySelector('#rc-total').innerHTML = arr.length ? `Tổng: <b>${money(total)}</b>` : '';
    d.el.querySelector('#rc-save').disabled = !arr.length;
  };
  const results = d.el.querySelector('#rc-results');
  d.el.querySelector('#rc-search').addEventListener('input', debounce(async (e) => {
    const q = e.target.value.trim();
    if (q.length < 2) { results.classList.add('hidden'); return; }
    const data = await api('/products', { params: { q, page_size: 8, include_inactive: 1 } });
    results.innerHTML = data.items.map((p) => `<button type="button" data-p='${esc(JSON.stringify({ id: p.id, name: p.name, price: p.price }))}'><span>${esc(p.name)} <span class="muted small">${esc(p.sku)}</span></span><span class="muted small">Tồn ${p.available ?? '?'}</span></button>`).join('') || '<p class="muted small" style="padding:.5rem .7rem;margin:0">Không tìm thấy</p>';
    results.classList.remove('hidden');
  }));
  results.addEventListener('click', (e) => {
    const b = e.target.closest('[data-p]');
    if (!b) return;
    const p = JSON.parse(b.dataset.p);
    if (!lines.has(p.id)) lines.set(p.id, { id: p.id, name: p.name, quantity: 10, unit_cost: Math.round(p.price * 0.75 / 500) * 500 });
    results.classList.add('hidden');
    d.el.querySelector('#rc-search').value = '';
    render();
  });
  d.el.querySelector('#rc-lines').addEventListener('input', (e) => {
    const tr = e.target.closest('tr[data-id]');
    if (!tr || !e.target.dataset.f) return;
    lines.get(Number(tr.dataset.id))[e.target.dataset.f] = Math.max(0, Number(e.target.value || 0));
  });
  d.el.querySelector('#rc-lines').addEventListener('change', render);
  d.el.querySelector('#rc-lines').addEventListener('click', (e) => { const tr = e.target.closest('tr[data-id]'); if (tr && e.target.closest('[data-rm]')) { lines.delete(Number(tr.dataset.id)); render(); } });
  d.el.querySelector('#rc-save').addEventListener('click', async (e) => {
    setBusy(e.currentTarget, true);
    try {
      const r = await api('/stock-receipts', { method: 'POST', body: {
        supplier_id: d.el.querySelector('#rc-sup').value || undefined, note: d.el.querySelector('#rc-note').value.trim() || undefined,
        items: [...lines.values()].map((l) => ({ product_id: l.id, quantity: l.quantity, unit_cost: l.unit_cost })) } });
      toast(`Đã nhập kho theo phiếu ${r.code}`);
      d.close(); onDone && onDone();
    } catch (err) { toastError(err); setBusy(e.currentTarget, false); }
  });
  render();
}

/* ================================================================ NHÀ CUNG CẤP */
async function viewSuppliers() {
  const c = page('Nhà cung cấp', '<button class="btn" id="new-sup">Thêm nhà cung cấp</button>');
  const fields = [
    { name: 'name', label: 'Tên nhà cung cấp', required: true, full: true },
    { name: 'contact_person', label: 'Người liên hệ' }, { name: 'phone', label: 'Điện thoại' },
    { name: 'email', label: 'Email', type: 'email' }, { name: 'address', label: 'Địa chỉ' },
    { name: 'note', label: 'Ghi chú', type: 'textarea', full: true },
  ];
  let items = [];
  const load = async () => {
    items = (await api('/suppliers', { params: { all: 1 } })).items;
    c.innerHTML = table([
      { label: 'Nhà cung cấp', render: (s) => `<b>${esc(s.name)}</b><br><span class="muted small">${esc(s.address || '')}</span>` },
      { label: 'Liên hệ', render: (s) => `${esc(s.contact_person || '')}<br><span class="muted small">${esc(s.phone || '')} ${esc(s.email || '')}</span>` },
      { label: 'Số phiếu nhập', cls: 'num', render: (s) => s.receipt_count },
      { label: 'Tổng đã nhập', cls: 'num', render: (s) => money(s.total_purchased) },
      { label: 'Trạng thái', render: (s) => s.is_active ? pill('DELIVERED', 'Đang hợp tác') : pill('INACTIVE', 'Ngừng') },
      { label: '', cls: 'num', render: (s) => `<div class="row-actions"><button class="btn ghost sm" data-edit="${s.id}">Sửa</button>${IS_ADMIN && s.is_active ? `<button class="btn ghost sm" data-off="${s.id}">Ngừng</button>` : ''}</div>` },
    ], items, { empty: 'Chưa có nhà cung cấp' });
  };
  qs('#new-sup').addEventListener('click', () => openForm({ title: 'Thêm nhà cung cấp', fields, onSubmit: async (v) => { await api('/suppliers', { method: 'POST', body: v }); toast('Đã thêm'); load(); } }));
  c.addEventListener('click', async (e) => {
    const t = e.target.closest('button');
    if (!t) return;
    const s = items.find((x) => String(x.id) === (t.dataset.edit || t.dataset.off));
    if (t.dataset.edit) openForm({ title: `Sửa: ${s.name}`, fields: [...fields, { name: 'is_active', label: 'Đang hợp tác', type: 'checkbox' }], values: s, onSubmit: async (v) => { await api(`/suppliers/${s.id}`, { method: 'PUT', body: v }); toast('Đã lưu'); load(); } });
    if (t.dataset.off && await confirmDialog(`Ngừng hợp tác với ${s.name}?`, { danger: true, okText: 'Ngừng hợp tác' })) {
      try { await api(`/suppliers/${s.id}`, { method: 'DELETE' }); toast('Đã cập nhật'); load(); } catch (err) { toastError(err); }
    }
  });
  load().catch((e) => { c.innerHTML = `<div class="empty">${esc(e.message)}</div>`; });
}

/* ================================================================ MÃ GIẢM GIÁ */
async function viewCoupons() {
  const c = page('Mã giảm giá', '<button class="btn" id="new-coupon">Tạo mã</button>');
  const STATE = { ACTIVE: 'Đang chạy', UPCOMING: 'Sắp diễn ra', EXPIRED: 'Hết hạn', USED_UP: 'Hết lượt', INACTIVE: 'Tạm tắt' };
  const fields = [
    { name: 'code', label: 'Mã', required: true, placeholder: 'VD: TET2027' },
    { name: 'name', label: 'Tên chương trình', required: true },
    { name: 'discount_type', label: 'Loại giảm', type: 'select', options: [['PERCENT', 'Theo phần trăm (%)'], ['FIXED', 'Số tiền cố định (đ)']] },
    { name: 'discount_value', label: 'Mức giảm', type: 'number', required: true, min: 1 },
    { name: 'max_discount', label: 'Giảm tối đa (đ)', type: 'number', min: 0, hint: 'Chỉ áp dụng cho loại %' },
    { name: 'min_order_value', label: 'Đơn tối thiểu (đ)', type: 'number', min: 0, default: 0 },
    { name: 'usage_limit', label: 'Tổng lượt dùng', type: 'number', min: 1, hint: 'Để trống nếu không giới hạn' },
    { name: 'per_user_limit', label: 'Lượt dùng mỗi khách', type: 'number', min: 1, default: 1 },
    { name: 'start_at', label: 'Bắt đầu', type: 'datetime-local' },
    { name: 'end_at', label: 'Kết thúc', type: 'datetime-local' },
    { name: 'description', label: 'Mô tả cho khách', full: true },
    { name: 'is_public', label: 'Hiển thị công khai trên cửa hàng', type: 'checkbox', default: true },
    { name: 'is_active', label: 'Kích hoạt', type: 'checkbox', default: true },
  ];
  let items = [];
  const load = async () => {
    items = (await api('/coupons', { params: { page_size: 100 } })).items;
    c.innerHTML = table([
      { label: 'Mã', render: (x) => `<b>${esc(x.code)}</b><br><span class="muted small">${esc(x.name)}</span>` },
      { label: 'Ưu đãi', render: (x) => `${esc(x.label)}<br><span class="muted small">Đơn từ ${money(x.min_order_value)}</span>` },
      { label: 'Đã dùng', cls: 'num', render: (x) => `${x.used_count}${x.usage_limit ? ' / ' + x.usage_limit : ''}` },
      { label: 'Thời gian', render: (x) => `<span class="small">${x.start_at ? fmtDate(x.start_at, false) : '…'} – ${x.end_at ? fmtDate(x.end_at, false) : '…'}</span>` },
      { label: 'Hiển thị', render: (x) => x.is_public ? 'Công khai' : 'Mã riêng' },
      { label: 'Trạng thái', render: (x) => pill(x.state === 'ACTIVE' ? 'DELIVERED' : x.state, STATE[x.state]) },
      { label: '', cls: 'num', render: (x) => `<div class="row-actions"><button class="btn ghost sm" data-usage="${x.id}">Lượt dùng</button><button class="btn ghost sm" data-edit="${x.id}">Sửa</button><button class="btn ghost sm" data-del="${x.id}">Xóa</button></div>` },
    ], items, { empty: 'Chưa có mã giảm giá' });
  };
  qs('#new-coupon').addEventListener('click', () => openForm({ title: 'Tạo mã giảm giá', wide: true, fields, onSubmit: async (v) => { await api('/coupons', { method: 'POST', body: v }); toast('Đã tạo mã'); load(); } }));
  c.addEventListener('click', async (e) => {
    const t = e.target.closest('button');
    if (!t) return;
    const x = items.find((i) => String(i.id) === (t.dataset.edit || t.dataset.del || t.dataset.usage));
    try {
      if (t.dataset.edit) openForm({ title: `Sửa mã ${x.code}`, wide: true, fields, values: x, onSubmit: async (v) => { await api(`/coupons/${x.id}`, { method: 'PUT', body: v }); toast('Đã lưu'); load(); } });
      if (t.dataset.del && await confirmDialog(`Xóa mã ${x.code}? Mã đã có lượt dùng sẽ được tắt thay vì xóa.`, { danger: true, okText: 'Xóa' })) {
        const r = await api(`/coupons/${x.id}`, { method: 'DELETE' }); toast(r.message); load();
      }
      if (t.dataset.usage) {
        const u = await api(`/coupons/${x.id}/usages`, { params: { page_size: 50 } });
        openDialog({ title: `Lượt dùng mã ${x.code}`, wide: true, body: table([
          { label: 'Đơn hàng', render: (r) => `#${r.order_id}` }, { label: 'Khách (ID)', render: (r) => r.user_id ?? 'Khách lẻ' },
          { label: 'Đã giảm', cls: 'num', render: (r) => money(r.discount_amount) }, { label: 'Trạng thái', render: (r) => r.status === 'USED' ? pill('DELIVERED', 'Đã dùng') : pill('CANCELLED', 'Đã hoàn lượt') },
          { label: 'Thời gian', render: (r) => fmtDate(r.created_at) }], u.items, { empty: 'Chưa có lượt dùng' }) });
      }
    } catch (err) { toastError(err); }
  });
  load().catch((e) => { c.innerHTML = `<div class="empty">${esc(e.message)}</div>`; });
}

/* ================================================================ NGƯỜI DÙNG */
async function viewUsers() {
  if (!IS_ADMIN) { location.hash = '#dashboard'; return; }
  const c = page('Người dùng', '<button class="btn" id="new-user">Thêm tài khoản</button>');
  const st = { q: '', role: '', page: 1 };
  c.innerHTML = `<div class="toolbar"><input type="search" id="u-q" placeholder="Tên, email hoặc số điện thoại">
    <select id="u-role"><option value="">Mọi vai trò</option>${Object.entries(ROLE_LABEL).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select>
    <button class="btn secondary" id="u-go">Lọc</button></div><div id="u-table"></div><nav class="pager" id="u-pager"></nav>`;
  let items = [];
  const roleOptions = Object.entries(ROLE_LABEL);
  const load = async () => {
    const data = await api('/users', { params: { ...st, page_size: 20 } });
    items = data.items;
    qs('#u-table').innerHTML = table([
      { label: 'Họ tên', render: (u) => `<b>${esc(u.full_name)}</b><br><span class="muted small">${esc(u.email)}</span>` },
      { label: 'Điện thoại', render: (u) => esc(u.phone || '—') },
      { label: 'Vai trò', render: (u) => pill(u.role === 'customer' ? 'DELIVERED' : u.role, ROLE_LABEL[u.role]) },
      { label: 'Trạng thái', render: (u) => u.is_active ? 'Hoạt động' : pill('locked', 'Đã khóa') },
      { label: 'Đăng nhập gần nhất', render: (u) => u.last_login_at ? timeAgo(u.last_login_at) : '—' },
      { label: 'Ngày tạo', render: (u) => fmtDate(u.created_at, false) },
      { label: '', cls: 'num', render: (u) => `<button class="btn ghost sm" data-edit="${u.id}">Sửa</button>` },
    ], items, { empty: 'Không có người dùng phù hợp' });
    pager(qs('#u-pager'), data.page, data.total_pages, (p) => { st.page = p; load(); });
  };
  qs('#u-go').addEventListener('click', () => { st.q = qs('#u-q').value.trim(); st.role = qs('#u-role').value; st.page = 1; load(); });
  qs('#u-q').addEventListener('keydown', (e) => { if (e.key === 'Enter') qs('#u-go').click(); });
  qs('#new-user').addEventListener('click', () => openForm({ title: 'Thêm tài khoản', fields: [
    { name: 'full_name', label: 'Họ tên', required: true }, { name: 'email', label: 'Email', type: 'email', required: true },
    { name: 'phone', label: 'Điện thoại' }, { name: 'role', label: 'Vai trò', type: 'select', options: roleOptions, default: 'staff' },
    { name: 'password', label: 'Mật khẩu', type: 'password', required: true, hint: 'Ít nhất 6 ký tự', full: true },
  ], onSubmit: async (v) => { await api('/users', { method: 'POST', body: v }); toast('Đã tạo tài khoản'); load(); } }));
  qs('#u-table').addEventListener('click', (e) => {
    const t = e.target.closest('[data-edit]');
    if (!t) return;
    const u = items.find((x) => String(x.id) === t.dataset.edit);
    openForm({ title: `Sửa: ${u.full_name}`, values: u, fields: [
      { name: 'full_name', label: 'Họ tên', required: true }, { name: 'phone', label: 'Điện thoại' },
      { name: 'role', label: 'Vai trò', type: 'select', options: roleOptions },
      { name: 'password', label: 'Đặt lại mật khẩu', type: 'password', hint: 'Để trống nếu giữ nguyên' },
      { name: 'is_active', label: 'Cho phép đăng nhập', type: 'checkbox', full: true },
    ], onSubmit: async (v) => { if (!v.password) delete v.password; await api(`/users/${u.id}`, { method: 'PUT', body: v }); toast('Đã lưu'); load(); } });
  });
  load().catch((e) => { qs('#u-table').innerHTML = `<div class="empty">${esc(e.message)}</div>`; });
}

/* ================================================================ THÔNG BÁO & EMAIL */
async function viewNotifications() {
  const c = page('Thông báo', '<button class="btn secondary" id="read-all">Đánh dấu đã đọc tất cả</button>');
  let pageNo = 1;
  const load = async () => {
    const data = await api('/notifications', { params: { page: pageNo, page_size: 20 } });
    c.innerHTML = table([
      { label: '', render: (n) => n.is_read ? '' : '<span class="badge red" title="Chưa đọc">•</span>' },
      { label: 'Nội dung', render: (n) => `<b>${esc(n.title)}</b><br><span class="small">${esc(n.message)}</span>` },
      { label: 'Thời gian', render: (n) => `<span class="nowrap">${timeAgo(n.created_at)}</span>` },
      { label: '', cls: 'num', render: (n) => n.link && n.link.startsWith('/admin/') ? `<a class="btn ghost sm" href="${esc(n.link.replace('/admin/', ''))}" data-read="${n.id}">Xem</a>` : (n.is_read ? '' : `<button class="btn ghost sm" data-read="${n.id}">Đã đọc</button>`) },
    ], data.items, { empty: 'Chưa có thông báo' }) + '<nav class="pager" id="n-pager"></nav>';
    pager(qs('#n-pager'), data.page, data.total_pages, (p) => { pageNo = p; load(); });
    refreshNotifBadge();
  };
  c.addEventListener('click', async (e) => {
    const t = e.target.closest('[data-read]');
    if (t) { await api(`/notifications/${t.dataset.read}/read`, { method: 'PUT' }).catch(() => {}); if (t.tagName === 'BUTTON') load(); else refreshNotifBadge(); }
  });
  qs('#read-all').addEventListener('click', async () => { await api('/notifications/read-all', { method: 'PUT' }).catch(toastError); load(); });
  load().catch((e) => { c.innerHTML = `<div class="empty">${esc(e.message)}</div>`; });
}

async function viewEmails() {
  if (!IS_ADMIN) { location.hash = '#dashboard'; return; }
  const c = page('Email đã gửi');
  let pageNo = 1;
  let items = [];
  const load = async () => {
    const data = await api('/notifications/emails', { params: { page: pageNo, page_size: 20 } });
    items = data.items;
    c.innerHTML = `<p class="muted">Email được mô phỏng và ghi lại tại đây (có thể thay bằng SMTP khi triển khai thật).</p>` + table([
      { label: 'Người nhận', render: (m) => esc(m.to_email) },
      { label: 'Tiêu đề', render: (m) => esc(m.subject) },
      { label: 'Sự kiện', render: (m) => `<code>${esc(m.event_type || '')}</code>` },
      { label: 'Thời gian', render: (m) => fmtDate(m.created_at) },
    ], items, { empty: 'Chưa có email nào', rowAttrs: (m) => `class="clickable" data-id="${m.id}"` }) + '<nav class="pager" id="e-pager"></nav>';
    pager(qs('#e-pager'), data.page, data.total_pages, (p) => { pageNo = p; load(); });
  };
  c.addEventListener('click', (e) => {
    const tr = e.target.closest('tr[data-id]');
    if (!tr) return;
    const m = items.find((x) => String(x.id) === tr.dataset.id);
    openDialog({ title: m.subject, body: `<p class="muted small">Gửi đến ${esc(m.to_email)} lúc ${fmtDate(m.created_at)}</p><pre style="white-space:pre-wrap;font-family:var(--font-body)">${esc(m.body)}</pre>` });
  });
  load().catch((e) => { c.innerHTML = `<div class="empty">${esc(e.message)}</div>`; });
}

/* ================================================================ TRẠNG THÁI DỊCH VỤ */
async function viewSystem() {
  const c = page('Trạng thái dịch vụ', '<a class="btn secondary" href="/api-docs.html" target="_blank" rel="noopener">Hợp đồng dịch vụ</a><button class="btn secondary" id="refresh">Kiểm tra lại</button>');
  const LAYER_LABEL = { task: 'Task', entity: 'Entity', utility: 'Utility', infrastructure: 'Hạ tầng', integration: 'Tích hợp' };
  const load = async () => {
    c.innerHTML = '<div class="spinner"></div>';
    let data;
    try {
      const res = await fetch('/api/health');
      data = await res.json();
    } catch (e) { c.innerHTML = `<div class="empty"><strong>Không kết nối được API Gateway</strong></div>`; return; }
    let reg = null;
    try { reg = await api('/registry'); } catch { reg = null; }
    const services = Object.entries(data.services);
    const up = services.filter(([, s]) => s.status === 'UP').length;
    const instances = reg ? Object.values(reg.services).reduce((n, s) => n + s.instances.length, 0) : 0;
    const rows = reg ? Object.entries(reg.services).flatMap(([name, s]) => s.instances.map((i) => ({ name, layer: s.layer, version: s.version, ...i }))) : [];
    c.innerHTML = `<div class="stats">${stat('API Gateway / ESB', data.gateway === 'UP' ? 'Hoạt động' : 'Lỗi')}${stat('Dịch vụ hoạt động', `${up} / ${services.length}`, '', up < services.length)}
        ${stat('Instance trong registry', reg ? instances : '—', reg ? `TTL heartbeat ${reg.ttl} giây` : 'Registry không phản hồi, đang dùng địa chỉ dự phòng', !reg)}
        ${stat('Event bus', esc(data.event_bus), data.event_bus === 'rabbitmq' ? 'RabbitMQ topic exchange' : 'Chế độ local qua HTTP')}</div>` +
      `<div class="box" style="margin-bottom:1rem"><h2>Sức khỏe dịch vụ <small>kiểm tra lúc ${fmtDate(data.time).slice(11)}</small></h2>` +
      table([
        { label: 'Dịch vụ', render: ([k, s]) => `<b>${esc(s.label)}</b><br><code class="small">${esc(k)}</code>` },
        { label: 'Lớp', render: ([, s]) => esc(LAYER_LABEL[s.layer] || s.layer || '—') },
        { label: 'Trạng thái', render: ([, s]) => pill(s.status === 'UP' ? 'DELIVERED' : 'CANCELLED', s.status) },
        { label: 'Độ trễ', cls: 'num', render: ([, s]) => (s.latency_ms != null ? s.latency_ms + ' ms' : '—') },
        { label: 'Instance', cls: 'num', render: ([, s]) => s.instances ?? '—' },
        { label: 'Địa chỉ từ', render: ([k, s]) => (k === 'registry' ? 'Địa chỉ cố định' : s.discovery === 'registry' ? 'Service Registry' : 'Cấu hình dự phòng') },
        { label: 'CSDL', render: ([, s]) => esc(s.database || '—') },
        { label: 'Circuit breaker', render: ([, s]) => esc(s.circuit || '') },
      ], services) + '</div>' +
      `<div class="box"><h2>Danh bạ dịch vụ (Service Registry) <small>service tự đăng ký và gửi heartbeat</small></h2>` +
      (reg ? table([
        { label: 'Service', render: (r) => `<b>${esc(r.name)}</b>` },
        { label: 'Lớp', render: (r) => esc(LAYER_LABEL[r.layer] || r.layer) },
        { label: 'Phiên bản', render: (r) => esc(r.version) },
        { label: 'Instance', render: (r) => `<code class="small">${esc(r.instance_id)}</code>` },
        { label: 'Địa chỉ', render: (r) => `<code class="small">${esc(r.url)}</code>` },
        { label: 'Trạng thái', render: (r) => pill(r.status === 'UP' ? 'DELIVERED' : 'CANCELLED', r.status) },
        { label: 'Heartbeat', cls: 'num', render: (r) => `${r.last_seen_seconds}s trước` },
      ], rows, { empty: 'Chưa có service nào đăng ký' }) : '<div class="banner">Không liên lạc được Service Registry. Gateway và các service đang dùng địa chỉ cấu hình dự phòng.</div>') + '</div>' +
      `<div class="box" style="margin-top:1rem"><h2>Kiến trúc hướng dịch vụ</h2><p class="small">
        <b>Tầng tích hợp:</b> API Gateway (xác thực JWT, định tuyến theo tên dịch vụ, dàn xếp SOAP ↔ REST) và Service Registry (đăng ký, tra cứu).
        <b>Task service:</b> order điều phối quy trình đặt hàng bằng Saga.
        <b>Entity service:</b> auth, product, inventory, cart, payment, promotion — mỗi service một CSDL, tái sử dụng cho cả kênh online và bán tại quầy.
        <b>Utility service:</b> notification lắng nghe sự kiện qua event bus. Mọi service công bố hợp đồng OpenAPI tại /contract.</p></div>`;
  };
  qs('#refresh').addEventListener('click', load);
  load();
}

/* ================================================================ điều hướng */
const VIEWS = {
  dashboard: viewDashboard, orders: viewOrders, pos: viewPos, payments: viewPayments, products: viewProducts,
  categories: viewCategories, inventory: viewInventory, receipts: viewReceipts, suppliers: viewSuppliers,
  coupons: viewCoupons, users: viewUsers, notifications: viewNotifications, emails: viewEmails, system: viewSystem,
};

function route() {
  const name = (location.hash || '#dashboard').slice(1);
  const view = VIEWS[name] || viewDashboard;
  qsa('.side a.nav').forEach((a) => a.toggleAttribute('aria-current', a.getAttribute('href') === '#' + name));
  qsa('.side a.nav[aria-current]').forEach((a) => a.setAttribute('aria-current', 'page'));
  qsa('.overlay').forEach((o) => o.remove());
  view();
  $view.focus({ preventScroll: true });
  window.scrollTo(0, 0);
}

async function refreshPendingBadge() {
  try {
    const d = await api('/orders', { params: { status: 'PENDING', page_size: 1 } });
    const b = qs('#pending-badge');
    b.textContent = d.total; b.classList.toggle('hidden', !d.total);
  } catch { /* bỏ qua */ }
}
async function refreshNotifBadge() {
  try {
    const { unread } = await api('/notifications/unread-count');
    const b = qs('#notif-badge');
    b.textContent = unread > 99 ? '99+' : unread; b.classList.toggle('hidden', !unread);
  } catch { /* bỏ qua */ }
}

if (Session.isStaff) {
  window.addEventListener('hashchange', route);
  route();
  refreshPendingBadge();
  refreshNotifBadge();
  setInterval(() => { refreshPendingBadge(); refreshNotifBadge(); }, 30000);
}
