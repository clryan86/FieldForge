"""Export the existing FieldForge portal as an explicitly static owner preview.

Run from a FieldForge checkout, or supply --source-root. No Python application
server, account database, credentials, or map data is copied to the website.
"""
from __future__ import annotations

import argparse
import html
import re
import shutil
from pathlib import Path

from build_offline_desk import export_offline

ROOT = Path(__file__).resolve().parents[1]
FAVICON = '<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 32 32%22%3E%3Crect width=%2232%22 height=%2232%22 rx=%227%22 fill=%22%23176445%22/%3E%3Cpath d=%22M10 7h15v5H15v4h8v5h-8v8h-5z%22 fill=%22white%22/%3E%3C/svg%3E">'
STYLE = '''
.preview-banner{background:#173d2c;color:#fff;padding:1.2rem 1.4rem;border-radius:10px;margin:0 0 1.6rem}
.preview-banner h2{font-size:1.25rem;margin-bottom:.45rem}.preview-banner p{max-width:850px;margin-bottom:.7rem}
.preview-banner a{color:#fff;text-underline-offset:3px}.preview-banner .actions a{background:#fff;color:#173d2c;border-color:#fff}
.preview-state{background:#fff5df;border:1px solid #e5c88f;color:#725021;border-radius:7px;padding:.8rem;margin:.8rem 0;font-size:.94rem}
.source-disabled{opacity:.65}.small,.hint,.badge,.online-only,details,.pack p,.map-card p,.eyebrow,.bottom-note,footer{font-size:max(.875rem,14px)}
.preview-gallery{display:grid;gap:1rem}.preview-gallery details{padding:1rem;background:#fff;border:1px solid #d8e1d9;border-radius:10px}
.preview-gallery summary{font-size:1.1rem}.preview-gallery img{display:block;width:100%;height:auto;border:1px solid #d8e1d9;margin-top:1rem}
.preview-gallery figure{margin:0}.preview-gallery figcaption{padding:.7rem 0;font-size:.95rem;color:#54685e}
.preview-gallery .actions{margin-bottom:1rem}.status-table{width:100%;border-collapse:collapse;text-align:left;margin-top:1rem}
.status-table th,.status-table td{padding:.8rem;border-bottom:1px solid #d8e1d9;vertical-align:top;overflow-wrap:anywhere}
@media(max-width:620px){.preview-banner{padding:1rem}.status-table{font-size:.875rem}.status-table th,.status-table td{padding:.5rem}.preview-gallery details{padding:.7rem}}
'''
SCRIPT = '''"use strict";
(() => {
  const id = value => document.getElementById(value);
  let enabled = false;
  function setConnection(value) {
    enabled = value;
    document.documentElement.dataset.sourcesEnabled = String(value);
    id("connectionBadge").textContent = value ? "Source links enabled" : "Source links paused";
    id("connectionBadge").classList.toggle("offline", !value);
    id("connect").disabled = value;
    id("disconnect").disabled = !value;
    for (const link of document.querySelectorAll("[data-source-link]")) {
      link.setAttribute("aria-disabled", String(!value));
      link.classList.toggle("source-disabled", !value);
    }
    id("connectionStatus").textContent = value
      ? "Source links are enabled. A provider is contacted only when you open its link. Address search, route calculation and hosted map downloads are not connected in this preview."
      : "Source links are paused. The website itself is online; this control does not turn off your device’s internet.";
  }
  id("connect").addEventListener("click", () => {
    if (!id("consent").checked) {
      id("connectionStatus").textContent = "Check the consent box before enabling external source links.";
      id("consent").focus(); return;
    }
    if (window.confirm("Enable online source links?\\n\\nOpening a source link will contact its provider. Large files may begin downloading when you select a direct download. This website is already online.\\n\\nAddress search, routes and live chat are not hosted in this preview.")) setConnection(true);
  });
  id("disconnect").addEventListener("click", () => setConnection(false));
  id("consent").addEventListener("change", () => { if (!id("consent").checked) setConnection(false); });
  for (const eventName of ["click", "auxclick"]) {
    document.addEventListener(eventName, event => {
      const link = event.target.closest?.("[data-source-link]");
      if (!link || enabled) return;
      event.preventDefault();
      id("connectionStatus").textContent = "Enable source links first to open an external provider.";
      id("connectionTitle").scrollIntoView({block:"center"});
      id("connect").focus();
    });
  }
  window.addEventListener("offline", () => setConnection(false));
  id("previewSkills").addEventListener("click", () => {
    const selected = [...document.querySelectorAll('#skillsPreviewForm input[name="skill"]:checked')].map(input => input.value);
    id("skillsPreview").textContent = selected.length
      ? (id("listSkillPreview").checked ? "Self-reported labels: " + selected.join(", ") : "Private preview: " + selected.length + " skills selected.") + " Nothing is sent or saved."
      : "Choose at least one skill. Nothing is sent or saved.";
  });
  const filter = id("regionalFilter");
  filter.addEventListener("input", () => {
    const query = filter.value.trim().toLocaleLowerCase();
    let count = 0;
    for (const row of document.querySelectorAll("#usSourceLinks li")) {
      row.hidden = !row.textContent.toLocaleLowerCase().includes(query);
      if (!row.hidden) count++;
    }
    id("regionalCount").textContent = count + " source regions match. These are PBF source files, not MBTiles.";
  });
  setConnection(false);
})();
'''

