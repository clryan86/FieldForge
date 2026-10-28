"use strict";
window.CommonsProfile = class {
  constructor({request, notice, failed, refresh, openConversation}) {
    Object.assign(this, {request, notice, failed, refresh, openConversation});
    this.el = id => document.getElementById(id);
    this.joined = false; this.active = false; this.viewer = null; this.identity = null;
    this.mode = null; this.epoch = 0; this.busy = false; this.revision = null;
    this.requests = new Set(); this.downloads = new Set();
    this.invitationRequests = new Map(); this.invitationRetry = null;
    this.inviteTarget = null; this.inviteEpoch = 0; this.inviteBusy = false; this.inviteController = null;
    this.categories = []; this.contributionTypes = []; this.experienceLevels = [];
    this.photoAssetId = null; this.saved = false; this.photoUploads = false; this.conflict = false;
    this.directory = {query: "", category: "", offset: 0, total: 0, limit: 12};
    this.el("openProfile").addEventListener("click", () => this.open("profile"));
    this.el("openDirectory").addEventListener("click", () => this.open("directory"));
    for (const mode of ["profile", "directory"]) {
      this.el(mode === "profile" ? "closeProfile" : "closeDirectory").addEventListener("click", () => this.close());
      this.el(mode + "Dialog").addEventListener("cancel", event => { event.preventDefault(); this.close(); });
      this.el(mode + "Dialog").addEventListener("close", () => {
        if (this.mode === mode && !this.el(mode + "Dialog").open) this.close();
      });
    }
    this.el("profileSaveAccount").addEventListener("click", () => {
      if (!this.available()) return;
      this.close(); this.el("accountManage").click();
    });
    this.el("profileForm").addEventListener("submit", event => { event.preventDefault(); this.save(); });
    this.el("profileForm").addEventListener("input", () => this.controls());
    this.el("profileForm").addEventListener("change", () => this.controls());
    this.el("profileReload").addEventListener("click", () => {
      if (confirm("Replace the current draft with your saved profile? Unsaved profile edits will be cleared.")) this.loadProfile();
    });
    this.el("profilePhotoUpload").addEventListener("click", () => this.uploadPhoto());
    this.el("profilePhotoRemove").addEventListener("click", () => this.removePhoto());
    this.el("profileDelete").addEventListener("click", () => this.deleteProfile());
    this.el("profileExport").addEventListener("click", () => this.exportProfile());
    this.el("directorySearchForm").addEventListener("submit", event => { event.preventDefault(); this.searchDirectory(); });
    this.el("directoryRefresh").addEventListener("click", () => this.searchDirectory());
    this.el("directoryPrevious").addEventListener("click", () => this.loadDirectory(Math.max(0, this.directory.offset - 12)));
    this.el("directoryNext").addEventListener("click", () => this.loadDirectory(this.directory.offset + 12));
    this.el("directoryInviteForm").addEventListener("submit", event => { event.preventDefault(); this.sendInvitation(); });
    this.el("directoryInviteSubject").addEventListener("input", () => {
      const previous = this.invitationRequests.get(this.invitationSignature(this.inviteTarget, this.invitationSubject()));
      this.invitationStatus(previous?.closed
        ? "That invitation was already sent and the conversation has since closed. No new invitation was created."
        : previous?.unconfirmed ? "Your earlier invitation could not be confirmed. Send again to check the same request."
          : "The recipient chooses whether to accept. No message is sent yet.");
      this.controls();
    });
    this.el("directoryInviteCancel").addEventListener("click", () => this.closeInvitation());
    this.el("directoryInviteDialog").addEventListener("cancel", event => { event.preventDefault(); this.closeInvitation(); });
    this.el("directoryInviteDialog").addEventListener("close", () => {
      if (this.inviteTarget && !this.el("directoryInviteDialog").open) this.closeInvitation();
    });
    this.el("directoryInviteSaveAccount").addEventListener("click", () => {
      if (!this.available()) return;
      this.close(); this.el("accountManage").click();
    });
    this.el("directoryInviteReview").addEventListener("click", () => {
      if (this.invitationRetry?.identity === this.identity) this.openInvitation(this.invitationRetry.target, this.invitationRetry);
    });
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) this.close();
      this.controls();
    });
    window.addEventListener("pagehide", () => this.close());
    window.addEventListener("offline", () => { this.close(); this.controls(); });
    window.addEventListener("online", () => this.controls());
    this.controls();
  }
  node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  }
  available() { return this.joined && this.active && !document.hidden && navigator.onLine !== false; }
  current(epoch, mode = this.mode) { return epoch === this.epoch && this.mode === mode && this.available(); }
  setSession(joined, active, viewer) {
    const identity = joined && viewer ? `${viewer.id}:${Boolean(viewer.account)}` : null;
    if (!joined || identity !== this.identity) this.clearInvitationMemory();
    if (!joined || !active || identity !== this.identity) this.close();
    this.joined = joined; this.active = active; this.viewer = viewer; this.identity = identity;
    this.controls();
  }
  cancelRequests() {
    this.epoch++;
    for (const controller of this.requests) controller.abort();
    this.requests.clear();
  }
  clearImages(root) {
    for (const image of root.querySelectorAll("img")) image.removeAttribute("src");
    root.replaceChildren();
  }
  close() {
    this.closeInvitation();
    this.cancelRequests(); this.mode = null; this.busy = false;
    for (const id of ["profileDialog", "directoryDialog"]) if (this.el(id).open) this.el(id).close();
    this.el("profileForm").reset(); this.el("profileForm").hidden = true;
    this.el("profileGuest").hidden = true; this.el("profileConflict").hidden = true;
    this.el("profileInterests").replaceChildren(); this.el("profileContributions").replaceChildren();
    this.clearImages(this.el("profilePhotoPreview")); this.clearImages(this.el("directoryCards"));
    this.el("directorySearchForm").reset();
    for (const id of ["profileStatus", "directoryStatus", "profileUsername", "profileSharingSummary", "profilePhotoState", "directoryPage"]) this.el(id).textContent = "";
    this.el("profileSavedState").textContent = "Private profile";
    this.el("profileBioCount").textContent = "0 / 500 characters";
    this.el("profileInterestCount").textContent = "0 of 5 areas selected";
    this.categories = []; this.contributionTypes = []; this.experienceLevels = [];
    this.revision = null; this.photoAssetId = null; this.saved = false; this.photoUploads = false; this.conflict = false;
    this.directory = {query: "", category: "", offset: 0, total: 0, limit: 12};
    for (const url of this.downloads) URL.revokeObjectURL(url);
    this.downloads.clear(); this.controls();
  }
  controls() {
    const available = this.available();
    this.el("openProfile").disabled = !available; this.el("openDirectory").disabled = !available;
    const editable = available && this.viewer?.account && Number.isInteger(this.revision) && !this.busy;
    for (const input of this.el("profileForm").querySelectorAll("input, select, textarea, button")) input.disabled = !editable;
    const selected = this.el("profileInterests").querySelectorAll("input:checked");
    this.el("profileInterestCount").textContent = `${selected.length} of 5 areas selected`;
    for (const row of this.el("profileInterests").children) {
      const checkbox = row.querySelector("input"), experience = row.querySelector("select");
      checkbox.disabled = !editable || (!checkbox.checked && selected.length >= 5);
      experience.disabled = !editable || !checkbox.checked;
      row.querySelector(".profile-experience").hidden = !checkbox.checked;
    }
    this.el("profileBioCount").textContent = `${Array.from(this.el("profileBio").value).length} / 500 characters`;
    this.el("profileSave").disabled = !editable || this.conflict;
    this.el("profileReload").disabled = !available || !this.viewer?.account || this.busy;
    this.el("profileSaveAccount").disabled = !available || this.busy;
    this.el("profilePhotoFile").disabled = !editable || !this.photoUploads || this.conflict;
    this.el("profilePhotoUpload").disabled = !editable || !this.photoUploads || this.conflict || !this.el("profilePhotoFile").files.length;
    this.el("profilePhotoRemove").disabled = !editable || !this.photoAssetId || this.conflict;
    this.el("profileSharePhoto").disabled = !editable || !this.photoAssetId;
    this.el("profileDelete").disabled = !editable || (!this.saved && !this.photoAssetId) || this.conflict;
    this.el("profileConflict").hidden = !this.conflict;
    if (!this.el("profileVisibility").checked) {
      this.el("profileSharingSummary").textContent = "Your profile stays private. Save profile to apply your choices.";
    } else {
      const skills = this.el("profileShareSkills").checked ? "Your interests and ways to help will be included." : "Your interests and ways to help stay private.";
      const photo = this.el("profileSharePhoto").checked && this.photoAssetId ? "Your photo will be included." : "Your photo stays private.";
      const invitations = this.el("profileAllowInvitations").checked ? "Saved-account members may invite you to a private conversation; you choose whether to accept." : "Directory invitations are off.";
      this.el("profileSharingSummary").textContent = `When saved, your profile name, @username, and bio will be listed. ${skills} ${photo} ${invitations}`;
    }
    const directoryBusy = this.busy || Boolean(this.inviteTarget);
    for (const element of this.el("directoryDialog").querySelectorAll("input, select, button")) element.disabled = !available || directoryBusy;
    this.el("closeDirectory").disabled = false;
    this.el("directoryPrevious").disabled = !available || directoryBusy || this.directory.offset === 0;
    this.el("directoryNext").disabled = !available || directoryBusy || this.directory.offset + 12 >= this.directory.total;
    const retry = this.invitationRetry?.identity === this.identity && this.viewer?.account ? this.invitationRetry : null;
    const showRetry = this.mode === "directory" && retry;
    this.el("directoryInviteRetry").hidden = !showRetry;
    this.el("directoryInviteRetryText").textContent = showRetry ? `An invitation to @${retry.target.username} could not be confirmed. Review it and send again to check the same request without creating a duplicate.` : "";
    const canInvite = available && this.mode === "directory" && this.inviteTarget && this.viewer?.account;
    const subject = this.invitationSubject();
    const previous = this.invitationRequests.get(this.invitationSignature(this.inviteTarget, subject));
    this.el("directoryInviteSubject").disabled = !canInvite || this.inviteBusy;
    this.el("directoryInviteSend").disabled = !canInvite || this.inviteBusy || !subject || Array.from(subject).length > 100 || previous?.closed === true;
    this.el("directoryInviteSend").textContent = this.inviteBusy ? "Sending invitation…" : "Send invitation";
    this.el("directoryInviteSaveAccount").disabled = !available || this.inviteBusy;
    this.el("directoryInviteDialog").setAttribute("aria-busy", String(this.inviteBusy));
    this.el("profileDialog").setAttribute("aria-busy", String(this.mode === "profile" && this.busy));
    this.el("directoryDialog").setAttribute("aria-busy", String(this.mode === "directory" && this.busy));
  }
  tell(text, error = false, mode = this.mode) {
    if (!mode) return;
    const status = this.el(mode + "Status"); status.textContent = text; status.classList.toggle("error", error);
  }
  async call(action, payload, epoch) {
    if (!this.current(epoch)) throw new DOMException("Profile view closed.", "AbortError");
    const controller = new AbortController(); this.requests.add(controller);
    try {
      const data = await this.request("profile/" + action, payload, controller.signal);
      if (!this.current(epoch)) throw new DOMException("Profile view changed.", "AbortError");
      return data;
    } finally { this.requests.delete(controller); }
  }
  async run(mode, operation) {
    if (this.mode !== mode || !this.available() || this.busy || this.inviteTarget) return;
    this.cancelRequests(); const epoch = this.epoch;
    this.busy = true; this.controls();
    try { await operation(epoch); }
    catch (error) {
      if (!this.current(epoch, mode) || error.name === "AbortError") return;
      if (error.status === 409 && mode === "profile") {
        this.conflict = true;
        this.tell("Your saved profile changed. Your draft is retained; use Reload saved profile before saving again.", true);
      } else if (!error.status || error.status === 401) {
        this.failed(error);
        this.notice(error.status === 401
          ? "Your session ended. Profile fields and the directory were cleared. Sign in or join again when ready."
          : mode === "profile"
            ? "The profile request could not be confirmed. Chat is paused and profile fields were cleared. Resume chat and reopen My profile to check the saved version."
            : "The directory could not be loaded. Chat is paused and profiles were cleared. Choose Resume chat when ready.", true);
      }
      else this.tell(error.message || "This profile request could not be completed.", true);
    } finally {
      if (this.current(epoch, mode)) { this.busy = false; this.controls(); }
    }
  }
  open(mode) {
    if (!this.available()) return;
    this.close(); this.mode = mode; this.el(mode + "Dialog").showModal();
    if (mode === "profile") {
      if (this.viewer?.account) this.loadProfile();
      else { this.el("profileGuest").hidden = false; this.tell("A saved account is needed to create and edit a profile."); }
    } else this.loadDirectory(0);
    this.controls();
  }
  loadProfile() {
    if (!this.viewer?.account) return;
    this.run("profile", async epoch => {
      this.tell("Loading your saved profile…");
      const data = await this.call("get", {}, epoch);
      this.renderProfile(data);
      this.tell(data.saved ? "Your saved profile is ready to edit." : "Start with a private profile. Nothing is listed until you choose to share it and save.");
      await this.readPhoto(data.profile.photo_asset_id, this.el("profilePhotoPreview"), "Your saved profile photo", epoch);
    });
  }
  renderProfile(data, draft = null) {
    const profile = draft || data.profile;
    this.revision = data.revision; this.saved = Boolean(data.saved); this.conflict = false;
    this.photoAssetId = data.profile.photo_asset_id; this.photoUploads = Boolean(data.photo_uploads);
    this.categories = data.categories; this.contributionTypes = data.contribution_types; this.experienceLevels = data.experience_levels;
    this.el("profileForm").hidden = false; this.el("profileGuest").hidden = true;
    this.el("profileUsername").textContent = `@${this.viewer.username || this.viewer.name}`;
    this.el("profileSavedState").textContent = data.profile.visibility === "commons" ? "Listed in Commons" : "Private profile";
    this.el("profileDisplayName").value = profile.display_name;
    this.el("profileBio").value = profile.bio;
    this.el("profileVisibility").checked = profile.visibility === "commons";
    this.el("profileShareSkills").checked = profile.share_skills === true;
    this.el("profileSharePhoto").checked = Boolean(profile.share_photo && this.photoAssetId);
    this.el("profileAllowInvitations").checked = profile.allow_invitations === true;
    this.el("profilePhotoFile").value = "";
    this.el("profilePhotoUploadFields").hidden = !this.photoUploads;
    this.el("profilePhotoUnavailable").hidden = this.photoUploads;
    this.el("profilePhotoRemove").hidden = !this.photoAssetId;
    this.el("profilePhotoState").textContent = this.photoAssetId
      ? data.profile.share_photo && data.profile.visibility === "commons" ? "Your saved photo is shared with your directory profile." : "Your saved photo is private."
      : "No photo saved. You can use your profile without one.";
    this.clearImages(this.el("profilePhotoPreview"));
    this.el("profilePhotoPreview").append(this.node("span", this.photoAssetId ? "Loading saved photo…" : "No photo saved", "profile-photo-placeholder"));
    this.renderAssessment(profile.assessment);
    this.controls();
  }
  renderAssessment(assessment) {
    const interests = this.el("profileInterests"); interests.replaceChildren();
    for (const category of this.categories) {
      const row = this.node("div", undefined, "profile-interest");
      const label = this.node("label", undefined, "profile-interest-toggle");
      const checkbox = this.node("input"); checkbox.type = "checkbox"; checkbox.value = category.id;
      checkbox.checked = assessment.interests.includes(category.id);
      label.append(checkbox, this.node("span", category.label)); row.append(label);
      const experience = this.node("div", undefined, "profile-experience");
      const levelLabel = this.node("label", "Your experience · private");
      const select = this.node("select"); select.id = "profileExperience-" + category.id;
      select.setAttribute("aria-label", category.label + " experience"); levelLabel.htmlFor = select.id;
      for (const level of this.experienceLevels) {
        const option = this.node("option", level.label); option.value = level.id; select.append(option);
      }
      select.value = assessment.experience[category.id] || "exploring";
      experience.append(levelLabel, select); row.append(experience); interests.append(row);
    }
    const contributions = this.el("profileContributions"); contributions.replaceChildren();
    for (const contribution of this.contributionTypes) {
      const label = this.node("label", undefined, "consent");
      const checkbox = this.node("input"); checkbox.type = "checkbox"; checkbox.value = contribution.id;
      checkbox.checked = assessment.contributions.includes(contribution.id);
      label.append(checkbox, this.node("span", contribution.label)); contributions.append(label);
    }
  }
  draft() {
    const interests = [], experience = {};
    for (const row of this.el("profileInterests").children) {
      const checkbox = row.querySelector("input");
      if (checkbox.checked) { interests.push(checkbox.value); experience[checkbox.value] = row.querySelector("select").value; }
    }
    return {display_name: this.el("profileDisplayName").value, bio: this.el("profileBio").value,
      visibility: this.el("profileVisibility").checked ? "commons" : "private",
      share_skills: this.el("profileShareSkills").checked, share_photo: Boolean(this.photoAssetId && this.el("profileSharePhoto").checked),
      allow_invitations: this.el("profileAllowInvitations").checked,
      assessment: {interests, experience, contributions: Array.from(this.el("profileContributions").querySelectorAll("input:checked"), input => input.value)}};
  }
  save() {
    if (this.conflict || !this.viewer?.account || !Number.isInteger(this.revision)) return;
    const draft = this.draft(), revision = this.revision;
    this.run("profile", async epoch => {
      this.tell("Saving your profile…");
      const data = await this.call("save", {profile: draft, revision}, epoch);
      this.renderProfile(data);
      this.tell(data.profile.visibility === "commons" ? "Profile saved. Your chosen details are listed in the local directory." : "Profile saved privately. Your profile is not listed in the directory.");
      await this.readPhoto(data.profile.photo_asset_id, this.el("profilePhotoPreview"), "Your saved profile photo", epoch);
    });
  }
  async encodedPhoto(file, epoch) {
    if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) throw Object.assign(new Error("Choose a PNG, JPEG, or WebP photo."), {status: 400});
    if (!file.size || file.size > 1048576) throw Object.assign(new Error("Choose a photo no larger than 1 MiB."), {status: 400});
    // The server checks raster dimensions before decoding and returns only a
    // bounded, metadata-free PNG. Never decode or preview the source here.
    if (!this.current(epoch, "profile")) throw new DOMException("Profile view closed.", "AbortError");
    const bytes = new Uint8Array(await file.arrayBuffer());
    if (!this.current(epoch, "profile")) { bytes.fill(0); throw new DOMException("Profile view closed.", "AbortError"); }
    let binary = "";
    for (let offset = 0; offset < bytes.length; offset += 8192) binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
    bytes.fill(0); return btoa(binary);
  }
  uploadPhoto() {
    const file = this.el("profilePhotoFile").files[0];
    if (!file || this.conflict || !this.photoUploads || !this.viewer?.account) return;
    const draft = this.draft(), revision = this.revision;
    this.run("profile", async epoch => {
      this.tell("Preparing your photo for private upload…");
      let encoded = await this.encodedPhoto(file, epoch);
      let data;
      try { data = await this.call("photo/upload", {encoded, revision}, epoch); }
      finally { encoded = ""; }
      draft.share_photo = false;
      this.renderProfile(data, draft);
      this.tell("Photo uploaded privately. Your other edits are retained. To share this photo, choose Share my profile photo and Save profile.");
      await this.readPhoto(data.profile.photo_asset_id, this.el("profilePhotoPreview"), "Your saved profile photo", epoch);
    });
  }
  removePhoto() {
    if (!this.photoAssetId || this.conflict || !confirm("Remove your saved profile photo? It will also be removed from your directory listing. Your other profile details will stay.")) return;
    const draft = this.draft(), revision = this.revision;
    this.run("profile", async epoch => {
      const data = await this.call("photo/remove", {revision}, epoch);
      draft.share_photo = false; this.renderProfile(data, draft);
      this.tell("Photo removed. Your other profile edits are retained.");
    });
  }
  deleteProfile() {
    if (this.conflict || !confirm("Delete your profile and its photo from this server? Your account, inbox, contact code, and messages will stay. You can create a new private profile later.")) return;
    const revision = this.revision;
    this.clearInvitationMemory();
    this.run("profile", async epoch => {
      const data = await this.call("delete", {revision}, epoch); this.renderProfile(data);
      this.tell("Profile and photo deleted. Your account, inbox, and messages are still available.");
    });
  }
  exportProfile() {
    this.run("profile", async epoch => {
      const data = await this.call("export", {}, epoch);
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type: "application/json"}));
      this.downloads.add(url);
      const link = this.node("a"); link.href = url; link.download = "fieldforge-commons-my-profile.json"; link.click();
      setTimeout(() => { URL.revokeObjectURL(url); this.downloads.delete(url); }, 1000);
      this.tell("Exported your saved profile and photo. Unsaved edits are not part of the export.");
    });
  }
  async readPhoto(assetId, target, alt, epoch) {
    if (!assetId) return;
    try {
      const data = await this.call("photo/read", {asset_id: assetId}, epoch);
      if (data.asset_id !== assetId || data.mime_type !== "image/png" || typeof data.encoded !== "string" || data.encoded.length > 1500000 || !/^[A-Za-z0-9+/]+={0,2}$/.test(data.encoded)) return;
      if (!this.current(epoch) || !target.isConnected) return;
      const image = this.node("img"); image.alt = alt; image.width = 96; image.height = 96; image.decoding = "async";
      image.src = "data:image/png;base64," + data.encoded;
      this.clearImages(target); target.append(image);
    } catch (error) {
      if (!this.current(epoch) || error.name === "AbortError") return;
      if (error.status === 401) this.failed(error);
      else if (this.mode === "profile") { this.clearImages(target); target.append(this.node("span", "Photo unavailable. Reopen your profile to try again.", "profile-photo-placeholder")); }
    }
  }
  searchDirectory() {
    if (this.busy) return;
    this.directory.query = this.el("directoryQuery").value.trim();
    this.directory.category = this.el("directoryCategory").value;
    this.loadDirectory(0);
  }
  loadDirectory(offset) {
    this.run("directory", epoch => this.fetchDirectory(offset, epoch));
  }
  async fetchDirectory(offset, epoch) {
    this.tell("Loading shared profiles…"); this.clearImages(this.el("directoryCards"));
    const payload = {query: this.directory.query, category: this.directory.category, offset};
    let data = await this.call("directory", payload, epoch);
    if (data.total > 0 && data.offset >= data.total) {
      data = await this.call("directory", {...payload, offset: Math.floor((data.total - 1) / 12) * 12}, epoch);
    }
    this.directory = {...this.directory, total: data.total, offset: data.offset, limit: data.limit};
    const cards = this.el("directoryCards"), photos = [];
    for (const profile of data.profiles) {
      const {card, photo} = this.directoryCard(profile); cards.append(card);
      if (profile.photo_asset_id) photos.push(this.readPhoto(profile.photo_asset_id, photo, `Profile photo for ${profile.display_name}`, epoch));
    }
    if (!data.profiles.length) {
      const empty = this.node("div", undefined, "directory-empty");
      empty.append(this.node("h3", this.directory.query || this.directory.category ? "No profiles match these filters." : "Room for a first introduction."));
      empty.append(this.node("p", this.directory.query || this.directory.category ? "Try a different search or interest area." : "People appear here when they choose to share a profile. Yours starts private."));
      cards.append(empty);
    }
    this.el("directoryPage").textContent = data.total ? `${data.offset + 1}–${Math.min(data.offset + data.profiles.length, data.total)} of ${data.total} profiles` : "0 shared profiles";
    this.tell(`${data.total} shared ${data.total === 1 ? "profile" : "profiles"}. Use Refresh directory to check for changes.`);
    await Promise.allSettled(photos);
  }
  directoryCard(profile) {
    const card = this.node("article", undefined, "directory-card");
    const heading = this.node("div", undefined, "directory-card-heading");
    const photo = this.node("div", undefined, "directory-avatar");
    photo.append(this.node("span", Array.from(profile.display_name).slice(0, 2).join("").toUpperCase()));
    const identity = this.node("div"); identity.append(this.node("h3", profile.display_name), this.node("p", "@" + profile.username, "directory-username"));
    heading.append(photo, identity); card.append(heading);
    if (profile.bio) card.append(this.node("p", profile.bio, "directory-bio"));
    if (profile.categories.length) {
      const skills = this.node("div", undefined, "directory-skills");
      for (const category of profile.categories) skills.append(this.node("span", `${category.badge} · ${category.label}`, "tag"));
      card.append(skills, this.node("p", "Self-reported interests · qualifications unverified", "hint"));
    }
    if (profile.contributions.length) {
      const labels = {hands_on: "Hands-on help", teach: "Teaching", coordinate: "Coordinating", research: "Research", remote: "Remote help"};
      card.append(this.node("p", "Ways to help: " + profile.contributions.map(value => labels[value] || value).join(", "), "directory-contributions"));
    }
    if (profile.own !== true) {
      const actions = this.node("div", undefined, "directory-card-actions");
      if (profile.accepts_invitations === true) {
        const invite = this.node("button", "Invite to chat"); invite.type = "button";
        invite.addEventListener("click", () => this.openInvitation(profile));
        actions.append(invite);
      }
      const button = this.node("button", "Block @" + profile.username, "secondary"); button.type = "button";
      button.addEventListener("click", () => {
        if (!confirm(`Block @${profile.username}? Their profile and messages will be hidden from your session. You can unblock them from Community rooms.`)) return;
        this.run("directory", async epoch => {
          await this.call("block", {profile_id: profile.profile_id}, epoch);
          await this.fetchDirectory(this.directory.offset, epoch);
          if (this.current(epoch, "directory")) { this.tell("Participant blocked. Their profile is hidden."); await this.refresh(); }
        });
      });
      actions.append(button); card.append(actions);
    } else card.append(this.node("span", "Your shared profile", "hint"));
    return {card, photo};
  }
  clearInvitationMemory() {
    this.invitationRequests.clear(); this.invitationRetry = null;
  }
  nextInvitationRetry() {
    this.invitationRetry = Array.from(this.invitationRequests.values()).reverse().find(attempt => attempt.identity === this.identity && attempt.unconfirmed) || null;
  }
  invitationSignature(target, title) {
    return JSON.stringify([this.identity, target?.profile_id || null, title]);
  }
  invitationSubject() {
    return this.el("directoryInviteSubject").value.replace(/\s+/g, " ").trim();
  }
  closeInvitation() {
    this.inviteEpoch++; this.inviteTarget = null; this.inviteBusy = false;
    this.inviteController?.abort(); this.inviteController = null;
    if (this.el("directoryInviteDialog").open) this.el("directoryInviteDialog").close();
    this.el("directoryInviteForm").reset();
    for (const id of ["directoryInviteName", "directoryInviteUsername", "directoryInviteSender", "directoryInviteStatus"]) this.el(id).textContent = "";
    this.el("directoryInviteGuest").hidden = true;
    this.el("directoryInviteFields").hidden = true;
    this.el("directoryInviteSend").hidden = true;
    this.controls();
  }
  currentInvitation(epoch, identity) {
    return epoch === this.inviteEpoch && identity === this.identity && this.available() && this.mode === "directory" && this.inviteTarget && this.el("directoryInviteDialog").open;
  }
  openInvitation(profile, retry = null) {
    if (!this.available() || this.mode !== "directory" || this.busy) return;
    if (!profile?.profile_id || (!retry && (!profile.accepts_invitations || profile.own))) return;
    this.closeInvitation();
    this.inviteTarget = {profile_id: profile.profile_id, display_name: profile.display_name, username: profile.username};
    this.el("directoryInviteName").textContent = profile.display_name;
    this.el("directoryInviteUsername").textContent = "@" + profile.username;
    const saved = Boolean(this.viewer?.account);
    this.el("directoryInviteSender").textContent = saved ? `Sending as @${this.viewer.username || this.viewer.name}.` : "";
    this.el("directoryInviteGuest").hidden = saved;
    this.el("directoryInviteFields").hidden = !saved;
    this.el("directoryInviteSend").hidden = !saved;
    const previous = retry || Array.from(this.invitationRequests.values()).reverse().find(attempt => attempt.identity === this.identity && attempt.target.profile_id === profile.profile_id && attempt.unconfirmed);
    if (saved && previous?.identity === this.identity) {
      this.el("directoryInviteSubject").value = previous.title;
      this.invitationStatus(previous.closed
        ? "That invitation was already sent and the conversation has since closed. No new invitation was created."
        : "Your earlier invitation could not be confirmed. Send again to check the same request. Nothing is sent until you choose Send invitation.");
    } else this.invitationStatus(saved ? "The recipient chooses whether to accept. No message is sent yet." : "Save your account before inviting someone from the directory.");
    this.el("directoryInviteDialog").showModal(); this.controls();
    if (saved) this.el("directoryInviteSubject").focus();
  }
  invitationStatus(text, error = false) {
    this.el("directoryInviteStatus").textContent = text;
    this.el("directoryInviteStatus").classList.toggle("error", error);
  }
  async sendInvitation() {
    const identity = this.identity, epoch = this.inviteEpoch, title = this.invitationSubject();
    if (!this.currentInvitation(epoch, identity) || !this.viewer?.account || this.inviteBusy || !title || Array.from(title).length > 100) return;
    const signature = this.invitationSignature(this.inviteTarget, title);
    let attempt = this.invitationRequests.get(signature);
    if (attempt?.closed) return;
    if (!attempt) {
      attempt = {identity, target: {...this.inviteTarget}, title, id: crypto.randomUUID(), unconfirmed: true, closed: false};
      this.invitationRequests.set(signature, attempt);
    }
    // Keep the original request even if the view closes after the server saves it.
    // It belongs only to this identity, and is never sent automatically.
    attempt.unconfirmed = true; this.invitationRetry = attempt;
    this.inviteBusy = true; const controller = new AbortController(); this.inviteController = controller;
    this.invitationStatus("Sending invitation…"); this.controls();
    try {
      const result = await this.request("profile/invite", {profile_id: attempt.target.profile_id, title, request_id: attempt.id}, controller.signal);
      if (!this.currentInvitation(epoch, identity)) return;
      attempt.unconfirmed = false;
      if (this.invitationRetry === attempt) this.nextInvitationRetry();
      if (result.closed) {
        attempt.closed = true;
        this.invitationStatus("That invitation was already sent and the conversation has since closed. No new invitation was created.");
        return;
      }
      this.invitationRequests.delete(signature);
      this.close();
      this.notice(result.duplicate ? "That invitation was already sent. Opening the existing conversation." : "Invitation sent. The recipient must accept before reading messages.");
      this.openConversation(result.thread);
    } catch (error) {
      if (!this.currentInvitation(epoch, identity) || error.name === "AbortError") return;
      if (!error.status || error.status === 401 || error.status >= 500) {
        this.failed(error);
        if (this.identity === identity && this.joined) this.notice("The invitation could not be confirmed. Chat is paused and the dialog was cleared. Resume chat, open Member directory, and choose Review pending invitation to retry the same request.", true);
      } else {
        attempt.unconfirmed = false; this.invitationRequests.delete(signature);
        if (this.invitationRetry === attempt) this.nextInvitationRetry();
        this.invitationStatus(error.message || "This invitation could not be sent.", true);
      }
    } finally {
      if (this.currentInvitation(epoch, identity)) { this.inviteBusy = false; this.inviteController = null; this.controls(); }
    }
  }
};
