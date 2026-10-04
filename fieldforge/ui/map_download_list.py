"""Review a portable map list before starting an explicit batch download."""

import tkinter as tk
from tkinter import ttk

from fieldforge_gps.tk_cleanup import TkCleanupMixin


class MapDownloadListWindow(TkCleanupMixin, tk.Toplevel):
    def __init__(self, owner, format_size):
        super().__init__(owner)
        self.owner = owner
        self.format_size = format_size
        self.title("FieldForge · Map download list")
        self.geometry("820x580")
        self.minsize(720, 500)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.info = tk.StringVar()
        ttk.Label(self, text="Review maps before downloading", font=("TkDefaultFont", 17, "bold"),
                  padding=(16, 12)).grid(row=0, column=0, sticky="w")
        ttk.Label(self, textvariable=self.info, wraplength=680, padding=(16, 0, 16, 10)).grid(row=1, column=0, sticky="ew")
        frame = ttk.Frame(self)
        frame.grid(row=2, column=0, sticky="nsew", padx=16)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(frame, columns=("title", "filename", "size", "format"), show="headings", selectmode="extended", height=8)
        for name, label, width in (("title", "Map", 280), ("filename", "Filename", 230), ("size", "File size", 120), ("format", "Format", 100)):
            self.tree.heading(name, text=label)
            self.tree.column(name, width=width, minwidth=75)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(frame, command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self.update_state())
        actions = ttk.Frame(self, padding=(16, 10))
        actions.grid(row=3, column=0, sticky="ew")
        self.remove_button = ttk.Button(actions, text="Remove selected", command=self.remove)
        self.clear_button = ttk.Button(actions, text="Clear list", command=owner.clear_download_list)
        self.import_button = ttk.Button(actions, text="Import list…", command=owner.import_download_list)
        self.save_button = ttk.Button(actions, text="Save list…", command=owner.export_download_list)
        self.copy_portal_button = ttk.Button(actions, text="Copy required portal", command=owner.copy_download_list_portal)
        for button in (self.remove_button, self.clear_button, self.import_button, self.save_button, self.copy_portal_button):
            button.pack(side="left", padx=(0, 8))
        options = ttk.Frame(self, padding=(16, 0, 16, 8))
        options.grid(row=4, column=0, sticky="ew")
        self.resume_button = ttk.Checkbutton(options, text="Keep partial downloads for retry", variable=owner.keep_partial_maps)
        self.resume_button.pack(side="left")
        self.discard_button = ttk.Button(options, text="Discard partial files…", command=owner.discard_list_partials)
        self.discard_button.pack(side="left", padx=16)
        transfer = ttk.Frame(self, padding=(16, 0, 16, 6))
        transfer.grid(row=5, column=0, sticky="ew")
        self.download_button = ttk.Button(transfer, text="Download list", command=owner.download_list)
        self.download_button.pack(side="left")
        self.stop_button = ttk.Button(transfer, text="Stop downloads", command=owner.cancel_task)
        self.stop_button.pack(side="left", padx=8)
        ttk.Label(transfer, textvariable=owner.transfer_info).pack(side="left", padx=8)
        ttk.Label(self, textvariable=owner.status, wraplength=680, padding=(16, 6)).grid(row=6, column=0, sticky="ew")
        ttk.Label(self, text="Save this list to reuse it after closing FieldForge. Saving a list does not download its maps.\n"
                  "Retry checks completed maps and kept partial bytes. Servers without range support restart the current file.",
                  wraplength=680, padding=(16, 6, 16, 12)).grid(row=7, column=0, sticky="ew")
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.render()

    def render(self):
        document = self.owner._download_list
        maps = document["maps"] if document else []
        self.tree.delete(*self.tree.get_children())
        for item in maps:
            self.tree.insert("", "end", iid=item["id"], values=(item["title"], item["filename"], self.format_size(item["bytes"]), item["format"]))
        self.info.set(f"{len(maps)} maps · {self.format_size(document['total_bytes'] if document else 0)} total file size\n"
                      + ("Required portal: " + document["portal"] if document else "Add a map from the loaded catalog or import a saved list.")
                      + "\nAlready downloaded matching maps are verified and reused. Lists never switch portals automatically.")
        self.update_state()

    def update_state(self):
        owner = self.owner
        if owner is None or owner._disposed:
            return
        ready = owner._download_list and owner._download_list["maps"]
        idle = not owner.busy and not owner._choosing_file
        self.remove_button.configure(state="normal" if idle and self.tree.selection() else "disabled")
        for button in (self.clear_button, self.save_button):
            button.configure(state="normal" if idle and ready else "disabled")
        self.import_button.configure(state="normal" if idle else "disabled")
        self.resume_button.configure(state="normal" if idle else "disabled")
        self.discard_button.configure(state="normal" if idle and ready and owner.library is not None else "disabled")
        self.copy_portal_button.configure(state="normal" if owner._download_list else "disabled")
        self.download_button.configure(state="normal" if idle and ready and owner.library is not None
                                       and owner._available("catalog")
                                       and owner._connection_url == owner._download_list["portal"] else "disabled")
        self.stop_button.configure(state="normal" if owner.busy and owner._operation == "download_list" else "disabled")

    def remove(self):
        if self.owner.busy:
            return
        selected = set(self.tree.selection())
        self.owner.remove_from_download_list(selected)

    def close(self):
        if self.owner._choosing_file or (self.owner.busy and self.owner._operation in {"save_download_list", "import_download_list", "discard_partials"}):
            self.owner.status.set("Finish the current list file operation before closing this window.")
            return
        self.destroy()

    def destroy(self):
        if self.__dict__.get("_tk_destroyed", False):
            return
        if self.owner is not None:
            self.owner._download_list_window = None
        super().destroy()
