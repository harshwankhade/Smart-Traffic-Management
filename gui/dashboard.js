'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const iso = ms => new Date(ms).toISOString().replace('.000Z', 'Z');
const uid = prefix => `${prefix}-${Date.now().toString(36)}-${crypto.randomUUID().slice(0,6)}`;
let token = '', expected = [], busy = false;

function notice(message, error = false) {
  $('notice').textContent = message;
  $('notice').classList.toggle('error', error);
}
function activity(method, service, path, status, payload, response) {
  const host = $('activity');
  if (!host.querySelector('details')) host.replaceChildren();
  const entry = document.createElement('details');
  const heading = document.createElement('summary');
  heading.innerHTML = `<span class="${status < 400 ? 'match' : 'mismatch'}">${status}</span>${esc(method)} ${esc(service + path)} <small>${esc(new Date().toLocaleTimeString())}</small>`;
  const body = document.createElement('pre');
  body.textContent = JSON.stringify({request: payload ?? undefined, response}, null, 2);
  entry.append(heading, body); host.prepend(entry);
  while (host.children.length > 40) host.lastElementChild.remove();
}
async function api(service, path, method = 'GET', payload, quiet = false) {
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), 26000);
  try {
    const response = await fetch(`/api/${service}${path}`, {
      method, signal: abort.signal,
      headers: {'Content-Type':'application/json', 'X-Demo-Token': token},
      ...(payload === undefined ? {} : {body: JSON.stringify(payload)})
    });
    const text = await response.text();
    let data; try { data = JSON.parse(text); } catch { data = {detail:text}; }
    if (!quiet) activity(method, service, path, response.status, payload, data);
    if (!response.ok) {
      const error = new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail ?? data));
      error.status = response.status; error.data = data; throw error;
    }
    return {data, status: response.status};
  } finally { clearTimeout(timer); }
}
function saveSelection() {
  localStorage.setItem('traffic.selection', JSON.stringify({intersection:$('intersection').value.trim(),sensor:$('sensor').value.trim()}));
}
function ids() {
  const intersection = $('intersection').value.trim(), sensor = $('sensor').value.trim();
  if (!intersection || !sensor) throw new Error('Enter both an intersection ID and sensor ID.');
  return {intersection, sensor};
}
function fresh() {
  const prefix = uid('demo'); $('intersection').value = prefix + '-junction'; $('sensor').value = prefix + '-sensor';
  $('incident-id').value = uid('incident'); expected = [];
  $('sensor-state').textContent = 'New IDs prepared. Click Register & read back to save them.';
  saveSelection();
}
async function register() {
  const {intersection,sensor} = ids();
  for (const [path, payload] of [
    ['/intersections',{intersection_id:intersection,name:$('junction-name').value.trim(),location:$('location').value.trim()}],
    ['/sensors',{sensor_id:sensor,intersection_id:intersection,location:$('location').value.trim(),status:'active'}]
  ]) {
    try { await api('registry',path,'POST',payload); }
    catch (error) { if (error.status !== 409) throw error; }
  }
  await loadSensor();
  notice('Sensor saved and read back from the cloud Registry. You can now send traffic.');
}
async function loadSensor() {
  const sensor = $('sensor').value.trim();
  if (!sensor) throw new Error('Enter a sensor ID first.');
  const {data} = await api('registry','/sensors/' + encodeURIComponent(sensor));
  if ($('intersection').value.trim() && $('intersection').value.trim() !== data.intersection_id) {
    throw new Error(`Sensor belongs to ${data.intersection_id}. Enter that intersection ID and load it again.`);
  }
  $('intersection').value = data.intersection_id;
  $('sensor-state').innerHTML = `<span class="badge">${esc(data.status)}</span> <strong>${esc(data.sensor_id)}</strong><br>Intersection: ${esc(data.intersection_id)} · ${esc(data.location)}`;
  saveSelection(); notice('Sensor retrieved from the cloud Registry.');
}
function eventTime() {
  return Math.max(Date.now(), Number(localStorage.getItem('traffic.lastObserved') || 0) + 1000);
}
async function syncClock() {
  const config = await fetch('/config').then(r=>r.json());
  token = config.csrf;
  localStorage.setItem('traffic.lastObserved', String(Math.max(Number(config.lastObserved || 0),Number(localStorage.getItem('traffic.lastObserved') || 0))));
}
async function sendReading(reading) {
  const result = await api('ingestion','/readings','POST',reading);
  if (result.data.event_id !== reading.event_id || result.data.accepted !== true) throw new Error('Unexpected ingestion acknowledgment.');
  localStorage.setItem('traffic.lastObserved', String(Math.max(Date.parse(reading.observed_at), Number(localStorage.getItem('traffic.lastObserved') || 0))));
  $('reading-state').innerHTML = `<span class="badge">HTTP ${result.status} accepted</span><br><strong>${esc(result.data.event_id)}</strong><br>Observed at ${esc(reading.observed_at)}`;
}
function measurements() {
  const count = Number($('count').value), speed = Number($('speed').value), occupancy = Number($('occupancy').value);
  if (['count','speed','occupancy'].some(id => $(id).value === '') || !Number.isSafeInteger(count) || count < 0 || !Number.isFinite(speed) || speed < 0 || !Number.isFinite(occupancy) || occupancy < 0 || occupancy > 1) throw new Error('Use a nonnegative integer count, nonnegative speed, and occupancy between 0 and 1.');
  return {vehicle_count:count,average_speed:speed,occupancy};
}
async function single() {
  await syncClock();
  const {intersection,sensor} = ids();
  await sendReading({event_id:uid('reading'),sensor_id:sensor,intersection_id:intersection,observed_at:iso(eventTime()),...measurements()});
  notice('Reading accepted. It becomes a summary when its event-time window closes.');
}
async function invalid() {
  const {intersection} = ids();
  try {
    await api('ingestion','/readings','POST',{event_id:uid('invalid'),sensor_id:uid('unknown-sensor'),intersection_id:intersection,observed_at:iso(eventTime()),...measurements()});
  } catch (error) {
    if (error.status >= 400 && error.status < 500) {
      $('reading-state').textContent = `HTTP ${error.status}: ${error.message}`;
      notice('The unknown sensor was rejected. The request evidence below shows the actual validation response.'); return;
    }
    throw error;
  }
  throw new Error('Unexpected result: the unknown sensor was accepted.');
}
function query() {
  const intersection = $('intersection').value.trim();
  if (!intersection) throw new Error('Enter an intersection ID to query.');
  const params = new URLSearchParams({intersection_id:intersection,limit:'100'});
  for (const field of ['from','to']) {
    const value = $(field).value.trim();
    if (value) { if (!value.endsWith('Z') || Number.isNaN(Date.parse(value))) throw new Error('Time filters must be UTC timestamps ending in Z.'); params.set(field,value); }
  }
  return '?' + params;
}
const number = value => value === null || value === undefined ? '—' : Number(value).toLocaleString(undefined,{maximumFractionDigits:3});
const windowLabel = value => { const d = new Date(value); return Number.isNaN(+d) ? value : d.toISOString().slice(11,19); };
function render(summaries, recommendations) {
  summaries.sort((a,b) => Date.parse(a.window_start)-Date.parse(b.window_start));
  $('stat-windows').textContent = summaries.length;
  $('stat-vehicles').textContent = number(summaries.reduce((sum,r) => sum + (r.vehicle_count_sum ?? 0),0));
  $('stat-speed').textContent = number(summaries.at(-1)?.average_speed);
  $('stat-advice').textContent = recommendations.length;
  $('windows').innerHTML = summaries.length ? summaries.map(row => {
    const check = expected.find(e => Date.parse(e.start) === Date.parse(row.window_start));
    const valid = check && row.reading_count === 2 && row.vehicle_count_sum === check.count && row.average_speed === check.speed && Math.abs(row.average_occupancy-check.occupancy)<1e-9;
    return `<tr><td title="${esc(row.window_id)}">${esc(windowLabel(row.window_start))} → ${esc(windowLabel(row.window_end))}</td><td>${number(row.reading_count)}</td><td><b>${number(row.vehicle_count_sum)}</b></td><td>${number(row.average_speed)}</td><td>${number(row.average_occupancy)}</td><td><span class="badge ${esc(row.congestion)}">${esc(row.congestion)}</span></td><td class="${check ? (valid?'match':'mismatch') : ''}">${check ? (valid?'Matches expected':'Does not match') : '—'}</td></tr>`;
  }).join('') : '<tr><td colspan="7" class="empty">No processed windows in this range yet. Send the two-window demo or widen the time range.</td></tr>';
  $('advice').innerHTML = recommendations.length ? recommendations.map(r => `<article class="advice-card"><span class="badge">${r.simulated === true ? 'SIMULATED' : 'ADVISORY'}</span><strong>${Number(r.green_extension_seconds)>0 ? '+'+number(r.green_extension_seconds)+' green seconds' : esc(r.action || 'Maintain timing')}</strong><p>${esc(r.rationale)}</p><small>${esc(windowLabel(r.window_start))} → ${esc(windowLabel(r.window_end))} UTC<br>${esc(r.window_id)}</small></article>`).join('') : '<p class="muted">No recommendations returned for this range.</p>';
}
async function refresh(announce = true) {
  const params = query();
  const [summary, advice] = await Promise.all([api('analytics','/traffic/summaries'+params),api('recommendations','/recommendations'+params)]);
  if (!Array.isArray(summary.data.items) || !Array.isArray(advice.data.items)) throw new Error('Unexpected result format. Inspect the response evidence.');
  render(summary.data.items,advice.data.items);
  if (announce) notice('Loaded actual persisted summaries and recommendations for this intersection and time range.');
  return {summaries:summary.data.items,recommendations:advice.data.items};
}
async function batch() {
  await syncClock();
  const {intersection,sensor} = ids();
  const base = Math.ceil(eventTime()/60000)*60000;
  expected = [{start:iso(base),count:45,speed:14,occupancy:.85},{start:iso(base+60000),count:25,speed:18,occupancy:.65}];
  $('from').value = iso(base); $('to').value = iso(base+120000);
  const values = [[5,15,10,.90],[25,30,18,.80],[65,13,16,.60],[85,12,20,.70],[190,0,50,.10]];
  for (let i=0;i<values.length;i++) {
    const [seconds,count,speed,occupancy] = values[i];
    notice(`Sending ${i===4?'watermark reading':`reading ${i+1} of 4`} through cloud ingestion…`);
    await sendReading({event_id:uid('window-'+(i+1)),sensor_id:sensor,intersection_id:intersection,observed_at:iso(base+seconds*1000),vehicle_count:count,average_speed:speed,occupancy});
  }
  const deadline = Date.now()+180000;
  while (Date.now()<deadline) {
    const result = await refresh(false);
    if (expected.every(e => result.summaries.some(r => Date.parse(r.window_start)===Date.parse(e.start))) && result.recommendations.length>=2) {
      notice('Two cloud-computed windows received. Compare the observed values with the expected checks below.'); return;
    }
    notice('Readings accepted. Waiting for managed Flink and the independent consumers…');
    await sleep(5000);
  }
  notice('The readings were accepted, but both results did not arrive within 3 minutes. Check processor health, event-time ordering, or refresh again.',true);
}
function showIncident(data) {
  $('incident-state').innerHTML = `<span class="badge">${esc(data.status)}</span> <strong>${esc(data.incident_id)}</strong><br>Event ID: ${esc(data.event_id)}<br>${esc(data.type)} · ${esc(data.description)}<br>Reported ${esc(data.reported_at)}`;
}
async function createIncident() {
  const {intersection} = ids();
  const result = await api('incidents','/incidents','POST',{incident_id:$('incident-id').value.trim(),intersection_id:intersection,type:$('incident-type').value,description:$('description').value.trim()});
  showIncident(result.data); notice('Incident saved in the cloud. Alert processing happens asynchronously.');
}
async function readIncident() {
  const id = $('incident-id').value.trim(); if (!id) throw new Error('Enter an incident ID.');
  const result = await api('incidents','/incidents/'+encodeURIComponent(id)); showIncident(result.data); notice('Incident read back through the cloud API.');
}
async function checkConnection() {
  const services = [['registry','Sensor Registry','/healthz'],['ingestion','Traffic Ingestion','/readyz'],['recommendations','Recommendation','/readyz'],['analytics','Analytics','/readyz'],['incidents','Incident Manager','/healthz']];
  const states = await Promise.all(services.map(async ([key,label,path]) => {
    try { await api(key,path,'GET',undefined,true); return {label,ok:true}; }
    catch { return {label,ok:false}; }
  }));
  $('health').innerHTML = states.map(s=>`<span class="chip ${s.ok?'ok':'bad'}"><span class="dot"></span>${esc(s.label)} · ${s.ok?'reachable':'unavailable'}</span>`).join('');
  $('connection').textContent = states.every(s=>s.ok) ? 'Connected · deployed EKS APIs through authenticated tunnels' : 'Some APIs are unavailable · check the dashboard terminal and AWS login';
}
async function run(action) {
  if (busy) return; busy = true;
  document.querySelectorAll('button,input,select').forEach(e => e.disabled = true);
  try { await action(); } catch(error) { notice(error.name==='AbortError'?'Request timed out. Inspect the backend connection and retry.':error.message,true); }
  finally { busy=false; document.querySelectorAll('button,input,select').forEach(e=>e.disabled=false); }
}
for (const [id,action] of Object.entries({register,load:loadSensor,fresh,send:single,invalid,batch,refresh:()=>refresh(), 'incident-create':createIncident,'incident-read':readIncident,check:checkConnection})) {
  $(id).addEventListener('click',()=>run(action));
}
$('clear-log').addEventListener('click',()=>$('activity').replaceChildren());
async function start() {
  try {
    const config = await fetch('/config').then(r=>r.json()); token=config.csrf;
    let selected; try { selected=JSON.parse(localStorage.getItem('traffic.selection')); } catch { selected=null; }
    if (selected?.sensor && selected?.intersection) { $('sensor').value=selected.sensor; $('intersection').value=selected.intersection; $('incident-id').value=uid('incident'); }
    else fresh();
    await checkConnection();
  } catch(error) { notice('Dashboard initialization failed: '+error.message,true); }
}
start();
