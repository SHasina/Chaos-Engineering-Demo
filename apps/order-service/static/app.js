const state = { history: [], polled: 0 };

function setNode(id, status) {
  const el = document.getElementById(id);
  const stateEl = el.querySelector('.state');
  stateEl.textContent = status || 'unreachable';
  el.className = 'node ' + (status === 'confirmed' ? 'ok' : status === 'degraded' ? 'warn' : 'down');
}

function record(data) {
  const healthy = data.status === 'confirmed' || data.status === 'degraded';
  state.history.push(healthy);
  if (state.history.length > 30) state.history.shift();
  state.polled += 1;

  const availability = state.history.length
    ? ((100 * state.history.filter(Boolean).length) / state.history.length).toFixed(1)
    : '—';

  document.getElementById('mode-value').textContent = data.resilient_mode ? 'on' : 'off';
  document.getElementById('latency').textContent = data.latency_ms != null ? `${data.latency_ms} ms` : '—';
  document.getElementById('availability').textContent = `${availability}%`;
  document.getElementById('count').textContent = state.polled;

  setNode('node-order', data.status);
  const paymentStatus = data.payment ? data.payment.status : null;
  setNode('node-payment', paymentStatus);
  const inventoryStatus = data.payment && data.payment.inventory ? data.payment.inventory.status : null;
  setNode('node-inventory', inventoryStatus);

  const log = document.getElementById('log');
  const li = document.createElement('li');
  const time = new Date().toLocaleTimeString();
  li.textContent = `${time} — order ${data.order_id ?? '?'} — ${data.status}${data.error ? ' (' + data.error + ')' : ''}`;
  li.className = data.status || 'failed';
  log.prepend(li);
  while (log.children.length > 10) log.removeChild(log.lastChild);
}

async function poll() {
  try {
    const res = await fetch('/orders');
    const data = await res.json();
    record(data);
  } catch (e) {
    record({ status: 'failed', error: String(e) });
  } finally {
    setTimeout(poll, 1200);
  }
}

poll();
