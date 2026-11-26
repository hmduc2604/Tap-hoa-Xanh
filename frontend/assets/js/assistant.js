/* Trợ lý mua sắm AI: nút nổi + khung chat. AI chỉ tra cứu và gợi ý; khách tự bấm "Thêm" để bỏ vào giỏ. */
(function () {
  const SUGGESTIONS = ['Nấu canh chua cho 4 người cần mua gì?', 'Gợi ý bữa sáng nhanh gọn', 'Có món nào đang giảm giá không?'];
  const history = []; // { role, content } - chỉ lưu văn bản, gửi tối đa 10 tin gần nhất
  let panel = null;
  let busy = false;

  const fab = document.createElement('button');
  fab.type = 'button';
  fab.className = 'ai-fab';
  fab.setAttribute('aria-haspopup', 'dialog');
  fab.setAttribute('aria-expanded', 'false');
  fab.innerHTML = '<span aria-hidden="true">💬</span> Trợ lý mua sắm';
  document.body.append(fab);

  function build() {
    panel = document.createElement('section');
    panel.className = 'ai-panel hidden';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', 'Trợ lý mua sắm');
    panel.innerHTML = `
      <header><div><b>Trợ lý mua sắm</b> <span class="ai-tag">AI</span><div class="muted small">Hỏi món ăn, nguyên liệu, giá, khuyến mãi</div></div>
        <button type="button" class="icon-btn" data-close aria-label="Đóng trợ lý">×</button></header>
      <div class="ai-log" role="log" aria-live="polite"></div>
      <form class="ai-form" autocomplete="off">
        <label class="sr-only" for="ai-input">Tin nhắn cho trợ lý</label>
        <input id="ai-input" maxlength="500" placeholder="Ví dụ: cần mua gì để làm bún chả?">
        <button class="btn" type="submit">Gửi</button>
      </form>`;
    document.body.append(panel);
    panel.querySelector('[data-close]').addEventListener('click', toggle);
    panel.addEventListener('keydown', (e) => { if (e.key === 'Escape') toggle(); });
    panel.querySelector('form').addEventListener('submit', (e) => { e.preventDefault(); const i = panel.querySelector('#ai-input'); send(i.value); });
    panel.querySelector('.ai-log').addEventListener('click', onLogClick);
    greet();
  }

  const log = () => panel.querySelector('.ai-log');
  const scroll = () => { const l = log(); l.scrollTop = l.scrollHeight; };

  function bubble(role, text) {
    const el = document.createElement('div');
    el.className = 'ai-msg ' + role;
    el.textContent = text; // textContent: nội dung do AI/khách tạo ra không bao giờ được chèn như HTML
    log().append(el);
    scroll();
    return el;
  }

  function cards(products) {
    if (!products || !products.length) return;
    const box = document.createElement('div');
    box.className = 'ai-cards';
    box.innerHTML = products.map((p) => `
      <div class="ai-card">
        ${thumb(p, 'sm')}
        <div class="info"><a href="/?product=${p.id}" class="name">${esc(p.name)}</a>
          <span class="muted small">${esc(p.unit || '')}${p.suggest_qty ? ` · mua ${p.suggest_qty}` : ''}</span><div>${priceBlock(p)}</div>
          ${p.reason ? `<span class="muted small">${esc(p.reason)}</span>` : ''}</div>
        ${p.in_stock === false ? '<span class="soldout small">Hết hàng</span>' : `<button type="button" class="btn sm" data-add="${p.id}" data-qty="${p.suggest_qty || 1}">Thêm</button>`}
      </div>`).join('');
    // công thức món ăn: một nút thêm toàn bộ nguyên liệu chính (không gồm gia vị) với số lượng gợi ý
    const main = products.filter((p) => p.suggest_qty && p.in_stock !== false && !/^Gia vị/.test(p.reason || ''));
    if (main.length >= 2) {
      const all = document.createElement('button');
      all.type = 'button';
      all.className = 'btn ghost sm ai-add-all';
      all.textContent = `Thêm ${main.length} nguyên liệu chính vào giỏ`;
      all.dataset.addAll = JSON.stringify(main.map((p) => [p.id, p.suggest_qty]));
      box.append(all);
    }
    log().append(box);
    scroll();
  }

  function extras(res) {
    if (res.link && /^[a-z0-9_.\-/]+$/i.test(res.link.href || '')) { // chỉ nhận đường dẫn nội bộ do máy chủ trả về
      const a = document.createElement('a');
      a.className = 'btn sm ai-link';
      a.href = res.link.href;
      a.textContent = res.link.text || 'Mở';
      log().append(a);
    }
    if (res.suggestions && res.suggestions.length) {
      const chips = document.createElement('div');
      chips.className = 'ai-chips';
      chips.innerHTML = res.suggestions.slice(0, 4).map((s) => `<button type="button" data-q="${esc(s)}">${esc(s)}</button>`).join('');
      log().append(chips);
    }
    scroll();
  }

  function greet() {
    if (!Session.token) {
      bubble('bot', 'Xin chào! Đăng nhập để chat với trợ lý và thêm món vào giỏ nhanh hơn nhé.');
      const b = document.createElement('div');
      b.innerHTML = '<a class="btn sm" href="#">Đăng nhập</a>';
      b.querySelector('a').addEventListener('click', (e) => { e.preventDefault(); goLogin(); });
      log().append(b);
      panel.querySelector('form').classList.add('hidden');
      return;
    }
    bubble('bot', 'Xin chào! Mình là trợ lý của Tạp Hóa Xanh. Bạn muốn nấu món gì hay cần tìm gì hôm nay?');
    const chips = document.createElement('div');
    chips.className = 'ai-chips';
    chips.innerHTML = SUGGESTIONS.map((s) => `<button type="button" data-q="${esc(s)}">${esc(s)}</button>`).join('');
    log().append(chips);
  }

  async function onLogClick(e) {
    const chip = e.target.closest('[data-q]');
    if (chip) { send(chip.dataset.q); return; }
    const all = e.target.closest('[data-add-all]');
    if (all) { addAll(JSON.parse(all.dataset.addAll), all); return; }
    const add = e.target.closest('[data-add]');
    if (add) addToCart(Number(add.dataset.add), Number(add.dataset.qty) || 1, add);
  }

  async function addAll(pairs, btn) {
    setBusy(btn, true, '…');
    try {
      let cart = null;
      for (const [id, qty] of pairs) cart = await api('/cart/items', { method: 'POST', body: { product_id: id, quantity: qty } });
      qs('#cart-count') && cart && (qs('#cart-count').textContent = cart.item_count);
      toast(`Đã thêm ${pairs.length} nguyên liệu vào giỏ hàng`);
      btn.disabled = true;
    } catch (e) { toastError(e); } finally { setBusy(btn, false); }
  }

  async function send(text) {
    text = (text || '').trim();
    if (!text || busy || !Session.token) return;
    busy = true;
    const input = panel.querySelector('#ai-input');
    input.value = '';
    panel.querySelector('.ai-chips')?.remove();
    bubble('user', text);
    history.push({ role: 'user', content: text });
    const typing = bubble('bot typing', 'Đang tìm giúp bạn…');
    panel.querySelector('form button').disabled = true;
    try {
      const res = await api('/ai/chat', { method: 'POST', body: { messages: history.slice(-10) } });
      typing.remove();
      bubble('bot', res.reply);
      history.push({ role: 'assistant', content: res.reply });
      cards(res.products);
      extras(res);
    } catch (err) {
      typing.remove();
      history.pop(); // bỏ câu hỏi lỗi để lần sau gửi lại không bị lệch lượt
      bubble('bot error', err.message || 'Trợ lý đang bận, bạn thử lại sau nhé.');
    } finally {
      busy = false;
      panel.querySelector('form button').disabled = false;
      input.focus();
    }
  }

  function toggle() {
    if (!panel) build();
    const open = panel.classList.toggle('hidden') === false;
    fab.setAttribute('aria-expanded', String(open));
    fab.classList.toggle('hidden', open && window.innerWidth < 720);
    if (open) panel.querySelector('#ai-input')?.focus();
    else fab.focus();
  }
  fab.addEventListener('click', toggle);
})();
