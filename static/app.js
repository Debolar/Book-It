// BookIt frontend: lists hotels and events, and books them through the API.

const $ = (id) => document.getElementById(id);
const els = {
  listings: $('listings'), city: $('city'), status: $('status'), statusText: $('status-text'),
  dialog: $('book-dialog'), form: $('book-form'), title: $('book-title'), sub: $('book-sub'),
  name: $('f-name'), email: $('f-email'), qty: $('f-qty'), qtyLabel: $('qty-label'),
  checkin: $('f-checkin'), nights: $('f-nights'), total: $('f-total'), error: $('f-error'),
  submit: $('f-submit'), confirm: $('confirm'), confirmRef: $('confirm-ref'),
  confirmDetail: $('confirm-detail'), mineForm: $('mine-form'), mineEmail: $('mine-email'),
  bookings: $('bookings'), bookingsEmpty: $('bookings-empty'), version: $('version'), env: $('env'),
};

let kind = '';
let current = null; // the listing being booked

const naira = (n) => '₦' + n.toLocaleString('en-NG');

function setStatus(ok, text) {
  els.status.classList.toggle('ok', ok);
  els.status.classList.toggle('down', !ok);
  els.statusText.textContent = text;
}

async function api(path, options = {}) {
  const res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...options });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    if (typeof body.detail === 'string') message = body.detail;
    else if (Array.isArray(body.detail)) message = 'Please check: ' + body.detail.map((d) => d.loc.at(-1)).join(', ');
    throw new Error(message);
  }
  return body;
}

function formatDate(iso) {
  return new Date(iso + 'T00:00:00').toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });
}

function renderListings(items) {
  els.listings.replaceChildren();
  for (const item of items) {
    const li = document.createElement('li');
    li.className = 'listing';

    const tag = document.createElement('span');
    tag.className = 'kind ' + item.kind;
    tag.textContent = item.kind === 'hotel' ? 'Hotel' : 'Event';

    const title = document.createElement('h3');
    title.textContent = item.title;

    const where = document.createElement('p');
    where.className = 'muted';
    where.textContent = `${item.venue}, ${item.city}` + (item.date ? ` · ${formatDate(item.date)}` : '');

    const desc = document.createElement('p');
    desc.className = 'desc';
    desc.textContent = item.description;

    const foot = document.createElement('div');
    foot.className = 'listing-foot';
    const price = document.createElement('p');
    price.className = 'price';
    price.textContent = naira(item.price) + (item.kind === 'hotel' ? ' / night' : ' / ticket');
    const left = document.createElement('p');
    left.className = 'left' + (item.available === 0 ? ' sold' : item.available <= 5 ? ' low' : '');
    left.textContent = item.available === 0 ? 'Sold out'
      : `${item.available} ${item.kind === 'hotel' ? 'rooms' : 'tickets'} left`;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = 'Book';
    btn.disabled = item.available === 0;
    btn.addEventListener('click', () => openBooking(item));
    foot.append(price, left, btn);

    li.append(tag, title, where, desc, foot);
    els.listings.append(li);
  }
}

async function loadListings() {
  const params = new URLSearchParams();
  if (kind) params.set('kind', kind);
  if (els.city.value) params.set('city', els.city.value);
  try {
    renderListings(await api('/api/listings?' + params));
    setStatus(true, 'Connected');
  } catch (err) {
    setStatus(false, 'API unreachable');
  }
}

function updateTotal() {
  if (!current) return;
  const qty = Math.max(1, Number(els.qty.value) || 1);
  const nights = current.kind === 'hotel' ? Math.max(1, Number(els.nights.value) || 1) : 1;
  els.total.textContent = naira(current.price * qty * nights);
}

