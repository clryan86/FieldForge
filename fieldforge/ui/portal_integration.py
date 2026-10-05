"""Connect explicit portal selections to the existing local map and place tools."""

from __future__ import annotations

from pathlib import Path

from fieldforge.navigation.places import coordinate_text


def place_fields(result: dict) -> dict:
    """Keep the complete source label/attribution in notes if the name is shortened."""
    from fieldforge.online.models import validate_search_result

    result = validate_search_result(result)
    notes = (
        f"Address lookup: {result['label']}\n"
        f"Source: {result['source']}\n"
        f"Attribution: {result['attribution']}\n"
        f"License: {result['license']}\n"
        f"Looked up: {result['retrieved_at']}\n"
        "Selected from online address results. Confirm the intended location."
    )
    if len(notes) > 4000:
        raise ValueError("This result's source notes exceed the saved-place limit.")
    return {
        "name": result["label"][:200],
        "latitude": result["latitude"],
        "longitude": result["longitude"],
        "kind": "address",
        "notes": notes,
    }


def install_online_maps(notebook, database, places, maps, gps_workspace, menu_bar):
    """Install a disconnected portal tab; opening it never connects to a service."""
    from fieldforge.ui.online_maps import OnlineMapsTab
    from fieldforge.ui.places import PlaceEditor

    def open_map(path):
        path = Path(path)
        if path.suffix.lower() == ".mbtiles":
            notebook.select(maps)
            maps.open_path(path)
        elif path.suffix.lower() == ".ffmap":
            window = maps.open_prepared_region()
            if window is None or window._disposed:
                raise ValueError("The prepared regional map window is unavailable.")
            if window.busy or window._closing:
                raise ValueError("Finish or cancel the current prepared regional map task before opening another map.")
            notebook.select(maps)
            if window.open_path(path) is False:
                raise ValueError("The prepared regional map could not be opened while its viewer is busy or closing.")
        else:
            frame = gps_workspace.open().live_map_frame.open_image_reference()
            if frame is None:
                raise ValueError("The image map window is unavailable.")
            # This callback follows the user's explicit Open action on a portal
            # download. Reflect that selection in the image viewer's trust toggle.
            frame.permission.set(True)
            frame.open_path(path)

    def center(latitude, longitude):
        if maps.pack_info is None:
            raise ValueError("Open a downloaded or local map before centering on this address.")
        maps.latitude.set(coordinate_text(latitude))
        maps.longitude.set(coordinate_text(longitude))
        notebook.select(maps)
        maps.go()

    def use_place(result):
        if places.store is None:
            raise ValueError("The saved-places database is unavailable.")
        if places.dialog is not None:
            places.dialog.lift()
            raise ValueError("Finish the open place editor before filling another address.")
        fields = place_fields(result)
        notebook.select(places)
        places.dialog = PlaceEditor(places, places.store, initial=fields, finished=places._finished)
        places._buttons()

    def show_route(route):
        maps.show_route(route)
        notebook.select(maps)

    panel = OnlineMapsTab(
        notebook, database, on_open_map=open_map, on_center=center,
        on_use_place=use_place, on_show_route=show_route,
    )
    notebook.add(panel, text="Online Maps")
    navigation = notebook.winfo_toplevel().nametowidget(menu_bar.entrycget("Navigation", "menu"))
    navigation.add_separator()
    navigation.add_command(label="Online maps, addresses & routes…", command=lambda: notebook.select(panel))
    return panel
