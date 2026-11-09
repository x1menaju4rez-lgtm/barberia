'use strict';

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
let currentUser = null;
let csrfToken = null;
let lastPhone = '';
let currentView = 'dashboard';
const roleNames = {admin:'Administradora', barber:'Barbero', specialist:'Especialista', inventory:'Inventario', cashier:'Cajero', customer:'Cliente'};
const navByRole = {
  admin: [['dashboard','Resumen'],['appointments','Citas'],['services','Servicios'],['products','Productos'],['inventory','Inventario'],['sales','Ventas y caja'],['employees','Empleados'],['audit','Auditoría']],
  barber: [['appointments','Mi agenda'],['services','Servicios']],
  specialist: [['appointments','Agenda'],['services','Tratamientos'],['inventory','Insumos']],
  inventory: [['products','Productos'],['inventory','Inventario']],
  cashier: [['sales','Ventas y caja'],['products','Productos'],['appointments','Citas']],
  customer: [['services','Servicios'],['products','Productos'],['profile','Mi perfil']]
};

function setMessage(message, isError = false) {
  const node = $('#auth-message');
  if (node) { node.textContent = message || ''; node.style.color = isError ? '#ff9ea6' : '#9fe0bb'; }
}
function toast(message, isError = false) {
  const node = $('#toast');
  node.textContent = message;
  node.classList.toggle('error', isError);
  node.classList.remove('hidden');
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => node.classList.add('hidden'), 4200);
}
async function api(path, options = {}) {
  const headers = {'Content-Type':'application/json', ...(options.headers || {})};
  if (csrfToken) headers['X-CSRF-Token'] = csrfToken;
  const response = await fetch(`/api${path}`, {...options, headers, credentials:'same-origin'});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Error ${response.status}`);
  return data;
}
function money(cents) { return new Intl.NumberFormat('es-MX',{style:'currency',currency:'MXN'}).format((cents || 0)/100); }
function dateTime(value) {
  if (!value) return 'Sin fecha';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('es-MX',{dateStyle:'medium',timeStyle:'short'});
}
function safe(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function showAuthTab(tab) {
  $$('.auth-tabs .tab').forEach(x => x.classList.toggle('active', x.dataset.authTab === tab));
  $('#customer-form').classList.toggle('hidden', tab !== 'customer');
  $('#staff-form').classList.toggle('hidden', tab !== 'staff');
  setMessage('');
}
function setupEvents() {
  $$('.auth-tabs .tab').forEach(button => button.addEventListener('click', () => showAuthTab(button.dataset.authTab)));
  $('#customer-phone').addEventListener('input', e => e.target.value = e.target.value.replace(/\D/g,'').slice(0,10));
  $('#customer-otp').addEventListener('input', e => e.target.value = e.target.value.replace(/\D/g,'').slice(0,6));
  $('#staff-code').addEventListener('input', e => e.target.value = e.target.value.replace(/\D/g,'').slice(0,10));

  $('#customer-form').addEventListener('submit', async e => {
    e.preventDefault();
    const full_name = $('#customer-name').value.trim();
    const phone = $('#customer-phone').value.trim();
    try {
      const result = await api('/auth/request-otp',{method:'POST',body:JSON.stringify({full_name,phone})});
      lastPhone = phone;
      $('#otp-area').classList.remove('hidden');
      setMessage(result.message + ' ' + (result.development_notice || ''), false);
      $('#customer-otp').focus();
    } catch (err) { setMessage(err.message, true); }
  });
  $('#verify-otp').addEventListener('click', async () => {
    try {
      const result = await api('/auth/verify-otp',{method:'POST',body:JSON.stringify({phone:lastPhone,otp:$('#customer-otp').value.trim()})});
      csrfToken = result.csrf_token;
      await enterApp(result.user);
    } catch (err) { setMessage(err.message, true); }
  });
  $('#staff-form').addEventListener('submit', async e => {
    e.preventDefault();
    try {
      const result = await api('/auth/staff',{method:'POST',body:JSON.stringify({code:$('#staff-code').value.trim(),admin_password:$('#admin-password').value})});
      csrfToken = result.csrf_token;
      await enterApp(result.user);
    } catch (err) { setMessage(err.message, true); }
  });
  $('#logout-btn').addEventListener('click', async () => {
    try { await api('/logout',{method:'POST',body:'{}'}); } catch (_) {}
    currentUser = null; csrfToken = null;
    $('#app-screen').classList.add('hidden'); $('#auth-screen').classList.remove('hidden');
    $('#logout-btn').classList.add('hidden'); $('#user-badge').textContent = 'Invitado';
    $('#otp-area').classList.add('hidden'); $('#customer-name').value=''; $('#customer-phone').value=''; $('#customer-otp').value='';
    setMessage('Sesión cerrada.');
  });
  $('#main-nav').addEventListener('click', e => {
    const button = e.target.closest('[data-view]');
    if (button) openView(button.dataset.view);
  });
  document.body.addEventListener('click', async e => {
    const go = e.target.closest('[data-go]');
    if (go) openView(go.dataset.go);
    const refresh = e.target.closest('[data-refresh]');
    if (refresh) loadView(currentView);
    const action = e.target.closest('[data-action]');
    if (action) await handleAction(action);
  });
  $('#service-create').addEventListener('submit', submitService);
  $('#product-create').addEventListener('submit', submitProduct);
  $('#appointment-create').addEventListener('submit', submitAppointment);
  $('#movement-create').addEventListener('submit', submitMovement);
  $('#sale-create').addEventListener('submit', submitSale);
  $('#employee-create').addEventListener('submit', submitEmployee);
}

async function enterApp(user) {
  currentUser = user;
  $('#auth-screen').classList.add('hidden'); $('#app-screen').classList.remove('hidden');
  $('#logout-btn').classList.remove('hidden');
  $('#user-badge').textContent = `${user.name} · ${roleNames[user.role] || user.role}`;
  $('#welcome-title').textContent = `Hola, ${user.name.split(' ')[0]}`;
  $('#role-label').textContent = roleNames[user.role] || 'PANEL';
  $('#welcome-subtitle').textContent = user.role === 'customer' ? 'Tu estilo, tus citas y tus compras.' : 'Tu espacio de trabajo en Legendary Barber.';
  $('#today-label').textContent = new Date().toLocaleDateString('es-MX',{weekday:'long',day:'numeric',month:'long'});
  const allowed = navByRole[user.role] || navByRole.customer;
  $('#main-nav').innerHTML = allowed.map(([id,label],i) => `<button class="nav-item ${i===0?'active':''}" data-view="${id}">${label}</button>`).join('');
  $$('.admin-only').forEach(el => el.classList.toggle('hidden', user.role !== 'admin'));
  $$('.inventory-only').forEach(el => el.classList.toggle('hidden', !['admin','inventory'].includes(user.role)));
  openView(allowed[0][0]);
}

function openView(view) {
  const allowed = (navByRole[currentUser?.role] || []).map(x=>x[0]);
  if (!allowed.includes(view)) return;
  currentView = view;
  $$('.view').forEach(el => el.classList.toggle('hidden', el.id !== `view-${view}`));
  $$('.nav-item').forEach(el => el.classList.toggle('active', el.dataset.view === view));
  loadView(view);
}
async function safeLoad(fn) { try { await fn(); } catch (err) { toast(err.message,true); } }
async function loadView(view) {
  if (view === 'dashboard') return safeLoad(loadDashboard);
  if (view === 'services') return safeLoad(loadServices);
  if (view === 'products') return safeLoad(loadProducts);
  if (view === 'appointments') return safeLoad(loadAppointments);
  if (view === 'inventory') return safeLoad(loadInventory);
  if (view === 'sales') return safeLoad(loadSales);
  if (view === 'employees') return safeLoad(loadEmployees);
  if (view === 'profile') return safeLoad(loadProfile);
  if (view === 'audit') return safeLoad(loadAudit);
}
async function loadDashboard() {
  const d = await api('/dashboard');
  $('#dashboard-cards').innerHTML = [
    ['Ventas de hoy',money(d.today_sales_cents)],['Operaciones',d.today_sales_count],['Stock bajo',d.low_stock],['Citas pendientes',d.pending_appointments],['Movimientos por aprobar',d.pending_movements],['Gastos de hoy',money(d.today_expenses_cents)]
  ].map(([label,value])=>`<article class="metric"><small>${safe(label)}</small><strong>${safe(value)}</strong></article>`).join('');
}
async function loadServices() {
  const d = await api('/services');
  $('#services-list').innerHTML = d.items.length ? d.items.map(s=>`<article class="catalog-card"><span class="category">${safe(s.category)}</span><h3>${safe(s.name)}</h3><p>${safe(s.description || 'Servicio de Legendary Barber.')}</p><div class="price">${s.price_cents ? money(s.price_cents) : 'Precio por configurar'} · ${s.duration_minutes} min</div>${currentUser.role==='admin'?`<p>ID ${s.id} · ${s.published?'Publicado':'No publicado'}</p><button class="small-btn gold" data-action="edit-service" data-id="${s.id}">Editar precio/duración</button><button class="small-btn" data-action="publish-service" data-id="${s.id}" data-published="${s.published?0:1}">${s.published?'Ocultar':'Publicar'}</button>`:''}</article>`).join('') : '<div class="empty">Todavía no hay servicios publicados.</div>';
  if (currentUser.role === 'admin') populateServiceSelect(d.items);
}
function populateServiceSelect(items) { $('#appointment-services').innerHTML = items.filter(s=>s.active).map(s=>`<option value="${s.id}">${safe(s.name)} · ${money(s.price_cents)}</option>`).join(''); }
async function loadProducts() {
  const d = await api('/products');
  $('#products-list').innerHTML = d.items.length ? d.items.map(p=>`<article class="catalog-card"><span class="category">${safe(p.brand || 'LEGENDARY BARBER')}</span><h3>${safe(p.name)}</h3><p>${safe(p.description || 'Producto disponible para solicitar en sucursal.')}</p><div class="price">${p.price_cents ? money(p.price_cents) : 'Precio por configurar'}</div>${p.stock !== undefined ? `<p>Existencias: ${p.stock} · Mínimo: ${p.min_stock}</p>`:''}${currentUser.role==='admin'?`<button class="small-btn gold" data-action="edit-product" data-id="${p.id}">Editar precio</button><button class="small-btn" data-action="publish-product" data-id="${p.id}" data-published="${p.published?0:1}">${p.published?'Ocultar':'Publicar'}</button>`:''}</article>`).join('') : '<div class="empty">No hay productos disponibles.</div>';
  const options = d.items.map(p=>`<option value="${p.id}">${safe(p.name)} · ${p.stock ?? '—'} pzas · ${money(p.price_cents)}</option>`).join('');
  $('#movement-product').innerHTML = options; $('#sale-product').innerHTML = options;
}
async function loadAppointments() {
  const d = await api('/appointments');
  $('#appointments-list').innerHTML = d.items.length ? d.items.map(a=>{
    const services = (a.services||[]).map(s=>s.service_name).join(', ');
    let actions = '';
    if (currentUser.role==='barber' && ['pendiente','reasignada'].includes(a.status)) actions = `<button class="small-btn gold" data-action="decision" data-id="${a.id}" data-decision="aceptada">Aceptar</button><button class="small-btn" data-action="decision" data-id="${a.id}" data-decision="rechazada">Rechazar</button>`;
    if (['barber','admin','specialist'].includes(currentUser.role) && ['aceptada','reasignada'].includes(a.status)) actions += `<button class="small-btn gold" data-action="complete" data-id="${a.id}">Completar</button>`;
    if (currentUser.role==='admin' && ['pendiente','aceptada','reasignada'].includes(a.status)) actions += `<button class="small-btn" data-action="reassign" data-id="${a.id}">Reasignar</button>`;
    if (currentUser.role==='customer' && !['cancelada','completada'].includes(a.status)) actions += `<button class="small-btn" data-action="cancel" data-id="${a.id}">Cancelar</button>`;
    return `<article class="list-card"><div><h3>Cita #${a.id} · ${safe(a.client_name || 'Mi cita')}</h3><p>${dateTime(a.starts_at)} · ${safe(a.barber_name || 'Barbero por asignar')}<br>${safe(services || a.notes || 'Sin servicios detallados')}</p></div><div class="list-actions"><span class="status ${a.status==='aceptada'||a.status==='completada'?'good':a.status==='pendiente'?'warn':''}">${safe(a.status)}</span>${actions}</div></article>`;
  }).join('') : '<div class="empty">No hay citas registradas.</div>';
  if (currentUser.role==='admin') await populateAppointmentForm();
}
async function populateAppointmentForm() {
  const [clients,barbers,services] = await Promise.all([api('/clients'),api('/employees/barbers'),api('/services')]);
  $('#appointment-client').innerHTML = clients.items.map(c=>`<option value="${c.id}">${safe(c.full_name)} · ${safe(c.phone)}</option>`).join('');
  $('#appointment-barber').innerHTML = `<option value="">Por asignar</option>`+barbers.items.map(b=>`<option value="${b.id}">${safe(b.full_name)}</option>`).join('');
  populateServiceSelect(services.items);
}
async function loadInventory() {
  const d = await api('/inventory/movements');
  $('#inventory-list').innerHTML = d.items.length ? d.items.map(m=>`<article class="list-card"><div><h3>${safe(m.product_name)} · ${safe(m.movement_type)} (${m.quantity})</h3><p>${safe(m.reason)} · ${dateTime(m.created_at)} · ${safe(m.requester || 'Sistema')}</p></div><div class="list-actions"><span class="status ${m.status==='aprobado'?'good':m.status==='pendiente'?'warn':''}">${safe(m.status)}</span>${currentUser.role==='admin'&&m.status==='pendiente'?`<button class="small-btn gold" data-action="approve-movement" data-id="${m.id}" data-approve="1">Aprobar</button><button class="small-btn" data-action="approve-movement" data-id="${m.id}" data-approve="0">Rechazar</button>`:''}</div></article>`).join('') : '<div class="empty">Aún no hay movimientos de inventario.</div>';
}
async function loadSales() {
  const d = await api('/sales');
  $('#sales-list').innerHTML = d.items.length ? d.items.map(s=>`<article class="list-card"><div><h3>Ticket #${s.id} · ${money(s.total_cents)}</h3><p>${dateTime(s.created_at)} · ${safe(s.payment_method)} · ${s.items.map(i=>`${safe(i.item_name)} × ${i.quantity}`).join(', ')}</p></div><span class="status good">Pagado</span></article>`).join('') : '<div class="empty">No hay ventas registradas.</div>';
}
async function loadEmployees() {
  const d = await api('/employees');
  $('#employees-list').innerHTML = d.items.map(e=>`<article class="list-card"><div><h3>${safe(e.full_name)}</h3><p>${safe(roleNames[e.role])} · ID ${e.id} · ${e.active?'Activo':'Desactivado'}</p></div><div class="list-actions"><button class="small-btn gold" data-action="reset-code" data-id="${e.id}">Cambiar código</button><button class="small-btn" data-action="toggle-employee" data-id="${e.id}" data-active="${e.active?0:1}">${e.active?'Desactivar':'Activar'}</button></div></article>`).join('');
}
async function loadProfile() {
  const d = await api('/profile');
  $('#profile-card').innerHTML = `<h3>${safe(d.client.full_name)}</h3><p class="muted">Teléfono: ${safe(d.client.phone)}<br>Cliente desde: ${dateTime(d.client.created_at)}</p><h3>Historial de citas</h3>${d.appointments.length?d.appointments.map(a=>`<p>${dateTime(a.starts_at)} · ${safe(a.barber_name||'Por asignar')} · <span class="status">${safe(a.status)}</span></p>`).join(''):'<p class="muted">Todavía no tienes citas registradas.</p>'}`;
}
async function loadAudit() {
  const d = await api('/audit');
  $('#audit-list').innerHTML = d.items.length ? d.items.map(a=>`<article class="list-card"><div><h3>${safe(a.action)} · ${safe(a.entity)} #${a.entity_id||'—'}</h3><p>${safe(a.actor_type)} #${a.actor_id||'—'} · ${dateTime(a.created_at)}<br>${safe(a.details)}</p></div></article>`).join('') : '<div class="empty">Sin movimientos de auditoría.</div>';
}

