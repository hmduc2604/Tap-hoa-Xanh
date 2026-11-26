/* Tạp Hóa Xanh — tiện ích dùng chung: gọi API qua gateway, phiên đăng nhập, định dạng, toast, hộp thoại */
const API_BASE = '/api';

const Session = {
  get token() { try { return localStorage.getItem('thx_token'); } catch { return null; } },
  get user() { try { return JSON.parse(localStorage.getItem('thx_user') || 'null'); } catch { return null; } },
  set(token, user) {
    try { localStorage.setItem('thx_token', token); localStorage.setItem('thx_user', JSON.stringify(user)); } catch { /* bỏ qua */ }
  },
  updateUser(user) { try { localStorage.setItem('thx_user', JSON.stringify(user)); } catch { /* bỏ qua */ } },
  clear() { try { localStorage.removeItem('thx_token'); localStorage.removeItem('thx_user'); } catch { /* bỏ qua */ } },
  get isStaff() { const u = this.user; return !!u && (u.role === 'admin' || u.role === 'staff'); },
};

class ApiError extends Error {
  constructor(message, status, data) { super(message); this.status = status; this.data = data; }
}

async function api(path, { method = 'GET', body, params } = {}) {
  let url = API_BASE + path;
  if (params) {
    const q = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== '') q.append(k, v); });
    const qs = q.toString();
    if (qs) url += '?' + qs;
  }
  const headers = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (Session.token) headers.Authorization = 'Bearer ' + Session.token;
  let res;
  try {
    res = await fetch(url, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined });
  } catch (e) {
    throw new ApiError('Không kết nối được máy chủ. Kiểm tra mạng rồi thử lại.', 0, null);
  }
  let data = null;
  try { data = await res.json(); } catch { data = null; }
  if (res.status === 401 && Session.token && ['TOKEN_EXPIRED', 'INVALID_TOKEN'].includes(data?.error?.code)) {
    Session.clear();
    toast('Phiên đăng nhập đã hết hạn, vui lòng đăng nhập lại', 'error');
    setTimeout(() => goLogin(), 900);
  }
  if (!res.ok) throw new ApiError(data?.error?.message || `Lỗi ${res.status}`, res.status, data);
  return data;
}

/* ------------------------------------------------------------ định dạng */
const money = (v) => Number(v || 0).toLocaleString('vi-VN') + 'đ';
const priceTag = (v, cls = '') => {
  const s = Number(v || 0).toLocaleString('vi-VN');
  return `<span class="tag ${cls}">${s}<small>đ</small></span>`;
};
function fmtDate(s, withTime = true) {
  if (!s) return '';
  const [d, t = ''] = String(s).split(' ');
  const [y, m, day] = d.split('-');
  return `${day}/${m}/${y}` + (withTime && t ? ' ' + t.slice(0, 5) : '');
}
function timeAgo(s) {
  if (!s) return '';
  const then = new Date(s.replace(' ', 'T') + '+07:00');
  const sec = Math.max(0, (Date.now() - then.getTime()) / 1000);
  if (sec < 60) return 'vừa xong';
  if (sec < 3600) return Math.floor(sec / 60) + ' phút trước';
  if (sec < 86400) return Math.floor(sec / 3600) + ' giờ trước';
  if (sec < 86400 * 7) return Math.floor(sec / 86400) + ' ngày trước';
  return fmtDate(s, false);
}
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
const qs = (sel, root = document) => root.querySelector(sel);
const qsa = (sel, root = document) => [...root.querySelectorAll(sel)];
const param = (name) => new URLSearchParams(location.search).get(name);
const stars = (n) => '★'.repeat(Math.round(n || 0)) + '☆'.repeat(5 - Math.round(n || 0));

/* ô ảnh sản phẩm: dùng ảnh nếu có, không thì biểu tượng danh mục trên nền màu theo danh mục */
function thumb(p, cls = '') {
  const hue = p.category_id ? (p.category_id * 47) % 360 : 140; // nền ô ảnh theo danh mục (CSS đổi độ sáng theo giao diện sáng/tối)
  const icon = p.category_icon || '🛒';
  // ảnh bao bì (Open Food Facts) giữ nguyên tỉ lệ; ảnh minh họa khác phủ kín ô. Ảnh lỗi thì quay về biểu tượng danh mục.
  const pack = /openfoodfacts/.test(p.image_url || '') ? ' class="pack"' : '';
  const inner = p.image_url
    ? `<img src="${esc(p.image_url)}" alt="${esc(p.name || '')}"${pack} loading="lazy" referrerpolicy="no-referrer" onerror="this.replaceWith(Object.assign(document.createElement('span'),{textContent:'${icon}'}))">`
    : `<span aria-hidden="true">${icon}</span>`;
  return `<div class="thumb ${cls}" style="--h:${hue}">${inner}</div>`;
}

/* khung xương cho lưới sản phẩm khi đang tải */
const skeletonCards = (n = 8) => Array.from({ length: n }, () => `
  <div class="card skeleton" aria-hidden="true">
    <div class="thumb skel"></div><div class="skel" style="height:1rem;width:90%"></div><div class="skel" style="height:1rem;width:55%"></div>
    <div class="price-row"><div class="skel" style="height:1.7rem;width:5.2rem"></div><div class="skel" style="height:2.5rem;width:2.5rem;border-radius:50%"></div></div>
  </div>`).join('');

