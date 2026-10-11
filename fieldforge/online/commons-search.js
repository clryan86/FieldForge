"use strict";
window.CommonsPrivateSearch = class {
  constructor({request, notice, failed, privateChat}) {
    Object.assign(this, {request, notice, failed, privateChat});
    this.el = id => document.getElementById(id);
    this.joined = false; this.active = false; this.identity = null;
    this.opened = false; this.epoch = 0; this.controller = null; this.busy = false;
    this.criteria = null; this.olderBefore = null; this.ready = false;
    this.dialog = this.el("privateSearchDialog");
    this.el("openPrivateSearch").addEventListener("click", () => this.open());
    this.el("closePrivateSearch").addEventListener("click", () => this.close());
    this.dialog.addEventListener("cancel", event => { event.preventDefault(); this.close(); });
    this.dialog.addEventListener("close", () => {
      // A close event can arrive after a newer explicit opening of the dialog.
      if (this.opened && !this.dialog.open) this.close();
    });
    this.el("privateSearchForm").addEventListener("submit", event => { event.preventDefault(); this.search(); });
    this.el("privateSearchQuery").addEventListener("input", () => this.changed());
    this.el("privateSearchThread").addEventListener("change", () => this.changed());
    this.el("privateSearchOlder").addEventListener("click", () => {
      if (!this.busy && this.ready && this.olderBefore !== null) this.search(this.olderBefore);
    });
    this.el("privateSearchNewest").addEventListener("click", () => this.search());
    document.addEventListener("visibilitychange", () => { if (document.hidden) this.close(); });
    window.addEventListener("pagehide", () => this.close());
    window.addEventListener("offline", () => this.close());
    // Dismiss before another feature's click handler can start work. A pending
    // history jump must not move focus after the person has left this feature.
    document.addEventListener("click", event => {
      const control = event.target.closest?.("button, a");
      if (!control || control === this.el("openPrivateSearch") || this.dialog.contains(control)) return;
      if (this.opened || this.privateChat.searchJump) this.close();
    }, true);
    this.observer = new MutationObserver(() => {
      const anotherDialog = Array.from(document.querySelectorAll("dialog[open]")).some(dialog => dialog !== this.dialog);
      if (this.opened && (!this.dialog.open || this.dialog.hidden || this.el("privateWorkspace").hidden || anotherDialog)
          || this.privateChat.searchJump && anotherDialog) this.close();
    });
    this.observer.observe(document.body, {subtree: true, attributes: true, attributeFilter: ["open", "hidden"]});
    this.controls();
  }
  node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  }
  available() {
    return this.joined && this.active && this.privateChat.visible && !this.el("privateWorkspace").hidden
      && !document.hidden && navigator.onLine !== false;
  }
  current(epoch, identity) {
    return epoch === this.epoch && identity === this.identity && this.opened && this.dialog.open
      && !this.dialog.hidden && this.available();
  }
  setSession(joined, active, viewer) {
    const identity = joined && viewer ? viewer.id : null;
    if (!joined || !active || identity !== this.identity) this.close();
    this.joined = joined; this.active = active; this.identity = identity; this.controls();
  }
  cancelRequest() {
    this.epoch++; this.controller?.abort(); this.controller = null; this.busy = false;
  }
  clearResults() {
    this.criteria = null; this.olderBefore = null; this.ready = false;
    this.el("privateSearchResults").replaceChildren();
    this.el("privateSearchPage").textContent = "";
    this.el("privateSearchPages").hidden = true;
  }
  close() {
    this.opened = false; this.cancelRequest(); this.clearResults();
    this.privateChat.clearSearchJump();
    if (this.dialog.open) this.dialog.close();
    this.el("privateSearchForm").reset();
    this.el("privateSearchThread").replaceChildren(this.node("option", "All accepted conversations"));
    this.el("privateSearchThread").firstElementChild.value = "";
    this.el("privateSearchQuery").value = "";
    this.el("privateSearchQuery").setCustomValidity("");
    this.el("privateSearchCount").textContent = "0 / 100 characters";
    this.tell(""); this.controls();
  }
  open() {
    if (!this.available() || this.privateChat.busy || this.privateChat.publicBusy) return;
    this.close(); this.privateChat.clearReveal();
    // Invalidate a history reply already in flight without reading any message.
    this.privateChat.pageRevision++;
    const thread = this.privateChat.threads.find(item => item.id === this.privateChat.selected && item.status === "accepted");
    if (thread) {
      const option = this.node("option", "Current conversation: " + thread.title); option.value = thread.id;
      this.el("privateSearchThread").append(option);
    }
    this.opened = true; this.dialog.hidden = false; this.dialog.showModal();
    this.tell("Enter text and choose Search. Results are shown newest first.");
    this.controls(); this.el("privateSearchQuery").focus();
  }
  validation() {
    const input = this.el("privateSearchQuery"), query = input.value.trim();
    const count = Array.from(query).length;
    const invalid = !query ? "Enter text to find in saved messages."
      : count > 100 ? "Use at most 100 characters of search text."
        : /[\u0000-\u001f\u007f-\u009f\u2028-\u202e\u2066-\u2069\ufffe\uffff]/u.test(input.value)
          || Array.from(input.value).some(char => { const code = char.codePointAt(0); return code >= 0xd800 && code <= 0xdfff; })
          ? "Enter a single line of search text without control characters." : "";
    input.setCustomValidity(invalid);
    this.el("privateSearchCount").textContent = `${count} / 100 characters`;
    return {query, invalid};
  }
  changed() {
    this.cancelRequest(); this.clearResults();
    const {invalid} = this.validation();
    this.tell(invalid || "Search changed. Choose Search to see matching saved messages.", Boolean(invalid));
    this.controls();
  }
  tell(text, error = false) {
    this.el("privateSearchStatus").textContent = text;
    this.el("privateSearchStatus").classList.toggle("error", error);
  }
  controls() {
    const available = this.available();
    this.el("openPrivateSearch").disabled = !available || this.privateChat.busy || this.privateChat.publicBusy;
    for (const id of ["privateSearchQuery", "privateSearchThread", "privateSearchSubmit"]) this.el(id).disabled = !available;
    this.el("closePrivateSearch").disabled = false;
    this.el("privateSearchOlder").disabled = !available || this.busy || !this.ready || this.olderBefore === null;
    this.el("privateSearchNewest").disabled = !available || this.busy || !this.ready || this.criteria?.before === null;
    this.el("privateSearchNewest").hidden = !this.criteria || this.criteria.before === null;
    for (const button of this.el("privateSearchResults").querySelectorAll("button")) button.disabled = !available || this.busy;
    this.el("privateSearchResults").setAttribute("aria-busy", String(this.busy));
  }
  async search(before = null) {
    if (!this.opened || !this.dialog.open || !this.available()) return;
    const {query, invalid} = this.validation();
    if (invalid) { this.tell(invalid, true); this.el("privateSearchQuery").reportValidity(); return; }
    const thread = this.el("privateSearchThread").value || null;
    if (before !== null && (!Number.isSafeInteger(before) || before <= 0 || !this.ready || before !== this.olderBefore)) return;
    this.cancelRequest(); this.clearResults();
    const epoch = this.epoch, identity = this.identity, criteria = {query, thread, before};
    const controller = new AbortController(); this.controller = controller;
    this.criteria = criteria; this.busy = true;
    this.tell(before === null ? "Searching saved messages…" : "Searching older saved messages…"); this.controls();
    try {
      const data = await this.request("private/search", criteria, controller.signal);
      if (!this.current(epoch, identity) || controller.signal.aborted) return;
      if (data.query !== query || (data.thread ?? null) !== thread || (data.before ?? null) !== before || !Array.isArray(data.results)) {
        this.tell("The search reply did not match this request. Choose Search to try again.", true); return;
      }
      this.olderBefore = Number.isSafeInteger(data.older_before) && data.older_before > 0 ? data.older_before : null;
      this.ready = true; this.render(data.results);
      const count = data.results.length;
      this.tell(count ? `${count} matching saved ${count === 1 ? "message" : "messages"} on this page. Newest first.`
        : before === null ? "No saved messages match this text in the selected conversations."
          : "No matches remain on this older page. Go back to newest or change your search.");
      this.el("privateSearchPage").textContent = before === null ? "Newest results" : "Older results";
      this.el("privateSearchPages").hidden = !count && before === null;
    } catch (error) {
      if (error.name === "AbortError" || !this.current(epoch, identity)) return;
      if (!error.status || error.status === 401) this.failed(error);
      else this.tell(error.message, true);
    } finally {
      if (this.current(epoch, identity)) { this.busy = false; this.controller = null; this.controls(); }
    }
  }
  render(results) {
    const list = this.el("privateSearchResults"); list.replaceChildren();
    for (const message of results) {
      const article = this.node("article", undefined, "private-search-result");
      article.dataset.id = message.id; article.dataset.thread = message.thread; article.setAttribute("role", "listitem");
      article.append(this.node("h3", message.title));
      const meta = this.node("div", undefined, "message-header");
      meta.append(this.node("strong", message.name + (message.own ? " (you)" : "")));
      const date = new Date(message.created * 1000), time = this.node("time", date.toLocaleString());
      time.dateTime = date.toISOString(); meta.append(time);
      meta.append(this.node("span", message.kind === "group" ? "Private group" : "Direct message", "tag"));
      article.append(meta, this.node("p", message.body, "message-body"));
      const button = this.node("button", "Open conversation", "secondary"); button.type = "button";
      button.setAttribute("aria-label", "Open conversation: " + message.title);
      // Keep only the destination in the action closure, never the saved body.
      const target = {id: message.id, thread: message.thread}, epoch = this.epoch, identity = this.identity;
      button.addEventListener("click", () => {
        if (!this.current(epoch, identity) || this.busy) return;
        if (!Number.isSafeInteger(target.id) || target.id <= 0 || !Number.isSafeInteger(target.id + 1)) {
          this.tell("This message cannot be opened at a valid history position.", true); return;
        }
        this.close(); this.privateChat.openSearchResult(target);
      });
      article.append(button); list.append(article);
    }
  }
};
