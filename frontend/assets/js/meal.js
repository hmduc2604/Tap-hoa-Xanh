/* Thực đơn AI: khách mô tả bữa ăn, AI lên món và danh sách đi chợ bằng hàng THẬT của cửa hàng; khách chỉnh số lượng,
   bỏ chọn món không cần, rồi thêm cả danh sách vào giỏ bằng một lần bấm. AI chỉ gợi ý, không tự thêm vào giỏ. */
renderShell('meal');

(function () {
  const EXAMPLES = [
    'Bữa tối cho 4 người, có món canh, khoảng 200k',
    'Nấu bún chả cho 5 người',
    'Bữa sáng nhanh gọn cho 2 người',
    'Tiệc nướng cuối tuần cho 8 người',
    'Bữa trưa ăn chay cho 3 người',
  ];
  const MAX_AVOID = 12;

  const textEl = qs('#meal-text');
  const servingsEl = qs('#meal-servings');
  const budgetEl = qs('#meal-budget');
  const goBtn = qs('#meal-go');
  const out = qs('#meal-result');

  let plan = null;          // phản hồi của /ai/meal-plan
  let rows = {};            // product_id -> { on, qty } trạng thái chỉnh sửa của khách
  let avoid = [];           // món đã gợi ý cho yêu cầu hiện tại, dùng cho "gợi ý thực đơn khác"
  let lastText = '';
  let busy = false;
  let servingsTouched = false;  // khách tự chỉnh số người/ngân sách thì gửi lên; chưa chỉnh thì để máy chủ đọc từ câu mô tả
  let budgetTouched = false;
  let added = false;

  qs('#meal-chips').innerHTML = EXAMPLES.map((e) => `<button type="button" data-q="${esc(e)}">${esc(e)}</button>`).join('');

  /* ------------------------------------------------------------ ô nhập */
  function setServings(n) { servingsEl.value = Math.max(1, Math.min(30, Number(n) || 2)); }
  qs('.meal-opts').addEventListener('click', (e) => {
    const b = e.target.closest('[data-servings]');
    if (!b) return;
    servingsTouched = true;
    setServings(Number(servingsEl.value) + Number(b.dataset.servings));
  });
  servingsEl.addEventListener('input', () => { servingsTouched = true; });
  budgetEl.addEventListener('input', () => { budgetTouched = true; });
  textEl.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); qs('#meal-form').requestSubmit(); } });
  qs('#meal-chips').addEventListener('click', (e) => {
    const b = e.target.closest('[data-q]');
    if (!b) return;
    textEl.value = b.dataset.q;
    servingsTouched = budgetTouched = false;
    generate();
  });
  qs('#meal-form').addEventListener('submit', (e) => { e.preventDefault(); generate(); });

  /* ------------------------------------------------------------ gọi AI */
  async function generate(options = {}) {
    if (busy) return;
    const text = textEl.value.trim();
    if (text.length < 2) { toast('Hãy mô tả bữa ăn bạn muốn nấu', 'error'); textEl.focus(); return; }
    if (!Session.token) {
      // đưa mô tả vào địa chỉ trang để sau khi đăng nhập quay lại đúng chỗ và tự lên thực đơn
      const u = new URL(location.href);
      u.searchParams.set('m', text);
      u.searchParams.set('go', '1');
      history.replaceState(null, '', u);
      toast('Đăng nhập để lên thực đơn');
      setTimeout(goLogin, 700);
      return;
    }
    if (text !== lastText && !options.again) avoid = [];
    lastText = text;
    busy = true;
    goBtn.disabled = true;
    added = false;
    showLoading();
    const body = { request: text };
    if (servingsTouched) body.servings = Number(servingsEl.value);
    if (budgetTouched && budgetEl.value) body.budget = Number(budgetEl.value);
    if (avoid.length) body.avoid = avoid.slice(-MAX_AVOID);
    try {
      plan = await api('/ai/meal-plan', { method: 'POST', body });
      rows = {};
      plan.items.forEach((it) => {
        const avail = it.product.available;
        const qty = typeof avail === 'number' && avail > 0 ? Math.min(it.qty, avail) : it.qty;
        rows[it.product.id] = { on: !it.pantry, qty };
      });
      avoid = [...new Set([...avoid, ...plan.dishes.map((d) => d.name).filter((n) => n !== 'cơm trắng')])];
      setServings(plan.servings);
      if (plan.budget && !budgetTouched) budgetEl.value = plan.budget;
      renderPlan();
      out.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
    } catch (e) {
      plan = null;
      out.innerHTML = `<div class="panel"><div class="empty"><strong>Chưa lên được thực đơn</strong>${esc(e.message)}
        <p style="margin-top:1rem"><button class="btn secondary" data-retry>Thử lại</button></p></div></div>`;
    } finally {
      busy = false;
      goBtn.disabled = false;
    }
  }

  function showLoading() {
    out.innerHTML = `<div class="panel meal-loading" role="status">
      <div class="spinner"></div>
      <p><b>Đang lên thực đơn…</b><br><span class="muted">Chọn món, tính khẩu phần và tra giá hàng thật ở cửa hàng. Thường mất vài giây.</span></p>
    </div>`;
  }

  /* ------------------------------------------------------------ hiển thị kết quả */
  const rowTotal = (it) => rows[it.product.id].qty * (it.product.final_price || 0);
  const lineTotal = (it) => (rows[it.product.id].on ? rowTotal(it) : 0); // chỉ dòng được chọn mới cộng vào tạm tính

  function rowHtml(it) {
    const p = it.product;
    const st = rows[p.id];
    const low = typeof p.available === 'number' && p.available > 0 && p.available < it.qty;
    return `<div class="meal-row ${st.on ? '' : 'off'}" data-id="${p.id}">
      <input type="checkbox" class="meal-on" ${st.on ? 'checked' : ''} aria-label="Chọn ${esc(p.name)}">
      ${thumb(p, 'sm')}
      <div class="info">
        <a class="title" href="/?product=${p.id}">${esc(p.name)}</a>
        <div class="muted small">${esc(p.unit || '')} · <b>${money(p.final_price)}</b>${p.sale_price ? ` <span class="was">${money(p.price)}</span>` : ''}</div>
        <div class="for">Cho: ${it.dishes.map(esc).join(', ')}${low ? ` · <span class="soldout">Kho chỉ còn ${p.available}</span>` : ''}</div>
      </div>
      <div class="ctl">
        <div class="qty"><button type="button" data-step="-1" aria-label="Bớt">−</button><input type="number" value="${st.qty}" min="1" max="99" aria-label="Số lượng ${esc(p.name)}" data-qty><button type="button" data-step="1" aria-label="Thêm">+</button></div>
        <span class="total" data-total>${money(rowTotal(it))}</span>
      </div>
    </div>`;
  }

  function groupHtml(title, hint, list, key) {
    if (!list.length) return '';
    const allOn = list.every((it) => rows[it.product.id].on);
    return `<div class="meal-group" data-group="${key}">
      <div class="meal-group-title"><span>${esc(title)} <span class="muted">(${list.length})</span></span>
        <button type="button" class="btn ghost sm" data-toggle-group="${key}">${allOn ? 'Bỏ chọn tất cả' : 'Chọn tất cả'}</button></div>
      ${hint ? `<p class="muted small meal-hint">${esc(hint)}</p>` : ''}
      ${list.map(rowHtml).join('')}
    </div>`;
  }

  function renderPlan() {
    const main = plan.items.filter((i) => !i.pantry);
    const pantry = plan.items.filter((i) => i.pantry);
    const aiTag = plan.source === 'ai'
      ? '<span class="ai-tag">Gợi ý bởi AI</span>'
      : `<span class="ai-tag">Từ cơ sở món ăn của cửa hàng</span>${plan.fallback ? '<span class="muted small"> · AI đang bận nên dùng thực đơn có sẵn</span>' : ''}`;
    out.innerHTML = `
      <div class="two-col meal-cols">
        <div>
          <section class="panel" aria-labelledby="menu-title">
            <div class="meal-head">
              <div><h2 id="menu-title">${esc(plan.title)}</h2>
                <p class="muted" style="margin:0">${plan.servings} người · ${plan.dishes.length} món ${aiTag}</p></div>
              <button type="button" class="btn secondary sm" data-again>Gợi ý thực đơn khác</button>
            </div>
            <div class="meal-dishes">${plan.dishes.map((d, i) => `
              <article class="meal-dish"><span class="meal-no" aria-hidden="true">${i + 1}</span><div>
                <h3>${esc(d.name)}</h3>${d.how ? `<p>${esc(d.how)}</p>` : ''}</div></article>`).join('')}
            </div>
          </section>
          <section class="panel" aria-labelledby="list-title">
            <h2 id="list-title">Danh sách đi chợ</h2>
            ${groupHtml('Nguyên liệu cần mua', '', main, 'main')}
            ${groupHtml('Nhà thường có sẵn', 'Gia vị, gạo… mặc định không chọn. Bấm chọn nếu nhà bạn chưa có.', pantry, 'pantry')}
            ${plan.missing.length ? `<p class="meal-missing"><b>Cửa hàng chưa bán:</b> ${plan.missing.map(esc).join(', ')}. Bạn mua thêm ở nơi khác nhé.</p>` : ''}
          </section>
        </div>
        <aside class="panel meal-side" aria-labelledby="sum-title">
          <h2 id="sum-title">Tạm tính</h2>
          <div id="meal-summary"></div>
          <button class="btn lg block" id="meal-add" type="button" style="margin-top:1rem"></button>
          <div id="meal-after" aria-live="polite"></div>
          <p class="muted small" style="margin:.8rem 0 0">Giá và tồn kho được kiểm tra lại khi thêm vào giỏ và khi đặt hàng. Số lượng gợi ý theo quy cách đóng gói, bạn có thể chỉnh.</p>
        </aside>
      </div>`;
    updateSummary();
  }

  function updateSummary() {
    if (!plan) return;
    const chosen = plan.items.filter((i) => rows[i.product.id].on);
    const total = chosen.reduce((s, i) => s + lineTotal(i), 0);
    const units = chosen.reduce((s, i) => s + rows[i.product.id].qty, 0);
    let budget = '';
    if (plan.budget) {
      const diff = plan.budget - total;
      const pct = Math.min(100, Math.round((total / plan.budget) * 100));
      budget = `<div class="meal-budget ${diff < 0 ? 'over' : ''}">
        ${diff >= 0 ? `Còn <b>${money(diff)}</b> trong ngân sách ${money(plan.budget)}` : `Vượt ngân sách <b>${money(-diff)}</b> (ngân sách ${money(plan.budget)})`}
        <div class="bar" role="img" aria-label="Đã dùng ${pct}% ngân sách"><i style="width:${pct}%"></i></div></div>`;
    }
    qs('#meal-summary').innerHTML = `
      <div class="sum">
        <div><span>Đã chọn</span><span>${chosen.length} sản phẩm (${units} đơn vị)</span></div>
        <div class="grand"><span>Tạm tính</span>${priceTag(total, 'lg')}</div>
      </div>${budget}`;
    const btn = qs('#meal-add');
    btn.disabled = !chosen.length;
    btn.textContent = added ? 'Thêm lần nữa' : chosen.length ? `Thêm ${chosen.length} sản phẩm vào giỏ` : 'Chọn ít nhất một sản phẩm';
  }

  /* ------------------------------------------------------------ chỉnh sửa */
  function setQty(id, qty, rowEl) {
    qty = Math.max(1, Math.min(99, Math.round(Number(qty) || 1)));
    rows[id].qty = qty;
    const input = rowEl.querySelector('[data-qty]');
    if (document.activeElement !== input) input.value = qty;
    const it = plan.items.find((i) => i.product.id === Number(id));
    rowEl.querySelector('[data-total]').textContent = money(rowTotal(it));
    updateSummary();
  }

  function setOn(id, on, rowEl) {
    rows[id].on = on;
    rowEl.classList.toggle('off', !on);
    const cb = rowEl.querySelector('.meal-on');
    if (cb) cb.checked = on;
  }

  out.addEventListener('click', (e) => {
    if (e.target.closest('[data-retry]')) { generate({ again: true }); return; }
    if (e.target.closest('[data-again]')) { generate({ again: true }); return; }
    if (e.target.closest('#meal-add')) { addToCart(); return; }
    const toggle = e.target.closest('[data-toggle-group]');
    if (toggle && plan) {
      const key = toggle.dataset.toggleGroup;
      const list = plan.items.filter((i) => (key === 'pantry') === i.pantry);
      const turnOn = !list.every((i) => rows[i.product.id].on);
      list.forEach((i) => setOn(i.product.id, turnOn, qs(`.meal-row[data-id="${i.product.id}"]`, out)));
      toggle.textContent = turnOn ? 'Bỏ chọn tất cả' : 'Chọn tất cả';
      updateSummary();
      return;
    }
    const row = e.target.closest('.meal-row');
    const step = e.target.closest('[data-step]');
    if (row && step) setQty(row.dataset.id, rows[row.dataset.id].qty + Number(step.dataset.step), row);
  });
  out.addEventListener('change', (e) => {
    const row = e.target.closest('.meal-row');
    if (!row) return;
    if (e.target.matches('.meal-on')) {
      setOn(row.dataset.id, e.target.checked, row);
      const group = row.closest('.meal-group');
      const btn = group && group.querySelector('[data-toggle-group]');
      if (btn) btn.textContent = qsa('.meal-on', group).every((c) => c.checked) ? 'Bỏ chọn tất cả' : 'Chọn tất cả';
      updateSummary();
    } else if (e.target.matches('[data-qty]')) {
      setQty(row.dataset.id, e.target.value, row);
      e.target.value = rows[row.dataset.id].qty;
    }
  });
  out.addEventListener('input', (e) => {
    if (e.target.matches('[data-qty]') && e.target.value !== '') setQty(e.target.closest('.meal-row').dataset.id, e.target.value, e.target.closest('.meal-row'));
  });

  /* ------------------------------------------------------------ thêm vào giỏ */
  async function addToCart() {
    if (!plan || busy) return;
    const items = plan.items.filter((i) => rows[i.product.id].on).map((i) => ({ product_id: i.product.id, quantity: rows[i.product.id].qty }));
    if (!items.length) return;
    const btn = qs('#meal-add');
    setBusy(btn, true, 'Đang thêm…');
    try {
      const res = await api('/cart/items/bulk', { method: 'POST', body: { items } });
      qs('#cart-count') && (qs('#cart-count').textContent = res.cart.item_count);
      added = true;
      const done = res.added.length + res.adjusted.length;
      const problems = [
        ...res.adjusted.map((a) => `${a.name}: chỉ thêm được ${a.added}/${a.requested} (kho không đủ)`),
        ...res.failed.map((f) => `${f.name || 'Sản phẩm #' + f.product_id}: ${f.reason}`),
      ];
      qs('#meal-after').innerHTML = `
        <div class="meal-done ${done ? '' : 'bad'}">
          <b>${done ? `Đã thêm ${done} sản phẩm vào giỏ hàng` : 'Chưa thêm được sản phẩm nào'}</b>
          ${problems.length ? `<ul>${problems.map((p) => `<li>${esc(p)}</li>`).join('')}</ul>` : ''}
          ${done ? '<a class="btn block" href="/cart.html" style="margin-top:.7rem">Xem giỏ hàng và đặt hàng</a>' : ''}
        </div>`;
      if (done) toast(`Đã thêm ${done} sản phẩm vào giỏ hàng`);
    } catch (e) { toastError(e); } finally { setBusy(btn, false); updateSummary(); }
  }

  /* ------------------------------------------------------------ mở từ trang chủ: ?q=...&go=1 */
  const q = param('m'); // không dùng 'q': trùng tên với ô tìm sản phẩm trên thanh đầu trang
  if (q) {
    textEl.value = q.slice(0, 300);
    if (param('go') === '1') generate();
  }
  if (!Session.token && !q) {
    out.innerHTML = '<div class="panel"><div class="empty"><strong>Đăng nhập để lên thực đơn</strong>Tài khoản giúp lưu giỏ hàng và giới hạn số lượt dùng AI cho công bằng.' +
      '<p style="margin-top:1rem"><a class="btn" href="#" id="meal-login">Đăng nhập</a></p></div></div>';
    qs('#meal-login').addEventListener('click', (e) => { e.preventDefault(); goLogin(); });
  }
})();
