import {ADDRESS_MAX_BYTES, addressQuery, addressURL, parseAddressResults} from "./address-core.mjs";

const abortError = () => new DOMException("Address search cancelled.", "AbortError");

async function readJSON(response, signal) {
  if (!/^(?:application\/json|application\/geo\+json)\b/i.test(response.headers.get("content-type") || "")) throw new Error("The address service did not return JSON. Try again later.");
  const declared = response.headers.get("content-length");
  if (declared !== null && /^\d+$/.test(declared) && Number(declared) > ADDRESS_MAX_BYTES) throw new Error("The address response is too large. Try a more specific search.");
  if (!response.body?.getReader) throw new Error("This browser cannot read address responses safely. Use a current browser.");
  const reader = response.body.getReader(), chunks = [];
  let length = 0;
  const cancel = () => { Promise.resolve(reader.cancel()).catch(() => {}); };
  signal.addEventListener("abort", cancel, {once:true});
  try {
    while (true) {
      if (signal.aborted) throw abortError();
      const {done, value} = await reader.read();
      if (done) break;
      if (!(value instanceof Uint8Array) || (length += value.byteLength) > ADDRESS_MAX_BYTES) throw new Error("The address response is too large. Try a more specific search.");
      chunks.push(value);
    }
    if (signal.aborted) throw abortError();
    const bytes = new Uint8Array(length); let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    try { return JSON.parse(new TextDecoder("utf-8", {fatal:true}).decode(bytes)); }
    catch { throw new Error("The address service returned unreadable results. Try again later."); }
  } finally {
    signal.removeEventListener("abort", cancel);
    cancel();
  }
}

export function createAddressService({fetchImpl = globalThis.fetch, now = Date.now, schedule = setTimeout, unschedule = clearTimeout, timeoutMs = 15000} = {}) {
  let connected = false, active = null, nextAllowed = 0, blocked = false;
  const cache = new Map(), starts = [];
  function cancel() { const pending = active; active = null; pending?.controller.abort(); }
  function setConnected(value) { connected = value === true; if (!connected) cancel(); }
  function clear() { cancel(); cache.clear(); }
  async function search(query, scope) {
    const checked = addressQuery(query, scope), key = JSON.stringify([checked.query, checked.scope]);
    if (!connected) throw new Error("Connect before submitting an address search.");
    if (active) throw new Error("An address search is already running. Cancel it or wait for the result.");
    const started = now(), cached = cache.get(key);
    if (cached && started - cached.fetchedAt < 15 * 60 * 1000) return {...structuredClone(cached.value), cached:true};
    if (blocked) throw new Error("The address service refused access. Search is paused for this tab; saved places still work.");
    if (started < nextAllowed) throw new Error(`Please wait ${Math.ceil((nextAllowed - started) / 1000)} seconds before another search.`);
    while (starts.length && starts[0] <= started - 60 * 60 * 1000) starts.shift();
    if (starts.length >= 30) throw new Error("This tab has reached its 30-search hourly preview limit. Save your results and try again later.");
    const request = {controller:new AbortController()}; active = request;
    const signal = request.controller.signal;
    starts.push(started); nextAllowed = started + 2000;
    let timer, onAbort;
    const deadline = new Promise((_, reject) => {
      onAbort = () => reject(abortError()); signal.addEventListener("abort", onAbort, {once:true});
      timer = schedule(() => { reject(new Error("Address search timed out. Check your connection and submit again when ready.")); request.controller.abort(); }, timeoutMs);
    });
    try {
      const value = await Promise.race([deadline, (async () => {
        const response = await fetchImpl(addressURL(checked.query, checked.scope), {method:"GET", mode:"cors", credentials:"omit", cache:"no-store", redirect:"error", referrerPolicy:"no-referrer", headers:{Accept:"application/json"}, signal});
        if (signal.aborted || active !== request) throw abortError();
        if (!response.ok) {
          Promise.resolve(response.body?.cancel()).catch(() => {});
          if (response.status === 429) {
            const raw = response.headers.get("retry-after"), seconds = /^\d+$/.test(raw || "") ? Number(raw) : (Date.parse(raw || "") - now()) / 1000;
            nextAllowed = Math.max(nextAllowed, now() + Math.max(60000, Number.isFinite(seconds) ? Math.min(seconds * 1000, 24 * 60 * 60 * 1000) : 60000));
            throw new Error("The address service is limiting requests. Search is paused for at least a minute; there is no automatic retry.");
          }
          if (response.status === 403) { blocked = true; throw new Error("The address service refused access. Search is paused for this tab; saved places still work."); }
          throw new Error("The address service is unavailable. Try again later; existing saved places are unchanged.");
        }
        const data = await readJSON(response, signal), retrievedAt = new Date(now()).toISOString();
        return {query:checked.query, scope:checked.scope, retrievedAt, results:parseAddressResults(data, retrievedAt)};
      })()]);
      if (signal.aborted || active !== request || !connected) throw abortError();
      cache.delete(key); cache.set(key, {fetchedAt:now(), value:structuredClone(value)});
      while (cache.size > 20) cache.delete(cache.keys().next().value);
      return {...value, cached:false};
    } catch (error) {
      request.controller.abort(); // Includes rejected headers before a reader was opened.
      if (error.name === "TypeError") throw new Error("The address service could not be reached. Check your connection or try later; no alternate provider was contacted.");
      throw error;
    } finally {
      unschedule(timer); signal.removeEventListener("abort", onAbort);
      if (active === request) active = null;
    }
  }
  return {search, cancel, clear, setConnected};
}