const STATUS = {
  PENDING: 'Chờ xác nhận', CONFIRMED: 'Đã xác nhận', SHIPPING: 'Đang giao', DELIVERED: 'Đã giao',
  COMPLETED: 'Hoàn tất', CANCELLED: 'Đã hủy',
};
const PAY_METHOD = { COD: 'Thanh toán khi nhận hàng', BANK_TRANSFER: 'Chuyển khoản', EWALLET: 'Ví điện tử', CASH: 'Tiền mặt', CARD: 'Thẻ' };
const pill = (code, label) => `<span class="pill ${esc(code)}">${esc(label || STATUS[code] || code)}</span>`;

/* ------------------------------------------------------------ toast & hộp thoại */
function toast(message, type = 'ok') {
  let box = qs('.toasts');
  if (!box) { box = document.createElement('div'); box.className = 'toasts'; box.setAttribute('role', 'status'); document.body.append(box); }
  const el = document.createElement('div');
  el.className = 'toast' + (type === 'error' ? ' error' : '');
  el.textContent = message;
  box.append(el);
  setTimeout(() => el.remove(), type === 'error' ? 5000 : 3000);
}
const toastError = (e) => toast(e?.message || 'Đã có lỗi xảy ra', 'error');

function openDialog({ title, body = '', footer = '', wide = false, onClose } = {}) {
  const overlay = document.createElement('div');
  overlay.className = 'overlay';
  overlay.innerHTML = `
    <div class="dialog ${wide ? 'wide' : ''}" role="dialog" aria-modal="true" aria-label="${esc(title)}">
      <header><h3>${esc(title)}</h3><button class="icon-btn" data-close aria-label="Đóng">×</button></header>
      <div class="body">${body}</div>
      ${footer ? `<footer>${footer}</footer>` : ''}
    </div>`;
  const previous = document.activeElement;
  const close = () => {
    overlay.remove();
    document.removeEventListener('keydown', onKey);
    if (previous && previous.focus) previous.focus();
    onClose && onClose();
  };
  const onKey = (e) => { if (e.key === 'Escape') close(); };
  overlay.addEventListener('click', (e) => { if (e.target === overlay || e.target.closest('[data-close]')) close(); });
  document.addEventListener('keydown', onKey);
  document.body.append(overlay);
  const first = overlay.querySelector('input, select, textarea, .body button, footer button');
  (first || overlay.querySelector('[data-close]')).focus();
  return { el: overlay, close, body: overlay.querySelector('.body') };
}

function confirmDialog(message, { okText = 'Đồng ý', danger = false, input = null } = {}) {
  return new Promise((resolve) => {
    let done = false;
    const field = input ? `<label class="field" style="margin-top:.8rem">${esc(input.label)}<input id="confirm-input" value="${esc(input.value || '')}" placeholder="${esc(input.placeholder || '')}"></label>` : '';
    const d = openDialog({
      title: 'Xác nhận',
      body: `<p>${esc(message)}</p>${field}`,
      footer: `<button class="btn secondary" data-close>Quay lại</button><button class="btn ${danger ? 'danger' : ''}" data-ok>${esc(okText)}</button>`,
      onClose: () => { if (!done) resolve(null); },
    });
    d.el.querySelector('[data-ok]').addEventListener('click', () => {
      done = true;
      const value = input ? d.el.querySelector('#confirm-input').value.trim() : true;
      d.close();
      resolve(value); // null = bấm Quay lại; chuỗi (có thể rỗng) = đồng ý
    });
  });
}

function pager(container, page, totalPages, onPage) {
  if (!container) return;
  if (totalPages <= 1) { container.innerHTML = ''; return; }
  const pages = [];
  for (let i = 1; i <= totalPages; i++) {
    if (i === 1 || i === totalPages || Math.abs(i - page) <= 1) pages.push(i);
    else if (pages[pages.length - 1] !== '…') pages.push('…');
  }
  container.innerHTML = `<button ${page <= 1 ? 'disabled' : ''} data-p="${page - 1}" aria-label="Trang trước">‹</button>` +
    pages.map((p) => p === '…' ? '<span>…</span>' : `<button data-p="${p}" ${p === page ? 'aria-current="page"' : ''}>${p}</button>`).join('') +
    `<button ${page >= totalPages ? 'disabled' : ''} data-p="${page + 1}" aria-label="Trang sau">›</button>`;
  container.onclick = (e) => { const b = e.target.closest('button[data-p]'); if (b && !b.disabled) onPage(Number(b.dataset.p)); };
}

function goLogin() {
  const next = location.pathname + location.search;
  location.href = '/login.html?next=' + encodeURIComponent(next);
}

function requireLogin() {
  if (!Session.token) { goLogin(); return false; }
  return true;
}

async function logout() {
  Session.clear();
  location.href = '/';
}

function setBusy(btn, busy, text) {
  if (!btn) return;
  if (busy) { btn.dataset.text = btn.innerHTML; btn.disabled = true; btn.innerHTML = text || 'Đang xử lý…'; }
  else { btn.disabled = false; if (btn.dataset.text) btn.innerHTML = btn.dataset.text; }
}

function formData(form) {
  const data = {};
  new FormData(form).forEach((v, k) => { data[k] = typeof v === 'string' ? v.trim() : v; });
  qsa('input[type=checkbox]', form).forEach((c) => { if (c.name) data[c.name] = c.checked; });
  return data;
}
