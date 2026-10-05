"use strict";
window.CommonsPrivate = class {
  constructor({request, notice, failed, refresh}) {
    this.request = request; this.notice = notice; this.failed = failed; this.refresh = refresh;
    this.active = false; this.joined = false; this.visible = false; this.busy = false;
    this.selected = null; this.threads = []; this.drafts = new Map(); this.viewEpoch = 0;
    this.before = null; this.olderBefore = null; this.pageRevision = 0;
    this.historyReady = false; this.historyCount = 0; this.pageScroll = "latest";
    this.el = id => document.getElementById(id);
    this.el("privateInboxButton").addEventListener("click", () => this.show(true));
    this.el("publicRoomsButton").addEventListener("click", () => this.show(false));
    this.el("privatePause").addEventListener("click", () => this.el("pauseButton").click());
    this.el("privateLeaveSession").addEventListener("click", () => this.el("leaveButton").click());
    this.el("privateOlder").addEventListener("click", () => this.page(this.olderBefore));
    this.el("privateLatest").addEventListener("click", () => this.page(null));
    this.el("newConversation").addEventListener("click", () => this.el("newConversationDialog").showModal());
    this.el("cancelConversation").addEventListener("click", () => this.el("newConversationDialog").close());
    this.el("newConversationForm").addEventListener("submit", event => {
      event.preventDefault(); this.run(async () => {
        const draft = {title: this.el("conversationTitle").value, kind: this.el("conversationKind").value,
          contacts: this.el("conversationContacts").value.split(/[\s,]+/).filter(Boolean)};
        const signature = JSON.stringify(draft);
        if (this.inviteDraft?.signature !== signature) this.inviteDraft = {signature, id: crypto.randomUUID()};
        const result = await this.request("private/create", {...draft, request_id: this.inviteDraft.id});
        this.el("newConversationDialog").close(); this.el("newConversationForm").reset(); this.inviteDraft = null;
        if (result.closed) this.notice("That invitation was already sent and the conversation has since closed. Start a new conversation if needed.");
        else { this.choose(result.thread); this.notice("Invitation sent. Recipients must accept before reading."); }
        await this.refresh();
      });
    });
    this.el("acceptConversation").addEventListener("click", () => this.run(async () => {
      await this.request("private/accept", {thread: this.selected}); await this.refresh(); this.notice("Invitation accepted.");
    }));
    const leave = () => this.run(async () => {
      const invited = this.threads.find(thread => thread.id === this.selected)?.status === "invited";
      if (!confirm(invited ? "Decline this invitation? You will not join this conversation or receive its messages." : "Leave this conversation? To chat again, start a new conversation. Your sent messages remain for participants who stay.")) return;
      await this.request("private/leave", {thread: this.selected}); this.choose(null); await this.refresh(); this.notice(invited ? "Invitation declined." : "You left the private conversation.");
    });
    this.el("leaveConversation").addEventListener("click", leave);
    this.el("declineConversation").addEventListener("click", leave);
    this.el("declineBlockConversation").addEventListener("click", () => this.run(async () => {
      const thread = this.threads.find(item => item.id === this.selected);
      if (thread?.status !== "invited") return;
      if (!confirm("Decline this invitation and block its sender? They will not be able to send you new private invitations while blocked.")) return;
      const pageRevision = this.pageRevision;
      await this.request("block", {target: thread.owner, blocked: true});
      if (!this.active || !this.joined) return;
      await this.request("private/leave", {thread: thread.id});
      if (this.selected === thread.id && pageRevision === this.pageRevision) this.choose(null);
      await this.refresh(); this.notice("Invitation declined and sender blocked. You can manage blocked participants in Community rooms.");
    }));
    this.el("privateMessage").addEventListener("input", () => this.saveDraft());
    this.el("privateLifetime").addEventListener("change", () => { this.saveDraft(); this.lifetimeHint(); });
    this.el("privateCompose").addEventListener("submit", event => { event.preventDefault(); this.send(); });
    this.el("closeViewOnce").addEventListener("click", () => this.clearReveal());
    this.el("viewOnceDialog").addEventListener("cancel", event => { event.preventDefault(); this.clearReveal(); });
    this.el("viewOnceDialog").addEventListener("close", () => { this.el("viewOnceBody").textContent = ""; clearInterval(this.revealTimer); });
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) { this.resetHistory(); this.controls(); }
      else if (this.active && this.visible && this.selected) this.refresh();
    });
    window.addEventListener("pagehide", () => { this.resetHistory(); this.controls(); });
    this.el("privateExport").addEventListener("click", () => this.run(async () => {
      const data = await this.request("private/export");
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type: "application/json"}));
      const link = document.createElement("a"); link.href = url; link.download = "fieldforge-private-sent-messages.json"; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000); this.notice("Exported your saved sent messages. Open-once messages are excluded.");
    }));
    this.el("cancelPrivateReport").addEventListener("click", () => this.el("privateReportDialog").close());
    this.el("privateReportForm").addEventListener("submit", event => {
      event.preventDefault(); this.run(async () => {
        await this.request("private/report", {...this.reportTarget, reason: this.el("privateReportReason").value});
        this.el("privateReportDialog").close(); this.notice("Private report saved for the local operator. Open-once bodies are not copied into reports.");
      });
    });
  }
  node(tag, text, className) {
    const element = document.createElement(tag); if (text !== undefined) element.textContent = text;
    if (className) element.className = className; return element;
  }
  button(text, callback) {
    const element = this.node("button", text); element.type = "button";
    element.addEventListener("click", () => this.run(callback)); return element;
  }
  setSession(joined, active, publicBusy) {
    if (!active) {
      if (this.active || this.historyReady || this.before !== null) this.resetHistory();
      else this.clearReveal();
    }
    if (!joined && this.joined) {
      this.choose(null); this.threads = []; this.drafts.clear(); this.el("threadList").replaceChildren();
      this.el("contactCode").value = ""; this.show(false);
      for (const id of ["newConversationDialog", "privateReportDialog"]) this.el(id).close();
    }
    this.joined = joined; this.active = active; this.publicBusy = publicBusy; this.controls();
    if (joined && !active && this.selected) this.el("privateEmpty").textContent = "Chat is paused. Resume chat to load this conversation's latest messages.";
  }
  controls() {
    const disabled = !this.active || this.busy || this.publicBusy;
    this.el("privateInboxButton").disabled = !this.joined || this.busy || this.publicBusy;
    this.el("publicRoomsButton").disabled = this.busy || this.publicBusy;
    for (const element of document.querySelectorAll("#privateWorkspace button, #privateCompose textarea, #privateCompose select, #newConversationDialog button, #newConversationDialog input, #newConversationDialog textarea, #newConversationDialog select, #privateReportDialog button, #privateReportDialog select")) element.disabled = disabled;
    this.el("privatePause").disabled = !this.joined || this.busy || this.publicBusy;
    this.el("privatePause").textContent = this.active ? "Pause chat" : "Resume chat";
    this.el("privateLeaveSession").disabled = !this.joined || this.busy || this.publicBusy;
    this.el("cancelConversation").disabled = false; this.el("cancelPrivateReport").disabled = false;
    this.historyControls(disabled);
  }
  show(visible) {
    if (visible && !this.joined) return;
    if (this.visible !== visible) this.resetHistory();
    this.visible = visible; this.clearReveal();
    this.el("publicWorkspace").hidden = visible; this.el("privateWorkspace").hidden = !visible;
    this.el("privateInboxButton").setAttribute("aria-pressed", String(visible));
    this.el("publicRoomsButton").setAttribute("aria-pressed", String(!visible));
    this.controls();
    if (this.active) this.refresh();
  }
  async run(callback) {
    if (!this.active || this.busy) return;
    this.busy = true; this.controls();
    try { await callback(); }
    catch (error) {
      if (error.name === "AbortError") return;
      if (!error.status || error.status === 401) this.failed(error);
      else this.notice(error.message, true);
    } finally { this.busy = false; this.controls(); }
  }
  saveDraft() {
    if (!this.selected) return;
    const body = this.el("privateMessage").value, lifetime = this.el("privateLifetime").value;
    const previous = this.drafts.get(this.selected);
    this.drafts.set(this.selected, {body, lifetime, id: previous?.body === body && previous?.lifetime === lifetime ? previous.id : null});
  }
  choose(thread) {
    this.saveDraft(); this.selected = thread; this.resetHistory();
    const draft = this.drafts.get(thread);
    this.el("privateMessage").value = draft?.body || ""; this.el("privateLifetime").value = draft?.lifetime || "saved";
    this.lifetimeHint();
    this.el("privateCompose").hidden = true; this.el("privateInvitation").hidden = true;
    this.el("privateTitle").textContent = thread ? "Loading conversation…" : "Your conversations, in one place";
    this.el("privateParticipants").textContent = ""; this.el("leaveConversation").hidden = true;
    this.controls();
  }
  resetHistory(before = null) {
    this.pageRevision++; this.before = before; this.olderBefore = null;
    this.historyReady = false; this.historyCount = 0; this.pageScroll = before === null ? "latest" : "older";
    this.clearReveal(); this.el("privateMessages").replaceChildren();
    this.el("privateHistoryStatus").textContent = "";
    this.el("privateHistory").hidden = true; this.el("privateLatest").hidden = before === null;
    this.el("privateEmpty").textContent = this.selected ? "Loading this conversation's messages…" : "Start a conversation or accept an invitation. Saved messages stay here; open-once messages disappear after opening.";
    this.el("privateEmpty").hidden = false;
    this.el("privateScroll").scrollTop = 0;
  }
  historyControls(disabled = !this.active || this.busy || this.publicBusy) {
    const thread = this.threads.find(item => item.id === this.selected);
    const available = this.active && this.visible && !document.hidden && thread?.status === "accepted";
    this.el("privateHistory").hidden = !available;
    this.el("privateOlder").disabled = disabled || !available || !this.historyReady || this.olderBefore === null;
    this.el("privateLatest").hidden = this.before === null;
    this.el("privateLatest").disabled = disabled || !available || this.before === null;
    if (!available) return;
    const unread = thread.unread ? ` ${thread.unread} unread in this conversation.` : "";
    const text = !this.historyReady ? this.before === null ? "Loading latest messages…" : "Loading older messages…"
      : this.before !== null ? this.historyCount ? `Older messages · ${this.historyCount} shown.${unread}` : "No messages remain on this older page. Return to latest."
        : `${this.historyCount} latest visible ${this.historyCount === 1 ? "message" : "messages"}.${unread}`;
    if (this.el("privateHistoryStatus").textContent !== text) this.el("privateHistoryStatus").textContent = text;
  }
  async page(before) {
    if (!this.active || !this.visible || document.hidden || this.busy || this.publicBusy || !this.selected) return;
    if (before !== null && (!Number.isSafeInteger(before) || before <= 0)) return;
    if (before === this.before) return;
    this.resetHistory(before); this.controls(); await this.refresh();
  }
  lifetimeHint() {
    this.el("lifetimeHint").textContent = this.el("privateLifetime").value === "saved"
      ? "Saved messages can be read again. Participants may copy them."
      : "Each recipient can open once, for a 30-second display. Unopened messages expire in 24 hours. Screenshots cannot be prevented. You cannot reread or export the body after sending.";
  }
  async poll(signal) {
    const pageRevision = this.pageRevision;
    const inbox = await this.request("private/inbox", {}, signal);
    if (signal.aborted || !this.active) return;
    this.el("contactCode").value = inbox.contact_code; this.threads = inbox.threads;
    this.renderThreads();
    if (!this.visible || document.hidden || pageRevision !== this.pageRevision) { this.controls(); return; }
    const thread = this.threads.find(item => item.id === this.selected);
    if (!thread) {
      this.choose(null); this.el("privateTitle").textContent = "Your conversations, in one place";
      this.el("privateParticipants").textContent = ""; this.el("leaveConversation").hidden = true;
      this.el("privateEmpty").hidden = false; this.controls(); return;
    }
    this.el("privateTitle").textContent = thread.title; this.el("privateKind").textContent = thread.kind === "group" ? "Invite-only group" : "One-to-one conversation";
    this.el("privateParticipants").textContent = "Participants: " + thread.participants.map(person => `${person.name} (${person.status})`).join(", ");
    this.el("privateInvitation").hidden = thread.status !== "invited";
    this.el("privateCompose").hidden = thread.status !== "accepted";
    this.el("leaveConversation").hidden = thread.status !== "accepted";
    if (thread.status === "accepted") {
      const selected = this.selected, before = this.before;
      const payload = before === null ? {thread: selected} : {thread: selected, before};
      const data = await this.request("private/read", payload, signal);
      if (signal.aborted || pageRevision !== this.pageRevision || selected !== this.selected || before !== this.before || !this.active || !this.visible || document.hidden) return;
      if (data.thread.id !== selected || (data.before ?? null) !== before) return;
      this.olderBefore = Number.isSafeInteger(data.older_before) && data.older_before > 0 ? data.older_before : null;
      this.historyReady = true; this.historyCount = data.messages.length;
      this.threads = this.threads.map(item => item.id === selected ? data.thread : item);
      this.renderMessages(data.messages); this.renderThreads();
    } else { this.resetHistory(); this.el("privateEmpty").hidden = true; }
    this.controls();
  }
  renderThreads() {
    const count = this.threads.reduce((total, thread) => total + (thread.status === "invited" ? 1 : thread.unread), 0);
    this.el("inboxCount").textContent = count ? `(${count})` : "";
    const signature = JSON.stringify(this.threads) + this.selected;
    const list = this.el("threadList");
    if (list.dataset.value !== signature) {
      list.dataset.value = signature; list.replaceChildren();
      for (const thread of this.threads) {
        const button = this.button("", async () => { this.choose(thread.id); await this.refresh(); });
        button.className = "thread-card"; if (thread.id === this.selected) button.setAttribute("aria-current", "page");
        button.append(this.node("strong", thread.title), this.node("span", thread.status === "invited" ? "Invitation · choose whether to join" : `${thread.kind === "group" ? "Private group" : "Direct message"} · ${thread.unread} unread`, "hint"));
        list.append(button);
      }
      if (!this.threads.length) list.append(this.node("p", "No invitations or conversations yet.", "hint"));
    }
  }
  renderMessages(messages) {
    const log = this.el("privateMessages"), scroll = this.el("privateScroll");
    const nearBottom = scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 80;
    const existing = new Map(Array.from(log.children).map(child => [Number(child.dataset.id), child]));
    const ids = new Set(messages.map(message => message.id));
    for (const [id, child] of existing) if (!ids.has(id)) child.remove();
    for (const [index, message] of messages.entries()) {
      const previous = existing.get(message.id), signature = JSON.stringify(message);
      if (previous?.dataset.value === signature) continue;
      const article = this.node("article", undefined, "private-message" + (message.own ? " own" : ""));
      article.dataset.id = message.id; article.dataset.value = signature;
      const header = this.node("div", undefined, "message-header");
      header.append(this.node("strong", message.name + (message.own ? " (you)" : "")), this.node("span", message.lifetime === "saved" ? "Saved" : "Open once", "tag"));
      const date = new Date(message.created * 1000); const time = this.node("time", date.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"})); time.dateTime = date.toISOString(); header.append(time); article.append(header);
      const labels = {opened: "Opened and cleared for this recipient.", expired: "Message expired.", deleted: "Message withdrawn by its sender.", moderated: "Message removed by the owner."};
      const body = message.lifetime === "saved" && message.body ? message.body : labels[message.state] || (message.own ? "Open-once message sent. Its body is not available in sent history." : "A message is waiting to be opened once.");
      article.append(this.node("p", body, "message-body"));
      const actions = this.node("div", undefined, "message-actions");
      if (message.can_open) actions.append(this.button("Open once", () => this.openOnce(message)));
      if (message.own && !["deleted", "expired", "opened", "moderated"].includes(message.state)) actions.append(this.button("Withdraw", async () => {
        if (!confirm("Withdraw this message from the conversation? Existing copies and screenshots cannot be erased.")) return;
        await this.request("private/delete", {thread: this.selected, message: message.id}); await this.refresh();
      }));
      if (!message.own) {
        actions.append(this.button("Block participant", async () => {
          await this.request("block", {target: message.author, blocked: true}); this.clearReveal(); await this.refresh(); this.notice("Participant blocked. New private contact is stopped; pending open-once deliveries between you are cleared.");
        }));
        actions.append(this.button("Report privately", () => {
          this.reportTarget = {thread: this.selected, message: message.id}; this.el("privateReportDialog").showModal();
        }));
      }
      article.append(actions);
      if (previous) previous.replaceWith(article); else log.insertBefore(article, log.children[index] || null);
    }
    this.el("privateEmpty").hidden = messages.length > 0;
    this.el("privateEmpty").textContent = this.before === null ? "No visible messages in this conversation yet." : "No messages remain on this older page. Choose Back to latest to read recent messages.";
    if (this.pageScroll === "older") scroll.scrollTop = 0;
    else if (this.pageScroll === "latest" || this.before === null && nearBottom) scroll.scrollTop = scroll.scrollHeight;
    this.pageScroll = null;
  }
  async send() {
    await this.run(async () => {
      this.saveDraft(); const draft = this.drafts.get(this.selected); if (!draft?.body.trim()) return;
      if (new TextEncoder().encode(draft.body.trim()).length > 2000) { this.notice("Shorten this message to at most 2,000 bytes.", true); return; }
      draft.id ||= crypto.randomUUID(); const selected = this.selected;
      await this.request("private/send", {thread: selected, body: draft.body, lifetime: draft.lifetime, request_id: draft.id});
      this.drafts.delete(selected); this.el("privateMessage").value = "";
      this.notice((draft.lifetime === "saved" ? "Private message saved." : "Open-once message sent. It is excluded from sent history and exports.") + (this.before !== null ? " You are viewing older messages; choose Back to latest to see recent messages." : ""));
      await this.refresh();
    });
  }
  async openOnce(message) {
    if (!confirm("Open this message once? It will close after 30 seconds or when you leave this tab. If the connection loses the reply, it cannot be recovered. Screenshots cannot be prevented.")) return;
    const epoch = this.viewEpoch, thread = this.selected;
    let data;
    try { data = await this.request("private/open", {thread, message: message.id}); }
    catch (error) {
      if (!error.status) {
        this.failed(error); this.notice("Opening could not be confirmed. The message may already be consumed and cannot be replayed. Resume to check its status.", true); return;
      }
      throw error;
    }
    if (!this.active || !this.visible || document.hidden || epoch !== this.viewEpoch || thread !== this.selected) return;
    this.el("viewOnceBody").textContent = data.body;
    const deadline = Date.now() + data.display_seconds * 1000;
    const tick = () => {
      const seconds = Math.ceil((deadline - Date.now()) / 1000);
      if (seconds <= 0) { this.clearReveal(); return; }
      this.el("viewOnceCountdown").textContent = `${seconds} seconds remaining`;
    };
    tick(); this.el("viewOnceDialog").showModal(); this.revealTimer = setInterval(tick, 250);
    await this.refresh();
  }
  clearReveal() {
    this.viewEpoch++; clearInterval(this.revealTimer);
    this.el("viewOnceBody").textContent = ""; this.el("viewOnceDialog").close();
  }
};