def replace_once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError(f"Portal structure changed; review export anchor: {old[:100]}")
    return source.replace(old, new, 1)

def export(source_root: Path, output: Path, revision: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Supply the full source commit SHA")
    portal = (source_root / "fieldforge/online/portal.html").read_text(encoding="utf-8")
    # Fail closed instead of shipping the live application's API handlers.
    if len(re.findall(r"<script\b", portal)) != 1:
        raise ValueError("Expected one portal script; review exporter before publishing")
    portal = re.sub(r"<script\b[^>]*>.*?</script>", '<script src="preview.js" defer></script>', portal, flags=re.S)
    if "fetch(" in portal or "/api/v1/" in portal:
        raise ValueError("Unexpected server API dependency in preview")
    base = f"https://github.com/clryan86/FieldForge/tree/{revision}"
    portal = replace_once(portal, "</head>", FAVICON + '<meta name="description" content="Explore the current FieldForge download portal and see the Commons chat, account and owner-console development screens."><link rel="stylesheet" href="preview.css"></head>')
    portal = replace_once(portal, "<main>", '''<main>
    <section class="preview-banner" aria-labelledby="previewTitle"><h2 id="previewTitle">Private development preview</h2>
    <p>The preparation desk works in your browser. Map hosting, online address lookup, routing, live accounts and messaging are not connected here yet. The sections below show the rest of the portal and its current progress.</p>
    <div class="actions"><a class="button" href="commons.html">See chat &amp; owner screens</a><a class="button" href="#mapAcquisitionTitle">Explore map sources</a></div></section>''')
    portal = replace_once(portal, 'Send my entered searches and route coordinates to this portal and its configured providers.', 'Allow me to open external map and resource providers from this preview.')
    portal = replace_once(portal, 'This page is already open in your browser. Connect asks permission before enabling its online services. Disconnect stops those services; it does not switch off your device\'s internet. Download what you need before leaving.', 'This website is already online. Connect asks before enabling external source links; Go offline pauses those links. These controls do not switch your device’s internet on or off. This preview does not run background provider requests.')
    portal = replace_once(portal, '<div class="layout">', '<p class="preview-state">Address lookup and route planning are shown below for layout review. Their online providers are not connected on this website.</p><div class="layout">')
    # Preserve form layout while making every server-backed control inert.
    portal = re.sub(r'(<input id="(?:start|end)(?:Latitude|Longitude)"[^>]*)(>)', r'\1 disabled\2', portal)
    for form_id in ("searchForm", "routeForm"):
        pattern = rf'(<form id="{form_id}">)(.*?)(</form>)'
        portal = re.sub(pattern, r'\1<fieldset disabled>\2</fieldset>\3', portal, flags=re.S)
    portal = replace_once(portal, 'Connect to see the published map catalog.', 'No map files are hosted in this preview. The source directory below links to external providers. All-world MBTiles have not been acquired.')
    portal = replace_once(portal, '<ul id="usSourceLinks">', '<label for="regionalFilter">Find a U.S. source region</label><input id="regionalFilter" type="search" placeholder="State or territory" autocomplete="off"><p id="regionalCount" role="status">53 source regions. PBF source files, not MBTiles.</p><ul id="usSourceLinks">')
    portal = replace_once(portal, '<span class="badge">Preview · membership not active</span>', '<span class="badge">Local development · view screens</span>')
    portal = replace_once(portal, '<button type="button" disabled aria-disabled="true">Member sign-in unavailable</button>', '<a class="button" href="commons.html#accounts">View account progress</a>')
    portal = replace_once(portal, 'Email registration, selected social sign-in providers, profile photos, consent controls and moderation are not connected yet. Choose and configure identity and email services before opening membership.', 'Local accounts, private messages, profiles and member controls are in development. Email and social sign-in are not connected. You can inspect the existing screens in the preview gallery; this website does not accept account registration.')
    portal = replace_once(portal, '<button type="button" disabled aria-disabled="true">Admin console unavailable</button>', '<a class="button" href="commons.html#owner">View owner console</a>')
    portal = replace_once(portal, 'The owner console will manage membership, reports and published resources. It needs server-side authentication, multi-factor protection and recovery setup before it can be enabled.', 'The local owner console includes reports, participant controls and announcements, with password and authenticator protection. CLRYAN86 is the reserved sole-owner username; setup is still performed locally.')
    portal = replace_once(portal, 'No account, profile photo, public directory, chat or encrypted messaging is active here. Any future messaging needs a reviewed implementation; FieldForge will not present homemade encryption as secure.', 'Live messaging and account services are not active on this website. The local application supports saved and open-once messages. It is not end-to-end encrypted and cannot prevent screenshots.')
    # External providers remain the original portal's sources. No mirroring or
    # proxying of their files and no implied ownership of world map collections.
    portal = portal.replace('<a href="https://', '<a data-source-link href="https://')
    portal = replace_once(portal, '</footer>', f' <a href="commons.html">Development progress</a> · <a href="{base}" target="_blank" rel="noopener noreferrer">Source snapshot {revision[:7]}</a></footer>')
    # Add actual browser-local tools without changing the desktop server portal.
    assets = Path(__file__).resolve().parent / "portal_preview"
    portal = replace_once(portal, '<section class="preview-banner"', (assets / "desk.html").read_text(encoding="utf-8") + '<section class="preview-banner"')
    portal = replace_once(portal, '</head>', '<link rel="stylesheet" href="desk.css"><link rel="stylesheet" href="route-explorer.css"><link rel="stylesheet" href="image-viewer.css"><link rel="stylesheet" href="places.css"><link rel="stylesheet" href="vector-viewer.css"><script type="module" src="desk.mjs"></script></head>')
    css = re.search(r'<style>(.*?)</style>', portal, flags=re.S).group(1)
    screens = [
        ("rooms", "Community rooms", "commons-chat-preview.png", "Public rooms organized around practical skills, with pause, export, block and report controls."),
        ("private", "Private inbox", "commons-private-preview.png", "Direct and group conversations, invitations, saved messages and open-once messages. Screenshots cannot be prevented; messages are not end-to-end encrypted."),
        ("accounts", "Local accounts", "commons-account-preview.png", "Local username/password accounts, stable contact codes and recovery. Email and social sign-in are not configured."),
        ("owner", "Owner console & announcements", "commons-owner-announcements.png", "Sole-owner console for reports, participant access and member announcements. Owner verification uses a password and authenticator code."),
        ("search", "Saved-message search", "commons-saved-search.png", "Search available saved conversation messages. Open-once bodies are excluded from message search."),
    ]
    gallery = []
    output.mkdir(parents=True, exist_ok=True)
    (output / "images").mkdir(exist_ok=True)
    for key, title, name, description in screens:
        shutil.copyfile(source_root / "docs/images" / name, output / "images" / name)
        gallery.append(f'<details id="{key}"'+(' open' if key == 'rooms' else '')+f'><summary>{html.escape(title)}</summary><p>{html.escape(description)}</p><figure><a href="images/{name}" target="_blank" rel="noopener"><img src="images/{name}" alt="FieldForge {html.escape(title)} from local development tests, containing test accounts and messages" loading="lazy"></a><figcaption>Screenshot from local development tests, not a live conversation. Select the image to view full size.</figcaption></figure></details>')
    commons = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>FieldForge Commons · Development progress</title><meta name="description" content="See the actual Commons chat, private inbox, account and owner-console development screens.">{FAVICON}<style>{css}</style><link rel="stylesheet" href="preview.css"></head><body>
    <header class="topbar"><div class="bar-inner"><a class="brand" href="index.html"><span class="brandmark" aria-hidden="true">F</span>FieldForge / Commons</a><a href="index.html">Download portal</a></div></header>
    <main><section class="hero"><div><p class="eyebrow">Development progress</p><h1>Commons is taking shape.</h1><p class="muted">Inspect the real application screens below. These captures use test participants, not a live community.</p></div></section>
    <section class="preview-banner"><h2>What you can use here</h2><p>This site hosts the portal preview and screen gallery. Rooms, private messages, saved accounts and the owner console currently run on the local FieldForge preview server. There is no live chat or sign-in on this website.</p><div class="actions"><a class="button" href="{base}/docs/COMMONS_CHAT_PREVIEW.md" target="_blank" rel="noopener noreferrer">Local preview instructions</a><a class="button" href="{base}/docs/COMMONS_OWNER.md" target="_blank" rel="noopener noreferrer">Owner setup instructions</a></div></section>
    <nav class="portal-nav" aria-label="Preview screens">{''.join(f'<a href="#{key}">{title}</a>' for key,title,_,_ in screens)}</nav>
    <section class="preview-gallery" aria-label="Development screenshots">{''.join(gallery)}</section>
    <section class="card maps-section"><h2>Current status</h2><table class="status-table"><thead><tr><th scope="col">Area</th><th scope="col">Available now</th><th scope="col">Still to connect</th></tr></thead><tbody>
    <tr><th scope="row">Website</th><td>Map source planner, download estimates, saved plans, local GPX and map-image inspection, coordinate CSV export and these screens</td><td>Hosted application services and a public community launch</td></tr>
    <tr><th scope="row">Maps &amp; routes</th><td>Links to regional PBF sources, NOAA charts and paid dataset providers</td><td>Hosted map files, address provider and route provider; world MBTiles collection not acquired</td></tr>
    <tr><th scope="row">Commons</th><td>Local rooms, inbox, accounts, profiles, search and owner controls</td><td>Online account services, email/social providers and production operations</td></tr>
    <tr><th scope="row">Library &amp; tiers</th><td>Subject areas and draft plans</td><td>Published knowledge packages, final prices and billing</td></tr>
    </tbody></table><p class="bottom-note">Open-once messages do not guarantee screenshot protection or deletion of copies. End-to-end encryption is not implemented.</p></section></main>
    <footer>FieldForge · <a href="index.html">Return to the portal</a> · <a href="{base}" target="_blank" rel="noopener noreferrer">Source snapshot {revision[:7]}</a></footer>
    <script>function revealScreen(){{const panel=document.getElementById(location.hash.slice(1));if(panel instanceof HTMLDetailsElement)panel.open=true;}}window.addEventListener('hashchange',revealScreen);revealScreen();</script></body></html>'''
    (output / "index.html").write_text(portal, encoding="utf-8")
    (output / "commons.html").write_text(commons, encoding="utf-8")
    (output / "preview.css").write_text(STYLE, encoding="utf-8")
    (output / "preview.js").write_text(SCRIPT, encoding="utf-8")
    for name in ("desk.css", "desk.mjs", "desk-core.mjs", "route-explorer.css", "route-explorer.mjs", "image-core.mjs", "image-viewer.mjs", "image-viewer.css", "places-core.mjs", "places.mjs", "places.css", "field-sheet-core.mjs", "field-sheet.mjs", "vector-core.mjs", "vector-viewer.mjs", "vector-viewer.css"):
        shutil.copyfile(assets / name, output / name)
    offline = export_offline(assets, output, (source_root / "fieldforge/online/portal.html").read_text(encoding="utf-8"), revision, FAVICON)
    print(f"Offline desk: {offline['bytes']:,} bytes, edition {offline['edition_id']}")
    print(f"Exported portal and Commons gallery from {revision} to {output}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    export(args.source_root, args.output, args.revision)
