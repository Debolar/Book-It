// BookIt admin page. The admin key lives only in this variable, never in storage.

const $ = (id) => document.getElementById(id);
let adminKey = '';

async function adminApi(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', 'X-Admin-Key': adminKey },
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    if (typeof body.detail === 'string') message = body.detail;
    else if (Array.isArray(body.detail)) message = 'Please check: ' + body.detail.map((d) => d.loc.at(-1)).join(', ');
    throw new Error(message);
  }
  return body;
}

$('lock-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  adminKey = $('key').value;
  $('lock-error').textContent = '';
  try {
    await adminApi('/api/admin/check');
    $('lock-card').hidden = true;
    $('admin').hidden = false;
    loadRows();
  } catch (err) {
    adminKey = '';
    $('lock-error').textContent = err.message;
  }
});

function syncKind() {
  const isEvent = $('a-kind').value === 'event';
  $('date-field').hidden = !isEvent;
  $('price-label').textContent = isEvent ? 'Price per ticket (₦)' : 'Price per night (₦)';
  $('avail-label').textContent = isEvent ? 'Tickets on sale' : 'Rooms available';
}
$('a-kind').addEventListener('change', syncKind);
syncKind();

$('add-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  $('add-error').textContent = '';
  $('add-ok').textContent = '';
  const kind = $('a-kind').value;
  const body = {
    kind,
    title: $('a-title').value,
    city: $('a-city').value,
    venue: $('a-venue').value,
    date: kind === 'event' ? ($('a-date').value || null) : null,
    price: Number($('a-price').value),
    available: Number($('a-available').value),
    description: $('a-desc').value,
  };
  try {
    const listing = await adminApi('/api/admin/listings', { method: 'POST', body: JSON.stringify(body) });
    $('add-ok').textContent = `Added "${listing.title}" (ID ${listing.id}). It is live on the site now.`;
    $('add-form').reset();
    syncKind();
    loadRows();
  } catch (err) {
    $('add-error').textContent = err.message;
  }
});

async function loadRows() {
  const listings = await (await fetch('/api/listings')).json();
  const tbody = $('rows');
  tbody.replaceChildren();
  for (const l of listings) {
    const tr = document.createElement('tr');

    const id = document.createElement('td');
    id.textContent = l.id;

    const name = document.createElement('td');
    const strong = document.createElement('strong');
    strong.textContent = l.title;
    const small = document.createElement('div');
    small.className = 'muted';
    small.textContent = `${l.kind} · ${l.city}` + (l.date ? ` · ${l.date}` : '');
    name.append(strong, small);

    const price = document.createElement('td');
    const priceIn = document.createElement('input');
    priceIn.type = 'number';
    priceIn.min = '1';
    priceIn.value = l.price;
    priceIn.setAttribute('aria-label', `Price for ${l.title}`);
    price.append(priceIn);

    const left = document.createElement('td');
    const leftIn = document.createElement('input');
    leftIn.type = 'number';
    leftIn.min = '0';
    leftIn.value = l.available;
    leftIn.setAttribute('aria-label', `Places left for ${l.title}`);
    left.append(leftIn);

    const action = document.createElement('td');
    const save = document.createElement('button');
    save.type = 'button';
    save.textContent = 'Save';
    save.addEventListener('click', async () => {
      try {
        await adminApi(`/api/admin/listings/${l.id}`, {
          method: 'PATCH',
          body: JSON.stringify({ price: Number(priceIn.value), available: Number(leftIn.value) }),
        });
        save.textContent = 'Saved ✓';
        setTimeout(() => (save.textContent = 'Save'), 1500);
      } catch (err) {
        alert(err.message);
      }
    });
    action.append(save);

    tr.append(id, name, price, left, action);
    tbody.append(tr);
  }
}
