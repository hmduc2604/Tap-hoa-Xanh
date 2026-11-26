/* Giỏ hàng & đặt hàng */
if (requireLogin()) {
  renderShell('cart');
  let cart = null;
  let addresses = [];
  let coupon = '';
  let togetherFor = null;

  async function loadCart() {
    try {
      cart = await api('/cart');
    } catch (e) {
      qs('#items').innerHTML = `<div class="empty"><strong>Không tải được giỏ hàng</strong>${esc(e.message)}</div>`;
      return;
    }
    qs('#cart-count').textContent = cart.item_count;
    if (!cart.items.length) {
      qs('#items').innerHTML = '<div class="empty"><strong>Giỏ hàng đang trống</strong>Chọn vài món trên kệ rồi quay lại đây nhé.<p style="margin-top:1rem"><a class="btn" href="/">Đi chọn hàng</a></p></div>';
      qs('#place-order').disabled = true;
      renderSummary(null);
      return;
    }
    qs('#items').innerHTML = cart.items.map((it) => {
      const p = it.product || { name: `Sản phẩm #${it.product_id}`, unit: '' };
      return `
        <div class="line-item" data-id="${it.product_id}">
          ${thumb(p, 'sm')}
          <div>
            <div class="title">${esc(p.name)}</div>
            <div class="muted small">${esc(p.unit || '')} · ${money(it.unit_price)}</div>
            ${it.issue ? `<div class="issue">${esc(it.issue)}</div>` : ''}
          </div>
          <div class="right">
            <span class="total">${money(it.line_total)}</span>
            <div class="qty"><button data-step="-1" aria-label="Bớt">−</button><input type="number" value="${it.quantity}" min="0" aria-label="Số lượng" data-qty><button data-step="1" aria-label="Thêm">+</button></div>
            <button class="btn ghost sm" data-remove>Xóa</button>
          </div>
        </div>`;
    }).join('') + (cart.degraded ? '<p class="muted small">Một số thông tin chưa cập nhật được do hệ thống bận.</p>' : '');
    qs('#place-order').disabled = cart.has_issues;
    // gợi ý mua kèm dựa trên món có giá trị lớn nhất trong giỏ, bỏ các món đã có trong giỏ
    const anchor = [...cart.items].sort((a, b) => b.line_total - a.line_total)[0];
    const ids = cart.items.map((i) => i.product_id);
    const key = anchor ? `${anchor.product_id}:${[...ids].sort((a, b) => a - b).join(',')}` : null;
    if (anchor && key !== togetherFor) { // đổi khi thành phần giỏ đổi, vì gợi ý tính theo cả giỏ
      togetherFor = key;
      loadTogether(anchor.product_id, qs('#together-panel'), { exclude: ids, add: true, cart: ids });
    }
    await preview();
  }

  async function setQty(pid, qty) {
    try {
      await api(`/cart/items/${pid}`, { method: 'PUT', body: { quantity: qty } });
    } catch (e) { toastError(e); }
    loadCart();
  }

  qs('#items').addEventListener('click', (e) => {
    const row = e.target.closest('.line-item');
    if (!row) return;
    const input = row.querySelector('[data-qty]');
    if (e.target.closest('[data-step]')) setQty(row.dataset.id, Math.max(0, Number(input.value) + Number(e.target.closest('[data-step]').dataset.step)));
    if (e.target.closest('[data-remove]')) api(`/cart/items/${row.dataset.id}`, { method: 'DELETE' }).then(loadCart, toastError);
  });
  qs('#items').addEventListener('change', (e) => {
    if (e.target.matches('[data-qty]')) setQty(e.target.closest('.line-item').dataset.id, Math.max(0, Number(e.target.value || 0)));
  });

  function renderSummary(pv) {
    if (!pv) { qs('#summary').innerHTML = ''; qs('#free-ship').innerHTML = ''; return; }
    const left = pv.free_ship_threshold - (pv.subtotal - pv.discount);
    qs('#free-ship').innerHTML = left > 0
      ? `<div class="free-ship">Mua thêm <b>${money(left)}</b> để được miễn phí giao hàng<div class="bar"><i style="width:${Math.min(100, ((pv.subtotal - pv.discount) / pv.free_ship_threshold) * 100)}%"></i></div></div>`
      : '<div class="free-ship">Đơn hàng được miễn phí giao hàng</div>';
    qs('#summary').innerHTML = `
      <div><span>Tạm tính</span><span>${money(pv.subtotal)}</span></div>
      ${pv.discount ? `<div class="discount"><span>Giảm giá (${esc(pv.coupon_code)})</span><span>−${money(pv.discount)}</span></div>` : ''}
      <div><span>Phí giao hàng</span><span>${pv.shipping_fee ? money(pv.shipping_fee) : 'Miễn phí'}</span></div>
      <div class="grand"><span>Tổng cộng</span>${priceTag(pv.total, 'lg')}</div>`;
  }

  async function preview() {
    if (!cart || !cart.items.length || cart.has_issues) { renderSummary(cart && cart.items.length ? { subtotal: cart.subtotal, discount: 0, shipping_fee: 0, total: cart.subtotal, free_ship_threshold: 300000 } : null); return; }
    try {
      const pv = await api('/orders/preview', { method: 'POST', body: { coupon_code: coupon } });
      const msg = qs('#coupon-msg');
      if (coupon) {
        msg.className = pv.coupon_valid ? 'note-ok' : 'note-err';
        msg.textContent = pv.coupon_message;
        if (!pv.coupon_valid) coupon = '';
      } else { msg.textContent = ''; }
      renderSummary(pv);
    } catch (e) { toastError(e); }
  }

  qs('#together-panel').addEventListener('click', async (e) => {
    const b = e.target.closest('[data-add]');
    if (b && await addToCart(Number(b.dataset.add), 1, b)) { togetherFor = null; loadCart(); }
  });

  qs('#apply-coupon').addEventListener('click', () => { coupon = qs('#coupon').value.trim().toUpperCase(); preview(); });
  qs('#coupon').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); qs('#apply-coupon').click(); } });

  async function loadAddresses() {
    try { addresses = (await api('/users/me/addresses')).items; } catch { addresses = []; }
    const box = qs('#addresses');
    box.innerHTML = addresses.map((a, i) => `
      <label class="option"><input type="radio" name="address" value="${a.id}" ${i === 0 ? 'checked' : ''}>
        <div><b>${esc(a.recipient_name)} · ${esc(a.phone)}</b><span>${esc([a.address_line, a.ward, a.district, a.city].filter(Boolean).join(', '))}</span></div></label>`).join('') +
      `<label class="option"><input type="radio" name="address" value="new" ${addresses.length ? '' : 'checked'}><div><b>Giao đến địa chỉ khác</b><span>Nhập địa chỉ mới</span></div></label>`;
    const toggle = () => qs('#new-address').classList.toggle('hidden', qs('input[name=address]:checked').value !== 'new');
    box.addEventListener('change', toggle);
    toggle();
    if (!addresses.length) {
      const u = Session.user;
      qs('#new-address [name=recipient_name]').value = u.full_name || '';
      qs('#new-address [name=phone]').value = u.phone || '';
    }
  }

  qs('#place-order').addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    const method = qs('input[name=method]:checked').value;
    const body = { payment_method: method, note: qs('#note').value.trim(), coupon_code: coupon || undefined };
    const choice = qs('input[name=address]:checked').value;
    if (choice === 'new') {
      const form = qs('#new-address');
      if (!form.reportValidity()) return;
      const a = formData(form);
      body.shipping_address = a;
      if (a.save) api('/users/me/addresses', { method: 'POST', body: a }).catch(() => {});
    } else {
      body.address_id = Number(choice);
    }
    setBusy(btn, true, 'Đang đặt hàng…');
    try {
      const order = await api('/orders', { method: 'POST', body });
      if (method === 'EWALLET' && order.payment?.payment_url) location.href = order.payment.payment_url;
      else location.href = `/orders.html?id=${order.id}&new=1`;
    } catch (err) {
      setBusy(btn, false);
      toastError(err);
      loadCart();
    }
  });

  loadAddresses();
  loadCart();
}