function openBooking(item) {
  current = item;
  els.form.hidden = false;
  els.confirm.hidden = true;
  els.error.textContent = '';
  els.title.textContent = item.title;
  els.sub.textContent = `${item.venue}, ${item.city}` + (item.date ? ` · ${formatDate(item.date)}` : '');
  const isHotel = item.kind === 'hotel';
  els.dialog.classList.toggle('is-hotel', isHotel);
  els.qtyLabel.textContent = isHotel ? 'Rooms' : 'Tickets';
  els.qty.max = Math.min(10, item.available);
  els.qty.value = 1;
  els.nights.value = 1;
  if (isHotel) {
    const tomorrow = new Date(Date.now() + 864e5).toISOString().slice(0, 10);
    els.checkin.min = tomorrow;
    els.checkin.value = els.checkin.value || tomorrow;
  }
  updateTotal();
  els.dialog.showModal();
  els.name.focus();
}

els.form.addEventListener('submit', async (event) => {
  event.preventDefault();
  els.error.textContent = '';
  const body = {
    listing_id: current.id,
    name: els.name.value,
    email: els.email.value,
    quantity: Number(els.qty.value),
  };
  if (current.kind === 'hotel') {
    body.check_in = els.checkin.value;
    body.nights = Number(els.nights.value);
  }
  els.submit.disabled = true;
  try {
    const b = await api('/api/bookings', { method: 'POST', body: JSON.stringify(body) });
    els.form.hidden = true;
    els.confirm.hidden = false;
    els.confirmRef.textContent = b.ref;
    els.confirmDetail.textContent = `${b.quantity} × ${b.listing_title} · ${naira(b.total)}`
      + (b.check_in ? ` · from ${formatDate(b.check_in)} for ${b.nights} night(s)` : '');
    els.mineEmail.value = b.email;
    loadListings();
  } catch (err) {
    els.error.textContent = err.message;
  } finally {
    els.submit.disabled = false;
  }
});

for (const input of [els.qty, els.nights]) input.addEventListener('input', updateTotal);
$('f-cancel').addEventListener('click', () => els.dialog.close());
$('confirm-done').addEventListener('click', () => { els.dialog.close(); loadMine(); });

async function loadMine() {
  const email = els.mineEmail.value.trim();
  if (!email) return;
  try {
    const list = await api('/api/bookings?email=' + encodeURIComponent(email));
    els.bookings.replaceChildren();
    for (const b of list) {
      const li = document.createElement('li');
      li.className = 'booking' + (b.status === 'cancelled' ? ' is-cancelled' : '');
      const info = document.createElement('div');
      const t = document.createElement('p');
      t.className = 'b-title';
      t.textContent = `${b.ref} · ${b.listing_title}`;
      const d = document.createElement('p');
      d.className = 'muted';
      d.textContent = `${b.quantity} × · ${naira(b.total)} · ${b.status}`
        + (b.check_in ? ` · from ${formatDate(b.check_in)}, ${b.nights} night(s)` : '');
      info.append(t, d);
      li.append(info);
      if (b.status === 'confirmed') {
        const cancel = document.createElement('button');
        cancel.type = 'button';
        cancel.className = 'ghost';
        cancel.textContent = 'Cancel';
        cancel.addEventListener('click', async () => {
          if (!confirm(`Cancel booking ${b.ref}?`)) return;
          try {
            await api(`/api/bookings/${b.ref}/cancel`, { method: 'POST' });
          } catch (err) {
            alert(err.message);
          }
          loadMine();
          loadListings();
        });
        li.append(cancel);
      }
      els.bookings.append(li);
    }
    els.bookingsEmpty.hidden = list.length > 0;
  } catch (err) {
    els.bookingsEmpty.hidden = false;
    els.bookingsEmpty.textContent = err.message;
  }
}

els.mineForm.addEventListener('submit', (e) => { e.preventDefault(); loadMine(); });

for (const tab of document.querySelectorAll('.tab')) {
  tab.addEventListener('click', () => {
    kind = tab.dataset.kind;
    document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('is-active', t === tab));
    loadListings();
  });
}
els.city.addEventListener('change', loadListings);

(async function start() {
  try {
    const info = await api('/api/info');
    els.version.textContent = `version ${info.version}`;
    els.env.textContent = `${info.environment} · ${info.store}`;
  } catch {
    setStatus(false, 'API unreachable');
  }
  loadListings();
})();
