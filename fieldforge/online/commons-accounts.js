"use strict";
window.CommonsAccounts = class {
  constructor({request, notice, connected, quiesce, disconnected, refresh}) {
    Object.assign(this, {request, notice, connected, quiesce, disconnected, refresh});
    this.el = id => document.getElementById(id);
    this.busy = false;
    this.joined = false; this.active = false; this.viewer = null;
    this.lifecycleMode = null; this.lifecycleEpoch = 0; this.lifecycleTarget = null;
    this.operation = null; this.exportReturnToClose = false; this.downloads = new Set();
    for (const [id, mode] of [["openSignIn", "login"], ["openRegister", "register"], ["openRecover", "recover"]]) {
      this.el(id).addEventListener("click", () => this.open(mode));
    }
    this.el("accountManage").addEventListener("click", () => this.open(this.viewer?.account ? "password" : "register"));
    this.el("accountCancel").addEventListener("click", () => this.el("accountDialog").close());
    this.el("accountDialog").addEventListener("cancel", event => { if (this.busy) event.preventDefault(); });
    this.el("accountDialog").addEventListener("close", () => this.clearFields());
    this.el("accountForm").addEventListener("submit", event => { event.preventDefault(); this.submit(); });
    this.el("openAccountExport").addEventListener("click", () => this.openLifecycle("export"));
    this.el("openAccountClose").addEventListener("click", () => this.openLifecycle("close"));
    this.el("accountCloseExport").addEventListener("click", () => this.openLifecycle("export", true));
    this.el("accountCloseBack").addEventListener("click", () => this.backLifecycle("password"));
    this.el("accountExportBack").addEventListener("click", () => this.backLifecycle(this.exportReturnToClose ? "close" : "password"));
    this.el("accountExportForm").addEventListener("submit", event => { event.preventDefault(); this.exportAccount(); });
    this.el("accountCloseForm").addEventListener("submit", event => { event.preventDefault(); this.closeAccount(); });
    this.el("accountCloseForm").addEventListener("input", () => this.lifecycleControls());
    this.el("accountCloseForm").addEventListener("change", () => this.lifecycleControls());
    for (const [mode, id] of [["export", "accountExportDialog"], ["close", "accountCloseDialog"]]) {
      this.el(id).addEventListener("cancel", event => {
        event.preventDefault();
        if (this.operation?.mode !== "close") this.resetLifecycle();
      });
      this.el(id).addEventListener("close", () => {
        if (this.lifecycleMode === mode && !this.el(id).open) this.resetLifecycle();
      });
    }
    this.el("resumeSession").addEventListener("click", async () => {
      if (this.busy) return;
      this.setBusy(true);
      try { await this.connected(await request("account/resume", {consent: true})); }
      catch (error) { notice(error.status === 401 ? "No active session remains. Sign in to your account or join as a guest." : error.message, true); }
      finally { this.setBusy(false); }
    });
    this.el("recoverySaved").addEventListener("change", () => { this.el("recoveryContinue").disabled = !this.el("recoverySaved").checked; });
    this.el("recoveryContinue").addEventListener("click", () => this.clearRecovery());
    this.el("recoveryDialog").addEventListener("cancel", event => {
      event.preventDefault();
      if (confirm("Clear this code without saving it? You can generate a replacement through Account security if you know your password.")) this.clearRecovery();
    });
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) {
        this.clearFields();
        const closing = this.operation?.mode === "close";
        this.resetLifecycle();
        if (closing) notice("Account closure was submitted. Its result is still pending; the confirmation fields have been cleared.");
        if (this.el("recoveryDialog").open) {
          this.clearRecovery();
          notice("Recovery code cleared when the tab was hidden. If you did not save it, sign in and use Account security to replace it.");
        }
      } else if (this.operation?.mode === "close" && this.active && this.sameIdentity(this.operation)) this.quiesce?.(this.operation.viewerId);
      this.lifecycleControls();
    });
    window.addEventListener("pagehide", () => { this.clearFields(); this.clearRecovery(); this.resetLifecycle({abandon: true}); });
    window.addEventListener("offline", () => this.resetLifecycle());
  }
  setBusy(busy) {
    this.busy = busy;
    const locked = busy || Boolean(this.operation);
    for (const input of this.el("accountForm").querySelectorAll("input, select, button")) {
      input.disabled = locked || input.closest("[hidden]") !== null;
    }
    for (const id of ["openSignIn", "openRegister", "openRecover", "resumeSession"]) this.el(id).disabled = locked;
    this.el("accountManage").disabled = locked || !this.active;
    this.lifecycleControls();
  }
  setSession(joined, active, viewer) {
    const changed = (this.viewer?.id || null) !== (viewer?.id || null);
    if (changed || this.joined && !joined) this.resetLifecycle({abandon: true});
    else if (this.active && !active) this.resetLifecycle();
    this.viewer = viewer; this.active = active; this.joined = joined;
    this.el("accountBar").hidden = !joined;
    const account = viewer?.account;
    this.el("accountIdentity").textContent = account ? `Local account · ${viewer.name}` : "Temporary guest session";
    this.el("accountHint").textContent = account ? "Your inbox and contact code stay with your account after sign-out." : "Save this session as an account before signing out to keep access to your inbox.";
    this.el("accountManage").textContent = account ? "Account security" : "Save my account";
    this.el("accountManage").disabled = !active || this.busy || Boolean(this.operation);
    this.el("contactHint").textContent = account ? "Your contact code stays the same across sign-ins. People with this code can invite you while you are signed out." : "Share this code with someone you want to hear from. Guest identities last up to eight hours. Save an account to keep this code.";
    this.lifecycleControls();
  }
  clearFields() {
    for (const id of ["accountPassword", "accountNewPassword", "accountConfirm", "accountRecovery"]) this.el(id).value = "";
  }
  clearRecovery() {
    this.el("recoveryValue").value = "";
    this.el("recoverySaved").checked = false;
    this.el("recoveryContinue").disabled = true;
    this.el("recoveryDialog").close();
  }
  open(mode) {
    if (this.busy || this.operation) return;
    this.resetLifecycle();
    this.mode = mode; this.el("accountForm").reset(); this.el("accountError").textContent = "";
    const copy = {
      register: ["Create a local account", "Keep your inbox and contact code on this server. Saving a guest session keeps its conversations and changes its visible name to your username.", "Create local account"],
      login: ["Welcome back", "Sign in to your inbox on this server. This ends any previous session for this account.", "Sign in to Commons"],
      recover: ["Recover your account", "Use your saved recovery code to choose a new password. This ends the old session and replaces the code. You will then sign in with your new password.", "Reset password"],
      password: ["Account security", "Update your password and replace your recovery code. The current session will rotate. You may use the same password if you only need a fresh recovery code.", "Update account security"]
    }[mode];
    [this.el("accountTitle").textContent, this.el("accountDescription").textContent, this.el("accountSubmit").textContent] = copy;
    for (const [field, visible] of Object.entries({Username: mode !== "password", Password: mode !== "recover", Recovery: mode === "recover", NewPassword: ["recover", "password"].includes(mode), Confirm: mode !== "login", Skill: mode === "register", Consent: mode !== "password"})) {
      this.el(`account${field}Field`).hidden = !visible;
    }
    this.el("accountPasswordLabel").textContent = mode === "password" ? "Current password" : "Password";
    this.el("accountPassword").autocomplete = mode === "register" ? "new-password" : "current-password";
    if (mode === "register" && this.viewer) {
      this.el("accountUsername").value = /^[A-Za-z][A-Za-z0-9_]{2,31}$/.test(this.viewer.name) ? this.viewer.name : "";
      this.el("accountSkill").value = this.el("skill").value;
    }
    this.setBusy(false); this.el("accountDialog").showModal();
  }
  async submit() {
    if (this.busy || this.operation) return;
    const mode = this.mode, value = id => this.el(id).value;
    const password = value("accountPassword"), newPassword = value("accountNewPassword");
    if (mode !== "login" && value("accountConfirm") !== (mode === "register" ? password : newPassword)) {
      this.el("accountError").textContent = "The passwords do not match."; return;
    }
    const payload = mode === "password" ? {password, new_password: newPassword} : {username: value("accountUsername"), consent: this.el("accountConsent").checked};
    if (["register", "login"].includes(mode)) payload.password = password;
    if (mode === "register") payload.skill = value("accountSkill");
    if (mode === "recover") Object.assign(payload, {recovery_code: value("accountRecovery"), new_password: newPassword});
    this.setBusy(true); this.el("accountError").textContent = "";
    try {
      const data = await this.request("account/" + mode, payload);
      this.el("accountDialog").close();
      if (data.viewer) await this.connected(data);
      else this.notice("Password reset. Sign in using your new password after saving the replacement recovery code.");
      if (data.recovery_code) {
        if (!document.hidden) { this.el("recoveryValue").value = data.recovery_code; this.el("recoveryDialog").showModal(); }
        else this.notice("Account updated while the tab was hidden. Sign in and use Account security to generate a recovery code you can save.");
        delete data.recovery_code;
      }
    } catch (error) {
      this.el("accountError").textContent = error.message || "The local server could not be reached.";
      if (!error.status) this.el("accountError").textContent += " If the update completed but its reply was lost, try signing in with your chosen password, then use Account security to replace the recovery code.";
    } finally { this.clearFields(); this.setBusy(false); }
  }
  username() { return this.viewer?.username || this.viewer?.name || ""; }
  isOwner() { return this.username().toLowerCase() === "clryan86"; }
  available() { return this.joined && this.active && this.viewer?.account && !document.hidden && navigator.onLine !== false; }
  sameIdentity(operation) { return this.joined && this.viewer?.id === operation.viewerId; }
  lifecycleCurrent(operation) {
    return this.operation === operation && this.lifecycleEpoch === operation.epoch && this.lifecycleMode === operation.mode
      && this.sameIdentity(operation) && this.available() && this.el(operation.mode === "export" ? "accountExportDialog" : "accountCloseDialog").open;
  }
  lifecycleControls() {
    const available = this.available(), locked = this.busy || Boolean(this.operation);
    this.el("accountDataSection").hidden = this.mode !== "password" || !this.viewer?.account;
    this.el("openAccountExport").disabled = !available || locked;
    this.el("openAccountClose").hidden = this.isOwner();
    this.el("openAccountClose").disabled = !available || locked || this.isOwner();
    this.el("accountOwnerCloseNote").hidden = !this.isOwner();
    for (const element of document.querySelectorAll("#accountExportForm input, #accountExportForm button, #accountCloseForm input, #accountCloseForm button")) element.disabled = !available || locked;
    this.el("accountExportBack").disabled = !available || this.busy || this.operation?.mode === "close";
    this.el("accountCloseBack").disabled = !available || locked;
    const usernameMatches = Boolean(this.lifecycleTarget?.username) && this.el("accountCloseUsername").value.trim().toLowerCase() === this.lifecycleTarget.username.toLowerCase();
    const password = this.el("accountClosePassword").value;
    this.el("accountCloseSubmit").disabled = !available || locked || this.isOwner() || !usernameMatches || !this.el("accountCloseConfirm").checked || password.length < 15 || password.length > 128;
    this.el("accountExportProgress").hidden = this.operation?.mode !== "export" || this.lifecycleMode !== "export";
    this.el("accountExportDialog").setAttribute("aria-busy", String(this.operation?.mode === "export"));
    this.el("accountCloseDialog").setAttribute("aria-busy", String(this.operation?.mode === "close"));
  }
  finishExportGrant(operation) {
    const grant = operation.exportToken; operation.exportToken = null;
    if (grant && this.sameIdentity(operation) && this.active && !document.hidden) {
      this.request("account/export/finish", {export_token: grant}).catch(() => {});
    }
  }
  resetLifecycle({abandon = false} = {}) {
    const operation = this.operation;
    this.lifecycleEpoch++; this.lifecycleMode = null; this.lifecycleTarget = null;
    if (operation && (operation.mode === "export" || abandon)) {
      operation.controller.abort(); clearTimeout(operation.timeout);
      if (operation.parts) operation.parts.length = 0;
      if (!abandon && operation.mode === "export") this.finishExportGrant(operation);
      this.operation = null;
    }
    for (const id of ["accountExportDialog", "accountCloseDialog"]) if (this.el(id).open) this.el(id).close();
    this.el("accountExportForm").reset(); this.el("accountCloseForm").reset();
    for (const id of ["accountExportIdentity", "accountCloseIdentity", "accountCloseUsernameHint", "accountExportStatus", "accountCloseStatus"]) this.el(id).textContent = "";
    this.el("accountExportProgress").value = 0;
    for (const url of this.downloads) URL.revokeObjectURL(url);
    this.downloads.clear(); this.setBusy(this.busy);
  }
  openLifecycle(mode, returnToClose = false) {
    if (!this.available() || this.busy || this.operation || mode === "close" && this.isOwner()) return;
    this.resetLifecycle(); this.el("accountDialog").close(); this.clearFields();
    this.lifecycleMode = mode; this.lifecycleTarget = {id: this.viewer.id, username: this.username()};
    this.exportReturnToClose = returnToClose;
    if (mode === "export") {
      this.el("accountExportIdentity").textContent = "@" + this.lifecycleTarget.username;
      this.el("accountExportBack").textContent = returnToClose ? "Back to close account" : "Back to account security";
    } else {
      this.el("accountCloseIdentity").textContent = "@" + this.lifecycleTarget.username;
      this.el("accountCloseUsernameHint").textContent = "Type " + this.lifecycleTarget.username + " without the @ sign.";
    }
    this.el(mode === "export" ? "accountExportDialog" : "accountCloseDialog").showModal();
    this.lifecycleControls();
  }
  backLifecycle(destination) {
    if (this.operation?.mode === "close") return;
    this.resetLifecycle();
    if (!this.available()) return;
    if (destination === "close") this.openLifecycle("close");
    else this.open("password");
  }
  beginLifecycle(mode) {
    if (!this.available() || this.busy || this.operation || this.lifecycleMode !== mode || this.lifecycleTarget?.id !== this.viewer.id || mode === "close" && this.isOwner()) return null;
    const operation = {mode, epoch: this.lifecycleEpoch, viewerId: this.viewer.id, controller: new AbortController(), exportToken: null, parts: []};
    this.operation = operation; this.setBusy(this.busy); return operation;
  }
  requireLifecycle(operation) {
    if (!this.lifecycleCurrent(operation)) throw new DOMException("This account view changed.", "AbortError");
  }
  lifecycleStatus(mode, text, error = false) {
    const element = this.el(mode === "export" ? "accountExportStatus" : "accountCloseStatus");
    element.textContent = text; element.classList.toggle("error", error);
  }
  async exportAccount() {
    const password = this.el("accountExportPassword").value;
    const operation = this.beginLifecycle("export"); if (!operation) return;
    this.el("accountExportPassword").value = "";
    this.lifecycleStatus("export", "Preparing your account export…");
    const sections = ["public_messages", "private_messages", "public_reports", "private_reports"];
    const labels = {public_messages: "public messages", private_messages: "saved private messages", public_reports: "public reports", private_reports: "private reports"};
    const counts = Object.fromEntries(sections.map(section => [section, 0]));
    try {
      const started = await this.request("account/export", {password}, operation.controller.signal);
      this.requireLifecycle(operation);
      const manifest = started.manifest;
      if (!manifest || manifest.format !== "fieldforge-commons-account" || manifest.version !== 1 || typeof started.export_token !== "string") throw new Error("The server returned an unsupported account export.");
      operation.exportToken = started.export_token;
      const total = sections.reduce((sum, section) => sum + (Number.isSafeInteger(manifest.totals?.[section]) ? manifest.totals[section] : 0), 0);
      this.el("accountExportProgress").max = Math.max(1, total);
      operation.parts.push(JSON.stringify(manifest).slice(0, -1));
      for (const section of sections) {
        let after = 0;
        operation.parts.push(`,"${section}":[`);
        while (true) {
          this.lifecycleStatus("export", `Collecting your ${labels[section]}… ${counts[section]} records collected.`);
          const page = await this.request("account/export/page", {export_token: operation.exportToken, section, after}, operation.controller.signal);
          this.requireLifecycle(operation);
          if (page.section !== section || !Array.isArray(page.records) || page.records.length > 500 || page.next_after !== null && (!Number.isSafeInteger(page.next_after) || page.next_after <= after)) throw new Error("The server returned an invalid export page. Start a fresh export.");
          if (page.records.length) {
            // Store each serialized page in a Blob chunk; never collect every
            // record into one giant object and serialize it a second time.
            operation.parts.push(new Blob([counts[section] ? "," : "", JSON.stringify(page.records).slice(1, -1)]));
            counts[section] += page.records.length;
            this.el("accountExportProgress").value = Object.values(counts).reduce((sum, count) => sum + count, 0);
          }
          if (page.next_after === null) break;
          after = page.next_after;
        }
        operation.parts.push("]");
      }
      this.lifecycleStatus("export", "Finishing your private download…");
      await this.request("account/export/finish", {export_token: operation.exportToken}, operation.controller.signal);
      this.requireLifecycle(operation); operation.exportToken = null;
      operation.parts.push(`,"finished_at":${Date.now() / 1000},"counts":${JSON.stringify(counts)}}`);
      const blob = new Blob(operation.parts, {type: "application/json"});
      const url = URL.createObjectURL(blob); this.downloads.add(url);
      const link = document.createElement("a"); link.href = url; link.download = "fieldforge-commons-my-account.json"; link.click();
      setTimeout(() => { URL.revokeObjectURL(url); this.downloads.delete(url); }, 1000);
      this.lifecycleStatus("export", `Account data download started. ${Object.values(counts).reduce((sum, count) => sum + count, 0)} records were collected, along with the account details shown in the export.`);
    } catch (error) {
      if (this.lifecycleCurrent(operation) && error.name !== "AbortError") {
        this.lifecycleStatus("export", "Export stopped. " + (error.message || "The local server could not be reached.") + " No file was downloaded. Start a new export to try again.", true);
      }
      this.finishExportGrant(operation);
    } finally {
      operation.parts.length = 0;
      if (this.operation === operation) this.operation = null;
      if (this.lifecycleEpoch === operation.epoch) this.el("accountExportPassword").value = "";
      this.setBusy(this.busy);
    }
  }
  async closeAccount() {
    const password = this.el("accountClosePassword").value, username = this.el("accountCloseUsername").value.trim();
    if (!this.el("accountCloseConfirm").checked || username.toLowerCase() !== this.lifecycleTarget?.username.toLowerCase() || password.length < 15) return;
    if (typeof this.quiesce !== "function" || typeof this.disconnected !== "function") { this.lifecycleStatus("close", "Account closure is unavailable in this preview.", true); return; }
    const operation = this.beginLifecycle("close"); if (!operation) return;
    this.el("accountClosePassword").value = "";
    if (!this.quiesce(operation.viewerId)) {
      this.operation = null; this.lifecycleStatus("close", "Your session changed. Reopen Account security before continuing.", true); this.setBusy(this.busy); return;
    }
    this.lifecycleStatus("close", "Closing your account…");
    operation.timeout = setTimeout(() => operation.controller.abort(), 30000);
    try {
      const result = await this.request("account/close", {password, username, confirm: true}, operation.controller.signal);
      if (result.closed !== true) throw new Error("The server did not confirm account closure.");
      if (!this.sameIdentity(operation)) return;
      if (this.operation === operation) this.operation = null;
      this.resetLifecycle();
      if (this.disconnected(operation.viewerId)) this.notice("Account closed. Your account, profile, photo, and authored message bodies were removed. Your former username cannot be reused.");
    } catch (error) {
      if (!this.sameIdentity(operation)) return;
      if (this.operation === operation) this.operation = null;
      if (error.status >= 400 && error.status < 500 && error.status !== 401) {
        if (this.lifecycleMode === "close" && this.lifecycleEpoch === operation.epoch) this.lifecycleStatus("close", "Your account was not closed. " + error.message, true);
        else this.notice("Your account was not closed. " + error.message, true);
        if (this.active) await this.refresh?.();
      } else {
        this.resetLifecycle();
        if (this.disconnected(operation.viewerId)) this.notice("Account closure could not be confirmed. This tab was cleared. The account may still exist; try signing in to check before deciding whether to submit another closure request.", true);
      }
    } finally {
      clearTimeout(operation.timeout);
      if (this.operation === operation) this.operation = null;
      if (this.lifecycleEpoch === operation.epoch) this.el("accountClosePassword").value = "";
      this.setBusy(this.busy);
    }
  }
};