async function handleAction(button) {
  const id = button.dataset.id;
  try {
    if (button.dataset.action==='decision') await api(`/appointments/${id}/decision`,{method:'PATCH',body:JSON.stringify({decision:button.dataset.decision})});
    if (button.dataset.action==='complete') await api(`/appointments/${id}/complete`,{method:'PATCH',body:'{}'});
    if (button.dataset.action==='cancel') await api(`/appointments/${id}/cancel`,{method:'PATCH',body:JSON.stringify({reason:'Cancelación desde el portal del cliente'})});
    if (button.dataset.action==='approve-movement') await api(`/inventory/movements/${id}/approve`,{method:'PATCH',body:JSON.stringify({approve:button.dataset.approve==='1'})});
    if (button.dataset.action==='toggle-employee') await api(`/employees/${id}`,{method:'PATCH',body:JSON.stringify({active:button.dataset.active==='1'})});
    if (button.dataset.action==='reset-code') {
      const code=prompt('Escribe el nuevo código de 10 dígitos. No lo compartas.');
      if(code===null) return;
      await api(`/employees/${id}`,{method:'PATCH',body:JSON.stringify({code})});
    }
    if (button.dataset.action==='reassign') {
      const barbers = await api('/employees/barbers');
      const choice = prompt('Escribe el ID del nuevo barbero:\n'+barbers.items.map(x=>`${x.id}: ${x.full_name}`).join('\n'));
      if (choice) await api(`/appointments/${id}/reassign`,{method:'PATCH',body:JSON.stringify({barber_id:Number(choice),reason:'Reasignación administrativa'})});
    }
    if (button.dataset.action==='edit-service') {
      const item=(await api('/services')).items.find(x=>x.id===Number(id));
      const price=prompt(`Precio MXN para ${item.name}:`,(item.price_cents/100).toFixed(2));
      if(price===null) return;
      const duration=prompt('Duración en minutos:',String(item.duration_minutes));
      if(duration===null) return;
      await api(`/services/${id}`,{method:'PUT',body:JSON.stringify({...item,price:Number(price),duration_minutes:Number(duration)})});
    }
    if (button.dataset.action==='edit-product') {
      const item=(await api('/products')).items.find(x=>x.id===Number(id));
      const price=prompt(`Precio MXN para ${item.name}:`,(item.price_cents/100).toFixed(2));
      if(price===null) return;
      const cost=prompt('Costo MXN (solo interno):',((item.cost_cents||0)/100).toFixed(2));
      if(cost===null) return;
      await api(`/products/${id}`,{method:'PUT',body:JSON.stringify({...item,price:Number(price),cost:Number(cost)})});
    }
    if (button.dataset.action==='publish-service') {
      const item = (await api('/services')).items.find(x=>x.id===Number(id));
      await api(`/services/${id}`,{method:'PUT',body:JSON.stringify({...item,price:item.price_cents/100,published:button.dataset.published==='1'})});
    }
    if (button.dataset.action==='publish-product') {
      const item = (await api('/products')).items.find(x=>x.id===Number(id));
      await api(`/products/${id}`,{method:'PUT',body:JSON.stringify({...item,price:item.price_cents/100,cost:(item.cost_cents||0)/100,published:button.dataset.published==='1'})});
    }
    toast('Operación realizada correctamente.');
    loadView(currentView);
  } catch (err) { toast(err.message,true); }
}
async function submitService(e) {
  e.preventDefault(); const f = Object.fromEntries(new FormData(e.currentTarget)); f.published = new FormData(e.currentTarget).has('published');
  try { await api('/services',{method:'POST',body:JSON.stringify(f)}); e.currentTarget.reset(); toast('Servicio creado.'); await loadServices(); }
  catch(err){toast(err.message,true);}
}
async function submitProduct(e) {
  e.preventDefault(); const fd=new FormData(e.currentTarget), f=Object.fromEntries(fd); f.published=fd.has('published');
  try { await api('/products',{method:'POST',body:JSON.stringify(f)}); e.currentTarget.reset(); toast('Producto creado.'); await loadProducts(); }
  catch(err){toast(err.message,true);}
}
async function submitAppointment(e) {
  e.preventDefault(); const fd=new FormData(e.currentTarget); const services=$('#appointment-services'); const service_ids=[...services.selectedOptions].map(o=>Number(o.value));
  const local = new Date(fd.get('starts_at'));
  try {
    if(service_ids.length>3||service_ids.length<1) throw new Error('Selecciona entre uno y tres servicios.');
    await api('/appointments',{method:'POST',body:JSON.stringify({client_id:Number(fd.get('client_id')),barber_id:fd.get('barber_id')?Number(fd.get('barber_id')):null,starts_at:local.toISOString(),service_ids,notes:fd.get('notes')})});
    e.currentTarget.reset(); toast('Solicitud de cita registrada.'); await loadAppointments();
  } catch(err){toast(err.message,true);}
}
async function submitMovement(e) {
  e.preventDefault(); const f=Object.fromEntries(new FormData(e.currentTarget));
  try { await api('/inventory/movements',{method:'POST',body:JSON.stringify(f)}); e.currentTarget.reset(); toast('Movimiento enviado; puede requerir aprobación.'); await loadInventory(); }
  catch(err){toast(err.message,true);}
}
async function submitSale(e) {
  e.preventDefault(); const f=Object.fromEntries(new FormData(e.currentTarget));
  try { const result=await api('/sales',{method:'POST',body:JSON.stringify({payment_method:f.payment_method,items:[{item_type:'producto',item_id:Number(f.item_id),quantity:Number(f.quantity)}]})});
    toast(`Venta #${result.id} registrada. Total: ${money(result.total_cents)}`); e.currentTarget.reset(); await Promise.all([loadSales(),loadProducts()]);
  } catch(err){toast(err.message,true);}
}
async function submitEmployee(e) {
  e.preventDefault(); const f=Object.fromEntries(new FormData(e.currentTarget));
  try { await api('/employees',{method:'POST',body:JSON.stringify(f)}); e.currentTarget.reset(); toast('Empleado creado. Guarda el código de forma segura.'); await loadEmployees(); }
  catch(err){toast(err.message,true);}
}

async function bootstrap() {
  setupEvents();
  $('#connection').innerHTML = '<i></i> Conectado';
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('/service-worker.js').catch(()=>{});
  try {
    const d=await api('/me');
    if(d.authenticated){ currentUser=d.user; csrfToken=d.user.csrf_token; await enterApp(d.user); }
  } catch (err) { console.error(err); }
}
document.addEventListener('DOMContentLoaded',bootstrap);
