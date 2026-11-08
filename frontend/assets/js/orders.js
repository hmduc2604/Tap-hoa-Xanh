/* Đơn hàng của khách: danh sách, chi tiết, hủy đơn, thanh toán lại, đánh giá */
if (requireLogin()) {
  renderShell('orders');
  let status = '';
  let page = 1;

  async function loadList() {
    const box = qs('#list');
    box.innerHTML = '<div class="spinner"></div>';
    try {
      const data = await api('/orders/my', { params: { status, page, page_size: 8 } });
      box.innerHTML = data.items.length ? data.items.map((o) => `
        <article class="order-card" data-id="${o.id}" tabindex="0" role="button" aria-label="Xem đơn ${esc(o.code)}">
          <div>
            <div class="code">#${esc(o.code)}</div>
            <div class="items">${o.preview_items.map((i) => `${i.category_icon || ''} ${esc(i.product_name)} ×${i.quantity}`).join(', ')}${o.item_count > 3 ? '…' : ''}</div>
            <div class="muted small">${fmtDate(o.created_at)} · ${esc(PAY_METHOD[o.payment_method] || o.payment_method)}</div>
          </div>
          <div class="right">${pill(o.status, o.status_label)}<b>${money(o.total)}</b>
            ${o.payment_status !== 'UNPAID' ? pill(o.payment_status === 'PAID' ? 'DELIVERED' : o.payment_status, o.payment_status_label) : ''}</div>
        </article>`).join('')
        : `<div class="empty"><strong>${status ? 'Không có đơn ở trạng thái này' : 'Bạn chưa có đơn hàng nào'}</strong><p><a class="btn" href="/">Bắt đầu mua sắm</a></p></div>`;
      pager(qs('#pager'), data.page, data.total_pages, (p) => { page = p; loadList(); });
    } catch (e) { box.innerHTML = `<div class="empty"><strong>Không tải được đơn hàng</strong>${esc(e.message)}</div>`; }
  }

  qs('#tabs').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-status]');
    if (!b) return;
    qsa('#tabs button').forEach((x) => x.setAttribute('aria-selected', String(x === b)));
    status = b.dataset.status; page = 1; loadList();
  });
  qs('#list').addEventListener('click', (e) => { const c = e.target.closest('.order-card'); if (c) openOrder(c.dataset.id); });
  qs('#list').addEventListener('keydown', (e) => { if (e.key === 'Enter' && e.target.matches('.order-card')) openOrder(e.target.dataset.id); });

  function paymentSection(o) {
    const p = o.payment;
    if (!p) return '';
    let extra = '';
    if (p.status === 'PENDING' && p.method === 'BANK_TRANSFER' && p.instructions) {
      const i = p.instructions;
      extra = `<dl class="bank-box"><dt>Ngân hàng</dt><dd>${esc(i.bank_name)}</dd><dt>Số tài khoản</dt><dd>${esc(i.account_number)}</dd>
        <dt>Chủ tài khoản</dt><dd>${esc(i.account_name)}</dd><dt>Số tiền</dt><dd>${money(i.amount)}</dd><dt>Nội dung</dt><dd>${esc(i.content)}</dd></dl>
        <p class="muted small" style="margin-top:.5rem">Cửa hàng sẽ xác nhận khi nhận được tiền. Bản demo có thể bấm nút dưới để mô phỏng đã chuyển khoản.</p>
        <button class="btn secondary" data-pay="${p.id}">Tôi đã chuyển khoản (mô phỏng)</button>`;
    }
    if (p.status === 'PENDING' && p.method === 'EWALLET') {
      extra = `<a class="btn yellow" href="/pay.html?payment_id=${p.id}">Thanh toán bằng Xanh Pay</a>`;
    }
    return `<section class="panel"><h2>Thanh toán</h2>
      <p>${esc(p.method_label)} · ${pill(p.status === 'PAID' ? 'DELIVERED' : p.status, p.status_label)}
      ${p.transaction_ref ? `<br><span class="muted small">Mã giao dịch ${esc(p.transaction_ref)}</span>` : ''}</p>${extra}</section>`;
  }

  async function openOrder(id) {
    const d = openDialog({ title: 'Chi tiết đơn hàng', body: '<div class="spinner"></div>', wide: true });
    const render = async () => {
      try {
        const o = await api(`/orders/${id}`);
        d.body.innerHTML = `
          <div class="page-title" style="margin-bottom:.6rem"><h2 style="margin:0">#${esc(o.code)}</h2>${pill(o.status, o.status_label)}</div>
          <div class="two-col" style="grid-template-columns:1fr 300px">
            <div>
              <section class="panel"><h2>Sản phẩm</h2>
                ${o.items.map((i) => `<div class="line-item">${thumb({ category_icon: i.category_icon }, 'sm')}
                  <div><div class="title">${esc(i.product_name)}</div><div class="muted small">${money(i.unit_price)} × ${i.quantity}</div>
                  ${o.status === 'DELIVERED' ? `<button class="btn ghost sm" data-review="${i.product_id}" data-name="${esc(i.product_name)}">Viết đánh giá</button>` : ''}</div>
                  <div class="right"><span class="total">${money(i.line_total)}</span></div></div>`).join('')}
                <div class="sum" style="margin-top:.8rem">
                  <div><span>Tạm tính</span><span>${money(o.subtotal)}</span></div>
                  ${o.discount ? `<div class="discount"><span>Giảm giá (${esc(o.coupon_code)})</span><span>−${money(o.discount)}</span></div>` : ''}
                  <div><span>Phí giao hàng</span><span>${o.shipping_fee ? money(o.shipping_fee) : 'Miễn phí'}</span></div>
                  <div class="grand"><span>Tổng cộng</span>${priceTag(o.total)}</div>
                </div>
              </section>
              ${paymentSection(o)}
            </div>
            <div>
              <section class="panel"><h2>Giao đến</h2><p><b>${esc(o.customer_name)}</b> · ${esc(o.customer_phone || '')}<br>${esc(o.shipping_address || '')}</p>
                ${o.note ? `<p class="muted small">Ghi chú: ${esc(o.note)}</p>` : ''}</section>
              <section class="panel"><h2>Hành trình đơn</h2><ol class="timeline">
                ${o.history.map((h) => `<li class="${h.status}"><b>${esc(h.status_label)}</b><div class="small">${esc(h.note || '')}</div><time>${fmtDate(h.created_at)}</time></li>`).join('')}
              </ol></section>
              ${o.can_cancel ? '<button class="btn danger block" data-cancel>Hủy đơn hàng</button>' : ''}
            </div>
          </div>`;
      } catch (e) { d.body.innerHTML = `<div class="empty"><strong>Không tải được đơn hàng</strong>${esc(e.message)}</div>`; }
    };
    await render();
    d.body.addEventListener('click', async (e) => {
      if (e.target.closest('[data-cancel]')) {
        const reason = await confirmDialog('Bạn chắc chắn muốn hủy đơn hàng này?', { okText: 'Hủy đơn', danger: true, input: { label: 'Lý do (không bắt buộc)', placeholder: 'Ví dụ: đặt nhầm sản phẩm' } });
        if (reason === null) return;
        try { await api(`/orders/${id}/cancel`, { method: 'POST', body: { reason: reason || undefined } }); toast('Đã hủy đơn hàng'); render(); loadList(); }
        catch (err) { toastError(err); }
      }
      const pay = e.target.closest('[data-pay]');
      if (pay) {
        setBusy(pay, true);
        try { await api(`/payments/${pay.dataset.pay}/pay`, { method: 'POST', body: { success: true } }); toast('Đã ghi nhận thanh toán'); setTimeout(() => { render(); loadList(); }, 800); }
        catch (err) { toastError(err); setBusy(pay, false); }
      }
      const rv = e.target.closest('[data-review]');
      if (rv) openReview(rv.dataset.review, rv.dataset.name);
    });
  }

  function openReview(productId, name) {
    const d = openDialog({
      title: `Đánh giá: ${name}`,
      body: `<form id="rv-form" style="display:grid;gap:.9rem">
        <fieldset style="border:0;padding:0;margin:0"><legend class="small" style="font-weight:600;margin-bottom:.3rem">Chấm điểm</legend>
          <div class="options" style="grid-template-columns:repeat(5,1fr)">${[5, 4, 3, 2, 1].map((n) => `<label class="option" style="justify-content:center"><input type="radio" name="rating" value="${n}" ${n === 5 ? 'checked' : ''}><span class="stars">${'★'.repeat(n)}</span></label>`).join('')}</div>
        </fieldset>
        <label class="field">Nhận xét<textarea name="comment" placeholder="Sản phẩm có tươi, đúng mô tả không?"></textarea></label></form>`,
      footer: '<button class="btn secondary" data-close>Để sau</button><button class="btn" id="rv-send">Gửi đánh giá</button>',
    });
    d.el.querySelector('#rv-send').addEventListener('click', async (e) => {
      const f = formData(d.el.querySelector('#rv-form'));
      setBusy(e.currentTarget, true);
      try { await api(`/products/${productId}/reviews`, { method: 'POST', body: { rating: Number(f.rating), comment: f.comment } }); toast('Cảm ơn bạn đã đánh giá'); d.close(); }
      catch (err) { toastError(err); setBusy(e.currentTarget, false); }
    });
  }

  loadList();
  if (param('id')) {
    if (param('new')) toast('Đặt hàng thành công!');
    openOrder(param('id'));
  }
}
