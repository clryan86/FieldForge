"use strict";
window.CommonsAccounts = class {
  constructor({request, notice, connected}) {
    Object.assign(this, {request, notice, connected});
    this.el = id => document.getElementById(id);
    this.busy = false;
    for (const [id, mode] of [["openSignIn", "login"], ["openRegister", "register"], ["openRecover", "recover"]]) {
      this.el(id).addEventListener("click", () => this.open(mode));
    }
    this.el("accountManage").addEventListener("click", () => this.open(this.viewer?.account ? "password" : "register"));
    this.el("accountCancel").addEventListener("click", () => this.el("accountDialog").close());
    this.el("accountDialog").addEventListener("cancel", event => { if (this.busy) event.preventDefault(); });
    this.el("accountDialog").addEventListener("close", () => this.clearFields());
    this.el("accountForm").addEventListener("submit", event => { event.preventDefault(); this.submit(); });
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
        if (this.el("recoveryDialog").open) {
          this.clearRecovery();
          notice("Recovery code cleared when the tab was hidden. If you did not save it, sign in and use Account security to replace it.");
        }
      }
    });
    window.addEventListener("pagehide", () => { this.clearFields(); this.clearRecovery(); });
  }
  setBusy(busy) {
    this.busy = busy;
    for (const input of this.el("accountForm").querySelectorAll("input, select, button")) {
      input.disabled = busy || input.closest("[hidden]") !== null;
    }
    for (const id of ["openSignIn", "openRegister", "openRecover", "resumeSession"]) this.el(id).disabled = busy;
    this.el("accountManage").disabled = busy || !this.active;
  }
  setSession(joined, active, viewer) {
    this.viewer = viewer; this.active = active;
    this.el("accountBar").hidden = !joined;
    const account = viewer?.account;
    this.el("accountIdentity").textContent = account ? `Local account · ${viewer.name}` : "Temporary guest session";
    this.el("accountHint").textContent = account ? "Your inbox and contact code stay with your account after sign-out." : "Save this session as an account before signing out to keep access to your inbox.";
    this.el("accountManage").textContent = account ? "Account security" : "Save my account";
    this.el("accountManage").disabled = !active || this.busy;
    this.el("contactHint").textContent = account ? "Your contact code stays the same across sign-ins. People with this code can invite you while you are signed out." : "Share this code with someone you want to hear from. Guest identities last up to eight hours. Save an account to keep this code.";
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
    if (this.busy) return;
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
    if (this.busy) return;
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
};
