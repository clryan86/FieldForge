"use strict";
(() => {
  const el = id => document.getElementById(id);
  let joined = false, active = false, room = "general", timer = null, reader = null;
  let revision = 0, identityRevision = 0, announcementRevision = 0, sending = false, reportMessage = null;
  let privateChat, accountUI, profileUI, viewer = null;
  const drafts = new Map();
  const notice = (text, error = false) => { el("status").textContent = text; el("status").classList.toggle("error", error); };
  const node = (tag, text, className) => { const result = document.createElement(tag); if (text !== undefined) result.textContent = text; if (className) result.className = className; return result; };
  async function request(action, data = {}, signal) {
    const ownIdentityRevision = identityRevision, expectedViewer = viewer?.id;
    const entering = ["join", "account/login", "account/resume", "account/recover"].includes(action);
    const headers = {"Content-Type": "application/json", "X-FieldForge-Chat": "preview-v1"};
    // Tabs share cookies. Bind established-session requests to the person shown
    // here so an account switch elsewhere cannot send this person's draft as another.
    if (expectedViewer && !entering) headers["X-FieldForge-Participant"] = expectedViewer;
    let response, result;
    try {
      response = await fetch("/api/commons/" + action, {method: "POST", credentials: "same-origin", cache: "no-store", signal,
        headers, body: JSON.stringify(data)});
      result = await response.json();
    } catch (error) {
      if (ownIdentityRevision !== identityRevision) throw new DOMException("This reply belongs to a previous chat session.", "AbortError");
      throw error;
    }
    if (ownIdentityRevision !== identityRevision) throw new DOMException("This reply belongs to a previous chat session.", "AbortError");
    if (!response.ok) {
      const error = new Error(result.error?.message || "Chat request failed."); error.status = response.status;
      if (expectedViewer && !entering && error.status === 401) failed(error);
      throw error;
    }
    if (expectedViewer && !entering && result.viewer && result.viewer.id !== expectedViewer) {
      const error = new Error("The account in this browser changed. Resume the current session when ready.");
      error.status = 401; failed(error); throw error;
    }
    return result;
  }
  function controls() {
    const enabled = joined && active;
    el("connectionLabel").textContent = active ? "Local chat connected" : joined ? "Chat paused" : "Not joined";
    el("message").disabled = !enabled || sending;
    el("sendButton").disabled = !enabled || sending;
    el("sendButton").textContent = sending ? "Sending…" : "Send message ↑";
    el("pauseButton").disabled = !joined;
    el("pauseButton").textContent = active ? "Pause chat" : "Resume chat";
    el("exportButton").disabled = !enabled;
    el("leaveButton").disabled = !joined || sending;
    el("joinPanel").hidden = joined;
    for (const button of el("rooms").querySelectorAll("button")) button.disabled = !enabled || sending;
    for (const button of document.querySelectorAll(".message-actions button, #blockedList button")) button.disabled = !enabled;
    privateChat?.setSession(joined, active, sending, viewer);
    accountUI?.setSession(joined, active, viewer);
    profileUI?.setSession(joined, active, viewer);
  }
  function stop() {
    active = false; revision++; identityRevision++; clearTimeout(timer); reader?.abort(); reader = null; clearAnnouncements(); controls();
  }
  function failed(error) {
    if (error.name === "AbortError" || error.sessionEnded) return;
    stop();
    if (error.status === 401) { clearIdentity(); error.sessionEnded = true; }
    notice((error.status ? error.message : "The local server could not be reached.") + (joined ? " Your draft is retained. Choose Resume chat to reconnect." : " Choose Resume existing session or sign in when ready."), true);
  }
  function clearIdentity() {
    active = false; joined = false; viewer = null; identityRevision++; revision++;
    clearTimeout(timer); reader?.abort(); reader = null;
    clearAnnouncements();
    drafts.clear(); el("message").value = ""; count(); controls();
    el("messages").replaceChildren(); el("emptyState").hidden = false;
    el("sessionName").textContent = "Preview"; el("blockedList").replaceChildren(); delete el("blockedList").dataset.value; el("blockedCount").textContent = "(0)";
    // Clear unfinished private invitations/reports as well as the thread drafts
    // cleared by CommonsPrivate.setSession(). They also belong to this identity.
    el("newConversationForm").reset(); el("privateReportForm").reset(); el("reportForm").reset();
    el("privateTitle").textContent = "Your conversations, in one place";
    el("privateParticipants").textContent = ""; el("privateKind").textContent = ""; el("inboxCount").textContent = "";
    delete el("threadList").dataset.value;
    el("reportDialog").close(); reportMessage = null;
    privateChat.inviteDraft = null; privateChat.reportTarget = null;
    accountUI.clearFields(); accountUI.clearRecovery(); el("accountDialog").close();
  }
  async function connected(data) {
    if (viewer && viewer.id !== data.viewer.id) clearIdentity();
    clearAnnouncements();
    identityRevision++; viewer = data.viewer; joined = true; active = true; controls();
    notice(`Joined as ${viewer.name}. ${viewer.account ? "Your account keeps access to your inbox after sign-out." : "Messages are saved on this local server."}`);
    await refresh();
    if (!joined || viewer?.id !== data.viewer.id) throw new DOMException("The account changed before connection completed.", "AbortError");
  }
  function saveDraft() {
    const body = el("message").value;
    const old = drafts.get(room);
    drafts.set(room, {body, id: old?.body === body ? old.id : null});
  }
  function count() { el("messageCount").textContent = `${Array.from(el("message").value).length} / 1,000 characters`; }
  function action(label, callback) {
    const button = node("button", label); button.type = "button";
    button.addEventListener("click", async () => {
      if (!active) return; button.disabled = true;
      try { await callback(); } catch (error) { failed(error); } finally { controls(); }
    });
    return button;
  }
  function messageNode(message) {
    const article = node("article", undefined, "message" + (message.own ? " own" : "") + (message.deleted ? " deleted" : ""));
    article.dataset.id = message.id; article.dataset.value = JSON.stringify(message);
    article.append(node("div", Array.from(message.name).slice(0, 2).join("").toUpperCase(), "avatar"));
    const content = node("div"); const header = node("div", undefined, "message-header");
    const author = node("strong", message.name + (message.own ? " (you)" : "")); author.title = "Unverified preview name"; header.append(author);
    if (message.skill) { const badge = node("span", message.skill + " · self-reported", "skill-tag"); header.append(badge); }
    const date = new Date(message.created * 1000); const time = node("time", date.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"}));
    time.dateTime = date.toISOString(); time.title = date.toLocaleString(); header.append(time); content.append(header);
    content.append(node("p", message.deleted ? "Message removed." : message.body, "message-body"));
    if (!message.deleted) {
      const actions = node("div", undefined, "message-actions");
      if (message.own) actions.append(action("Delete", async () => {
        if (!confirm("Delete this message from the room? Copies already exported by others cannot be removed.")) return;
        await request("delete", {message: message.id}); await refresh(); notice("Message deleted from the room.");
      }));
      else {
        actions.append(action("Block", async () => { await request("block", {target: message.author, blocked: true}); await refresh(); notice("Participant blocked. Their messages are hidden from your session."); }));
        actions.append(action("Report", () => { reportMessage = message.id; el("reportDialog").showModal(); }));
      }
      content.append(actions);
    }
    article.append(content); return article;
  }
  function clearAnnouncements() {
    // Hiding and showing a tab may happen before an older reply arrives.
    // This generation belongs to notices alone; ordinary chat keeps its lifecycle.
    announcementRevision++;
    el("commonsAnnouncementList").replaceChildren(); el("commonsAnnouncements").hidden = true;
    el("commonsAnnouncementCount").textContent = "";
  }
  function renderAnnouncements(data) {
    if (!joined || !active || document.hidden) return;
    const list = el("commonsAnnouncementList"), announcements = data.announcements;
    const existing = new Map(Array.from(list.children).map(child => [Number(child.dataset.id), child]));
    const ids = new Set(announcements.map(announcement => announcement.id));
    for (const [id, article] of existing) if (!ids.has(id)) article.remove();
    for (const [index, announcement] of announcements.entries()) {
      const previous = existing.get(announcement.id), signature = JSON.stringify(announcement);
      if (previous?.dataset.value === signature) continue;
      const article = node("article", undefined, "announcement-card");
      article.dataset.id = announcement.id; article.dataset.value = signature; article.setAttribute("role", "listitem");
      const heading = node("div", undefined, "announcement-meta");
      heading.append(node("span", "Owner announcement", "tag"), node("strong", "CLRYAN86"));
      const created = new Date(announcement.created * 1000), time = node("time", created.toLocaleString());
      time.dateTime = created.toISOString(); heading.append(time);
      article.append(heading, node("h3", announcement.title), node("p", announcement.body, "announcement-body"));
      if (previous) previous.replaceWith(article); else list.insertBefore(article, list.children[index] || null);
    }
    const count = `${announcements.length} active`;
    if (el("commonsAnnouncementCount").textContent !== count) el("commonsAnnouncementCount").textContent = count;
    el("commonsAnnouncements").hidden = announcements.length === 0;
  }
  function render(data) {
    viewer = data.viewer;
    el("sessionName").textContent = data.viewer.name;
    const currentRoom = data.rooms.find(value => value.id === room);
    el("roomTitle").textContent = currentRoom.label; el("roomBadge").textContent = currentRoom.badge;
    const roomSignature = JSON.stringify(data.rooms) + room;
    if (el("rooms").dataset.value !== roomSignature) {
      el("rooms").dataset.value = roomSignature; el("rooms").replaceChildren();
      for (const entry of data.rooms) {
        const button = action(entry.label, async () => {
          if (room === entry.id) return;
          saveDraft(); room = entry.id; el("message").value = drafts.get(room)?.body || ""; count();
          el("messages").replaceChildren(); await refresh();
        });
        if (entry.id === room) button.setAttribute("aria-current", "page"); el("rooms").append(button);
      }
    }
    const log = el("messages"), scroll = el("messageScroll");
    const nearBottom = scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 80;
    const existing = new Map(Array.from(log.children).map(child => [Number(child.dataset.id), child]));
    const ids = new Set(data.messages.map(message => message.id));
    for (const [id, child] of existing) if (!ids.has(id)) child.remove();
    for (const [index, message] of data.messages.entries()) {
      const child = existing.get(message.id);
      if (!child) log.insertBefore(messageNode(message), log.children[index] || null);
      else if (child.dataset.value !== JSON.stringify(message)) child.replaceWith(messageNode(message));
    }
    el("emptyState").hidden = data.messages.length > 0;
    if (nearBottom) scroll.scrollTop = scroll.scrollHeight;
    const blocked = el("blockedList");
    if (blocked.dataset.value !== JSON.stringify(data.blocked)) {
      blocked.dataset.value = JSON.stringify(data.blocked); blocked.replaceChildren();
      if (!data.blocked.length) blocked.append(node("p", "No participants blocked.", "hint"));
      for (const person of data.blocked) {
        const row = node("div", undefined, "blocked-person"); row.append(node("span", person.name));
        row.append(action("Unblock", async () => { await request("block", {target: person.id, blocked: false}); await refresh(); notice("Participant unblocked."); })); blocked.append(row);
      }
    }
    el("blockedCount").textContent = `(${data.blocked.length})`; controls();
  }
  async function refresh() {
    clearTimeout(timer); reader?.abort(); const ownRevision = ++revision;
    if (!active) return;
    reader = new AbortController();
    const ownAnnouncementRevision = announcementRevision;
    try {
      const [data, announcements] = await Promise.all([
        request("read", {room}, reader.signal),
        !document.hidden ? request("announcements", {}, reader.signal) : Promise.resolve(null)
      ]);
      if (!active || ownRevision !== revision) return;
      render(data);
      if (announcements && ownAnnouncementRevision === announcementRevision && !document.hidden) renderAnnouncements(announcements);
      await privateChat.poll(reader.signal);
      if (active && ownRevision === revision) timer = setTimeout(refresh, 2000);
    } catch (error) { if (ownRevision === revision) failed(error); }
  }
  privateChat = new window.CommonsPrivate({request, notice, failed, refresh});
  privateChat.search = new window.CommonsPrivateSearch({request, notice, failed, privateChat});
  accountUI = new window.CommonsAccounts({request, notice, connected, refresh,
    quiesce: expectedViewerId => {
      if (!active || !joined || viewer?.id !== expectedViewerId) return false;
      clearTimeout(timer); reader?.abort(); reader = null; revision++;
      return true;
    },
    disconnected: expectedViewerId => {
      if (viewer?.id !== expectedViewerId) return false;
      clearIdentity(); return true;
    }
  });
  if (window.CommonsProfile) profileUI = new window.CommonsProfile({request, notice, failed, refresh,
    openConversation: thread => {
      if (!joined || !active || document.hidden) return;
      privateChat.choose(thread); privateChat.show(true);
    }
  });
  el("joinForm").addEventListener("submit", async event => {
    event.preventDefault(); if (!el("consent").checked) return;
    el("joinButton").disabled = true;
    try {
      const data = await request("join", {name: el("displayName").value, skill: el("skill").value, consent: true});
      await connected(data);
    } catch (error) { notice(error.message || "Cannot join local chat.", true); }
    finally { el("joinButton").disabled = false; }
  });
  el("message").addEventListener("input", () => { saveDraft(); count(); });
  el("composeForm").addEventListener("submit", async event => {
    event.preventDefault(); if (!active || sending) return;
    saveDraft(); const draft = drafts.get(room); if (!draft.body.trim()) return;
    if (new TextEncoder().encode(draft.body.trim()).length > 2000) { notice("This message exceeds the 2,000-byte text limit. Shorten it before sending.", true); return; }
    draft.id ||= crypto.randomUUID(); sending = true; controls();
    try {
      await request("send", {room, body: draft.body, request_id: draft.id});
      drafts.delete(room); el("message").value = ""; count(); notice("Message saved."); await refresh();
      el("messageScroll").scrollTop = el("messageScroll").scrollHeight;
    } catch (error) {
      if (error.name === "AbortError") return;
      if (error.status === 429 || error.status === 400) notice(error.message + " Your draft is retained.", true);
      else if (error.status === 401) failed(error);
      else { failed(error); notice("Delivery could not be confirmed. Your draft is retained; resume and send again to check the same message without duplicating it.", true); }
    } finally { sending = false; controls(); if (active) el("message").focus(); }
  });
  el("pauseButton").addEventListener("click", async () => {
    if (active) { stop(); notice("Chat paused. Reading and sending are stopped. Any message already submitted may still finish saving."); }
    else { active = true; controls(); notice("Reconnecting to local chat…"); await refresh(); if (active) notice("Local chat connected."); }
  });
  el("leaveButton").addEventListener("click", async () => {
    stop();
    try {
      await request("leave"); const account = viewer?.account; clearIdentity();
      notice("You left chat. " + (account ? "Sign in to your account to return to your inbox." : "Your saved messages remain, but this guest session cannot be recovered."));
    } catch (error) {
      if (error.status === 401) { clearIdentity(); notice("This session has already ended. Sign in to return to your account."); }
      else notice("Chat is paused, but the server could not confirm logout. Retry Leave chat when it is reachable; the session expires within eight hours.", true);
    }
  });
  el("exportButton").addEventListener("click", async () => {
    if (!active) return;
    try {
      const data = await request("export"); const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type: "application/json"}));
      const link = node("a"); link.href = url; link.download = "fieldforge-commons-my-messages.json"; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      notice("Exported up to 1,000 of your latest retained messages. Other participants' messages are not included.");
    } catch (error) { failed(error); }
  });
  el("cancelReport").addEventListener("click", () => el("reportDialog").close());
  el("reportForm").addEventListener("submit", async event => {
    event.preventDefault(); if (!active) return; const button = event.submitter; button.disabled = true;
    try { await request("report", {message: reportMessage, reason: el("reportReason").value}); el("reportDialog").close(); notice("Report saved for the local operator. No automatic removal or staffed response is provided."); }
    catch (error) { el("reportDialog").close(); failed(error); }
    finally { button.disabled = false; }
  });
  window.addEventListener("offline", () => { if (joined) { stop(); notice("Connection changed. Chat is paused; choose Resume chat when ready."); } });
  document.addEventListener("visibilitychange", () => { if (document.hidden) clearAnnouncements(); });
  window.addEventListener("pagehide", stop);
  controls();
})();
