"use strict";
(() => {
  const el = id => document.getElementById(id);
  const node = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
  let active = false, busy = false, revision = 0, operationRevision = 0, expiryTimer, offset = 0, total = 0, query = "";
  let announcementDraft = null;
  const notice = (message, error = false) => { el("ownerStatus").textContent = message; el("ownerStatus").classList.toggle("error", error); };
  const date = value => new Date(value * 1000).toLocaleString();
  function secretsClear() {
    for (const id of ["ownerPassword", "ownerCode", "ownerCurrentPassword", "ownerSecurityCode", "ownerNewPassword", "ownerConfirmPassword"]) el(id).value = "";
  }
  function recoveryClear() { el("ownerRecoveryValue").value = ""; el("ownerRecoverySaved").checked = false; el("ownerRecoveryDone").disabled = true; el("ownerRecoveryDialog").close(); }
  function clear() {
    active = false; revision++; clearTimeout(expiryTimer); secretsClear(); recoveryClear();
    for (const id of ["ownerReports", "ownerMembers", "ownerAudit", "ownerAnnouncementList"]) el(id).replaceChildren();
    clearAnnouncementDraft(); el("ownerAnnouncementCount").textContent = "";
    for (const id of ["ownerAccountCount", "ownerGuestCount", "ownerClosedCount", "ownerSuspendedCount", "ownerReportCount", "ownerMemberCount", "ownerExpiry"]) el(id).textContent = "";
    query = ""; offset = 0; total = 0; el("ownerSearch").value = "";
    el("ownerSecurityDialog").close(); el("ownerDashboard").hidden = true; el("ownerSignIn").hidden = false;
    el("ownerConnection").textContent = "Owner verification required";
  }
  function controls() {
    for (const button of document.querySelectorAll("main button, #ownerSecurityDialog button")) button.disabled = busy;
    el("ownerPrevious").disabled = busy || offset === 0; el("ownerNext").disabled = busy || offset + 50 >= total;
    for (const input of el("ownerAnnouncementForm").querySelectorAll("input, textarea, button")) input.disabled = busy || !active;
    el("ownerAnnouncementForm").setAttribute("aria-busy", String(busy));
  }
  async function request(action, payload = {}) {
    if (operationRevision !== revision || document.hidden) throw new DOMException("Console was cleared", "AbortError");
    const response = await fetch("/api/commons/owner/" + action, {method: "POST", credentials: "same-origin", cache: "no-store", headers: {"Content-Type": "application/json", "X-FieldForge-Chat": "preview-v1"}, body: JSON.stringify(payload)});
    const data = await response.json();
    if (operationRevision !== revision || document.hidden) throw new DOMException("Console was cleared", "AbortError");
    if (!response.ok) { const error = new Error(data.error?.message || "Owner request failed."); error.status = response.status; throw error; }
    return data;
  }
  async function run(callback) {
    if (busy) return; busy = true; operationRevision = revision; controls();
    try { await callback(); }
    catch (error) {
      if (error.name === "AbortError") { notice("Console cleared. A submitted action may have completed; resume or verify and refresh before retrying."); return; }
      if (error.status === 401 || error.status === 403 || !error.status) clear();
      notice(error.announcementOutcomeMessage || (error.status ? error.message : "The server reply was lost. An action may have completed. Resume the console or sign in with a new authenticator code, then refresh before retrying."), true);
    } finally { secretsClear(); busy = false; controls(); }
  }
  function action(text, callback) { const b = node("button", text, "secondary"); b.type = "button"; b.addEventListener("click", () => run(callback)); return b; }
  function reasonSelect(label) {
    const select = node("select"); select.setAttribute("aria-label", label);
    for (const [value, text] of [["spam", "Spam"], ["harassment", "Harassment"], ["unsafe", "Unsafe content"], ["other", "Other"]]) { const option = node("option", text); option.value = value; select.append(option); }
    select.value = "other"; return select;
  }
  function announcementNotice(message, error = false) {
    el("ownerAnnouncementStatus").textContent = message;
    el("ownerAnnouncementStatus").classList.toggle("error", error);
  }
  function announcementValues() {
    return {title: el("ownerAnnouncementTitle").value.replace(/\s+/gu, " ").trim(),
      body: el("ownerAnnouncementBody").value.replace(/\r\n?/g, "\n").trim()};
  }
  function unsupportedAnnouncementText(text) {
    return Array.from(text).some(char => {
      const value = char.codePointAt(0);
      return value < 32 && ![9, 10, 13].includes(value) || value >= 127 && value <= 159
        || value >= 0xd800 && value <= 0xdfff || [0xfffe, 0xffff].includes(value)
        || value >= 0x202a && value <= 0x202e || value >= 0x2066 && value <= 0x2069;
    });
  }
  function announcementValidity() {
    const values = announcementValues(), titleCount = Array.from(values.title).length, bodyCount = Array.from(values.body).length;
    const bodyBytes = new TextEncoder().encode(values.body).length;
    const titleError = !values.title ? "Enter an announcement title." : titleCount > 80 ? "Use at most 80 characters in the title."
      : unsupportedAnnouncementText(el("ownerAnnouncementTitle").value) ? "Remove unsupported control characters from the title." : "";
    const bodyError = !values.body ? "Enter the announcement text." : bodyCount > 1000 ? "Use at most 1,000 characters in the announcement."
      : bodyBytes > 2000 ? "Shorten the announcement to at most 2,000 bytes."
        : unsupportedAnnouncementText(el("ownerAnnouncementBody").value) ? "Remove unsupported control characters from the announcement." : "";
    el("ownerAnnouncementTitle").setCustomValidity(titleError); el("ownerAnnouncementBody").setCustomValidity(bodyError);
    el("ownerAnnouncementTitleCount").textContent = `${titleCount} / 80 characters`;
    el("ownerAnnouncementBodyCount").textContent = `${bodyCount} / 1,000 characters · ${bodyBytes} / 2,000 bytes`;
    el("ownerAnnouncementTitleCount").classList.toggle("error", titleCount > 80);
    el("ownerAnnouncementBodyCount").classList.toggle("error", bodyCount > 1000 || bodyBytes > 2000);
    return {...values, titleError, bodyError};
  }
  function clearAnnouncementDraft() {
    announcementDraft = null; el("ownerAnnouncementForm").reset();
    el("ownerAnnouncementTitle").value = ""; el("ownerAnnouncementBody").value = "";
    announcementValidity(); announcementNotice("");
  }
  function renderAnnouncements(data) {
    const list = el("ownerAnnouncementList"), announcements = data.announcements;
    const existing = new Map(Array.from(list.querySelectorAll("article")).map(article => [Number(article.dataset.id), article]));
    const ids = new Set(announcements.map(announcement => announcement.id));
    for (const [id, article] of existing) if (!ids.has(id)) article.remove();
    for (const placeholder of list.querySelectorAll(".announcement-empty")) placeholder.remove();
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
      const button = action("Withdraw announcement", async () => {
        if (!active || document.hidden) return;
        if (!confirm(`Withdraw “${announcement.title}” from Commons? Members will no longer see it among current notices. Existing copies cannot be recalled.`)) return;
        const generation = revision;
        announcementNotice("Withdrawing announcement…");
        try {
          await request("announcements/withdraw", {announcement: announcement.id}); await refresh();
          if (generation !== revision || !active || document.hidden) return;
          announcementNotice("Announcement withdrawn. Publish a new announcement if you need to share a correction.");
          notice("Owner announcement withdrawn.");
        } catch (error) {
          if (generation === revision && active && !document.hidden && error.name !== "AbortError") announcementNotice(error.message, true);
          throw error;
        }
      });
      button.setAttribute("aria-label", "Withdraw announcement: " + announcement.title); article.append(button);
      if (previous) previous.replaceWith(article); else list.insertBefore(article, list.children[index] || null);
    }
    if (!announcements.length) list.append(node("p", "No active announcements. Publish a notice when you have something to share with everyone in Commons.", "hint announcement-empty"));
    el("ownerAnnouncementCount").textContent = `${announcements.length} of 5 active`;
  }
  async function publishAnnouncement() {
    if (!active || busy || document.hidden) return;
    const {title, body, titleError, bodyError} = announcementValidity();
    if (titleError || bodyError) {
      announcementNotice(titleError || bodyError, true); el("ownerAnnouncementForm").reportValidity(); return;
    }
    const signature = JSON.stringify({title, body});
    if (announcementDraft?.signature !== signature) announcementDraft = {signature, id: crypto.randomUUID()};
    const submitted = announcementDraft;
    await run(async () => {
      const generation = revision;
      let confirmed = null;
      announcementNotice("Publishing announcement…");
      try {
        const result = await request("announcements/publish", {title, body, request_id: submitted.id});
        if (generation !== revision || !active || document.hidden) return;
        confirmed = result.withdrawn ? "withdrawn" : "published";
        // Disabled fields prevent edits during publication; the signature guard
        // also protects a newer draft if another script changes the form.
        if (announcementDraft === submitted && JSON.stringify(announcementValues()) === signature) clearAnnouncementDraft();
        await refresh();
        if (generation !== revision || !active || document.hidden) return;
        const message = result.withdrawn
          ? "This announcement was already published and then withdrawn. It was not published again. Use a new draft to create another announcement."
          : "Announcement published. Members see it in rooms and their private inboxes.";
        announcementNotice(message); notice(result.withdrawn ? "The earlier announcement is already withdrawn." : "Owner announcement published.");
      } catch (error) {
        if (generation === revision && active && !document.hidden && error.name !== "AbortError") {
          if (confirmed) {
            error.announcementOutcomeMessage = (confirmed === "published"
              ? "The announcement was published, but the console could not refresh."
              : "The earlier announcement is already withdrawn; the console could not refresh.")
              + " Refresh the console to check current notices.";
            announcementNotice(error.announcementOutcomeMessage, true);
          } else announcementNotice((error.status ? error.message : "Publication could not be confirmed.") + " Your draft is retained until the console is cleared.", true);
        }
        throw error;
      }
    });
  }
  function renderReports(data) {
    el("ownerReports").replaceChildren(); el("ownerReportCount").textContent = data.reports.length + " shown";
    if (!data.reports.length) el("ownerReports").append(node("p", "No retained reports yet.", "hint"));
    for (const report of data.reports) {
      const card = node("article", undefined, "owner-report"); card.dataset.message = report.message; card.dataset.scope = report.scope;
      card.append(node("span", report.scope === "private" ? "Reported private message" : "Public room · " + report.location, "tag"));
      card.append(node("h3", report.author), node("p", `${report.reporter} reported ${report.reason} · ${date(report.created)}`, "hint"));
      card.append(node("p", report.lifetime === "view_once" ? "Open-once body is unavailable to moderation." : report.body || "Message body already removed.", "owner-report-body"));
      if (report.resolution) card.append(node("p", `${report.resolution.outcome === "remove" ? "Removed" : "Dismissed"} · ${report.resolution.reason} · ${date(report.resolution.updated)}`, "hint"));
      if (report.resolution?.outcome !== "remove") {
        const actions = node("div", undefined, "owner-actions"), reason = reasonSelect(`Report reason for ${report.scope} message ${report.message}`);
        actions.append(reason);
        for (const [label, value] of [["Dismiss report", "dismiss"], ["Remove message", "remove"]]) actions.append(action(label, async () => {
          if (!confirm(value === "remove" ? "Remove this reported message from chat? Existing screenshots and exported copies cannot be removed." : "Mark this report dismissed without removing the message?")) return;
          await request("resolve", {scope: report.scope, message: report.message, action: value, reason: reason.value}); await refresh(); notice("Report decision saved.");
        }));
        card.append(actions);
      }
      el("ownerReports").append(card);
    }
  }
  function renderMembers(data) {
    total = data.total; offset = data.offset; el("ownerMembers").replaceChildren();
    el("ownerMemberCount").textContent = total ? `${offset + 1}–${Math.min(offset + 50, total)} of ${total}` : "No matches";
    for (const member of data.members) {
      const row = node("article", undefined, "owner-member"); row.dataset.participant = member.id;
      const identity = member.closed ? "Closed account · Access permanently removed" : `${member.owner ? "Sole owner" : member.username ? "Account · " + member.username : "Guest identity"} · ${member.suspended ? "Suspended" : member.active_session ? "Session active" : "Signed out"}`;
      row.append(node("strong", member.name), node("p", identity, "hint"));
      if (!member.owner && !member.closed) {
        const actions = node("div", undefined, "owner-actions"), reason = reasonSelect("Access reason for " + member.name); actions.append(reason);
        for (const [text, operation] of [[member.suspended ? "Restore access" : "Suspend", member.suspended ? "restore" : "suspend"], ["Revoke session", "revoke"]]) actions.append(action(text, async () => {
          if (!confirm(`${text} for ${member.name}? This action will be recorded.`)) return;
          await request("control", {target: member.id, action: operation, reason: reason.value}); await refresh(); notice(`${text}: decision saved.`);
        }));
        row.append(actions);
      }
      el("ownerMembers").append(row);
    }
  }
  async function refresh() {
    const generation = revision;
    const [dashboard, reports, members, announcements] = await Promise.all([request("dashboard"), request("reports"), request("members", {query, offset}), request("announcements")]);
    if (generation !== revision || document.hidden) return;
    active = true; el("ownerSignIn").hidden = true; el("ownerDashboard").hidden = false;
    el("ownerConnection").textContent = "Owner verified"; el("ownerExpiry").textContent = "Verification expires " + date(dashboard.owner_expires) + ". Refresh is manual; hidden tabs clear this dashboard.";
    el("ownerAccountCount").textContent = dashboard.accounts; el("ownerGuestCount").textContent = dashboard.guests; el("ownerClosedCount").textContent = dashboard.closed_accounts; el("ownerSuspendedCount").textContent = dashboard.suspended;
    renderReports(reports); renderMembers(members); renderAnnouncements(announcements); el("ownerAudit").replaceChildren();
    for (const entry of dashboard.audit) {
      const row = node("div", undefined, "owner-audit-row"); row.append(node("strong", entry.event.replaceAll("_", " ")), node("span", entry.target_label || entry.target), node("span", entry.reason), node("time", date(entry.created))); el("ownerAudit").append(row);
    }
    clearTimeout(expiryTimer); expiryTimer = setTimeout(() => { clear(); notice("Owner verification expired. Sign in with your password and a fresh authenticator code."); }, Math.max(0, dashboard.owner_expires * 1000 - Date.now()));
    controls();
  }
  el("ownerLoginForm").addEventListener("submit", event => { event.preventDefault(); run(async () => {
    const generation = revision;
    try {
      await request("login", {username: el("ownerUsername").value, password: el("ownerPassword").value, code: el("ownerCode").value, consent: el("ownerConsent").checked});
      if (generation !== revision || document.hidden) return;
      await refresh(); notice("Owner verified. Review reports and record decisions below.");
    } finally { secretsClear(); }
  }); });
  el("ownerResume").addEventListener("click", () => run(async () => { await refresh(); if (active) notice("Verified owner console resumed."); }));
  el("ownerRefresh").addEventListener("click", () => run(async () => { await refresh(); if (active) notice("Console refreshed."); }));
  el("ownerLock").addEventListener("click", () => run(async () => { await request("lock"); clear(); notice("Owner console locked. Your ordinary chat session remains signed in."); }));
  el("ownerSearchForm").addEventListener("submit", event => { event.preventDefault(); run(async () => { query = el("ownerSearch").value; offset = 0; await refresh(); }); });
  el("ownerAnnouncementForm").addEventListener("submit", event => { event.preventDefault(); publishAnnouncement(); });
  el("ownerAnnouncementForm").addEventListener("input", () => {
    announcementDraft = null; announcementNotice(""); announcementValidity();
  });
  el("ownerAnnouncementClear").addEventListener("click", () => {
    if (!active || busy || document.hidden) return;
    clearAnnouncementDraft(); el("ownerAnnouncementTitle").focus();
  });
  for (const [id, direction] of [["ownerPrevious", -1], ["ownerNext", 1]]) el(id).addEventListener("click", () => run(async () => { offset = Math.max(0, offset + 50 * direction); await refresh(); }));
  el("ownerSecurity").addEventListener("click", () => { el("ownerSecurityForm").reset(); el("ownerSecurityError").textContent = ""; el("ownerSecurityDialog").showModal(); });
  el("ownerSecurityCancel").addEventListener("click", () => el("ownerSecurityDialog").close());
  el("ownerSecurityDialog").addEventListener("close", secretsClear);
  el("ownerSecurityDialog").addEventListener("cancel", event => { if (busy) event.preventDefault(); });
  el("ownerSecurityForm").addEventListener("submit", event => { event.preventDefault();
    if (el("ownerNewPassword").value !== el("ownerConfirmPassword").value) { el("ownerSecurityError").textContent = "The new passwords do not match."; return; }
    run(async () => {
      const generation = revision;
      const result = await request("password", {password: el("ownerCurrentPassword").value, code: el("ownerSecurityCode").value, new_password: el("ownerNewPassword").value});
      if (generation !== revision || document.hidden) return;
      clear(); el("ownerRecoveryValue").value = result.recovery_code; delete result.recovery_code; el("ownerRecoveryDialog").showModal(); notice("Owner credentials updated. Save the new recovery code, then sign in with a fresh authenticator code.");
    });
  });
  el("ownerRecoverySaved").addEventListener("change", () => { el("ownerRecoveryDone").disabled = !el("ownerRecoverySaved").checked; });
  el("ownerRecoveryDone").addEventListener("click", recoveryClear);
  el("ownerRecoveryDialog").addEventListener("cancel", event => { event.preventDefault(); if (confirm("Clear this recovery code without saving it? You can replace it after signing in with your password and authenticator.")) recoveryClear(); });
  document.addEventListener("visibilitychange", () => { if (document.hidden) { clear(); notice("Console and credential fields cleared while the tab was hidden. Resume verified console or sign in when ready."); } });
  window.addEventListener("pagehide", clear);
  window.addEventListener("offline", () => { clear(); notice("Connection changed. Verify or resume the console when ready."); });
  announcementValidity(); controls();
})();
