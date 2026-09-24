/*
 * The merged library browser.
 *
 * With no source filter set the daemon queries every connected service and
 * merges the answers, so artists and albums from Navidrome and Kodi appear in
 * one list; each row carries a badge saying where it came from.
 */

import QtQuick
import QtQuick.Layouts

import org.kde.plasma.components as PlasmaComponents
import org.kde.plasma.extras as PlasmaExtras
import org.kde.plasma.plasmoid
import org.kde.kirigami as Kirigami

import "Formatting.js" as Fmt

Item {
    id: pane

    readonly property var client: root.client

    /* Navigation history; the last entry is what is on screen. */
    property var stack: [{ mode: "albums", title: "" }]
    readonly property var here: stack[stack.length - 1]
    readonly property bool atRoot: stack.length === 1

    /* Which service to browse; empty means all of them at once. */
    property string sourceFilter: ""

    property var entries: []
    property bool loading: false
    property string loadError: ""

    /* True when the current list is made of tracks we can enqueue wholesale. */
    readonly property bool listIsTracks:
        here.mode === "albumTracks" || here.mode === "playlistTracks"

    function push(entry) {
        stack = stack.concat([entry]);
        load();
    }

    function pop() {
        if (stack.length > 1) {
            stack = stack.slice(0, stack.length - 1);
            load();
        }
    }

    function replaceRoot(entry) {
        stack = [entry];
        load();
    }

    function _params(extra) {
        const params = extra || {};
        if (sourceFilter) {
            params.source = sourceFilter;
        }
        return params;
    }

    function _receive(kind, key) {
        return function (result, error) {
            pane.loading = false;
            if (error) {
                pane.loadError = error;
                pane.entries = [];
                return;
            }
            pane.loadError = "";
            const items = (result && result[key]) || [];
            pane.entries = items.map(item => ({ kind: kind, item: item }));
        };
    }

    function load() {
        if (!client.linked) {
            entries = [];
            loadError = "";
            return;
        }
        loading = true;
        loadError = "";
        const at = here;

        switch (at.mode) {
        case "artists":
            client.call("library.artists", _params(), _receive("artist", "artists"));
            break;
        case "albums":
            client.call("library.albums",
                        _params({ sort: Plasmoid.configuration.albumSort,
                                  limit: 300 }),
                        _receive("album", "albums"));
            break;
        case "genres":
            client.call("library.genres", _params(), function (result, error) {
                pane.loading = false;
                pane.loadError = error || "";
                const names = (result && result.genres) || [];
                pane.entries = names.map(name => ({ kind: "genre",
                                                    item: { name: name } }));
            });
            break;
        case "playlists":
            client.call("library.playlists", _params(),
                        _receive("playlist", "playlists"));
            break;
        case "artistAlbums":
            client.call("library.artistAlbums",
                        { id: at.id, source: at.source },
                        _receive("album", "albums"));
            break;
        case "genreAlbums":
            client.call("library.genreAlbums", _params({ genre: at.genre }),
                        _receive("album", "albums"));
            break;
        case "albumTracks":
            client.call("library.albumTracks", { id: at.id, source: at.source },
                        _receive("track", "tracks"));
            break;
        case "playlistTracks":
            client.call("library.playlistTracks", { id: at.id, source: at.source },
                        _receive("track", "tracks"));
            break;
        case "search":
            client.call("library.search", _params({ query: at.query }),
                        function (result, error) {
                pane.loading = false;
                if (error) {
                    pane.loadError = error;
                    pane.entries = [];
                    return;
                }
                pane.loadError = "";
                const built = [];
                const groups = [
                    ["artist", "artists", i18n("Artists")],
                    ["album", "albums", i18n("Albums")],
                    ["track", "tracks", i18n("Tracks")],
                ];
                for (const [kind, key, label] of groups) {
                    const items = (result && result[key]) || [];
                    if (items.length === 0) {
                        continue;
                    }
                    built.push({ kind: "header", item: { name: label } });
                    for (const item of items) {
                        built.push({ kind: kind, item: item });
                    }
                }
                pane.entries = built;
            });
            break;
        }
    }

    /* Turn a row into something the daemon can enqueue. */
    function specFor(entry) {
        const item = entry.item;
        switch (entry.kind) {
        case "album":    return { albumId: item.id, source: item.source };
        case "artist":   return { artistId: item.id, source: item.source };
        case "playlist": return { playlistId: item.id, source: item.source };
        case "track":    return { tracks: [item] };
        }
        return null;
    }

    function activate(entry) {
        const item = entry.item;
        switch (entry.kind) {
        case "artist":
            push({ mode: "artistAlbums", id: item.id, source: item.source,
                   title: item.name });
            break;
        case "album":
            push({ mode: "albumTracks", id: item.id, source: item.source,
                   title: item.name });
            break;
        case "genre":
            push({ mode: "genreAlbums", genre: item.name, title: item.name });
            break;
        case "playlist":
            push({ mode: "playlistTracks", id: item.id, source: item.source,
                   title: item.name });
            break;
        case "track":
            client.enqueue({ tracks: [item] }, "replace", true);
            break;
        }
    }

    Component.onCompleted: load()

    Connections {
        target: client
        // Reload once a service connects, disconnects, or the daemon restarts.
        function onSourcesChanged() { pane.load(); }
        function onReloaded() { pane.load(); }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: Kirigami.Units.smallSpacing

        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            PlasmaComponents.ToolButton {
                icon.name: "go-previous"
                display: PlasmaComponents.AbstractButton.IconOnly
                visible: !pane.atRoot
                text: i18n("Back")
                onClicked: pane.pop()
            }

            PlasmaExtras.SearchField {
                id: searchField
                Layout.fillWidth: true
                placeholderText: i18n("Search the library…")

                onTextChanged: searchDebounce.restart()

                Timer {
                    id: searchDebounce
                    interval: 350
                    onTriggered: {
                        const query = searchField.text.trim();
                        if (query.length === 0) {
                            if (pane.here.mode === "search") {
                                pane.pop();
                            }
                            return;
                        }
                        if (pane.here.mode === "search") {
                            pane.stack = pane.stack.slice(0, pane.stack.length - 1)
                                             .concat([{ mode: "search", query: query,
                                                        title: query }]);
                            pane.load();
                        } else {
                            pane.push({ mode: "search", query: query,
                                        title: query });
                        }
                    }
                }
            }

            PlasmaComponents.ComboBox {
                id: sourceBox
                Layout.maximumWidth: Kirigami.Units.gridUnit * 8
                visible: client.sources.length > 1
                textRole: "name"
                model: [{ id: "", name: i18n("All libraries") }].concat(
                           client.connectedSources)

                onActivated: index => {
                    pane.sourceFilter = model[index].id || "";
                    // Ids are per-service, so anything deeper is now meaningless.
                    pane.replaceRoot({ mode: pane.atRoot ? pane.here.mode : "albums",
                                       title: "" });
                }
            }
        }

        // Top-level sections; hidden once you have drilled into something.
        RowLayout {
            Layout.fillWidth: true
            visible: pane.atRoot
            spacing: 0

            Repeater {
                model: [
                    { mode: "albums",    label: i18n("Albums"),    icon: "view-media-album-cover" },
                    { mode: "artists",   label: i18n("Artists"),   icon: "view-media-artist" },
                    { mode: "genres",    label: i18n("Genres"),    icon: "view-media-genre" },
                    { mode: "playlists", label: i18n("Playlists"), icon: "view-media-playlist" },
                ]

                PlasmaComponents.TabButton {
                    required property var modelData
                    Layout.fillWidth: true
                    icon.name: modelData.icon
                    text: modelData.label
                    checked: pane.here.mode === modelData.mode
                    onClicked: pane.replaceRoot({ mode: modelData.mode, title: "" })
                }
            }
        }

        // What we drilled into, plus bulk actions when it is a track list.
        RowLayout {
            Layout.fillWidth: true
            visible: !pane.atRoot
            spacing: Kirigami.Units.smallSpacing

            PlasmaExtras.Heading {
                Layout.fillWidth: true
                Layout.leftMargin: Kirigami.Units.smallSpacing
                level: 5
                elide: Text.ElideRight
                text: pane.here.title || ""
            }

            PlasmaComponents.ToolButton {
                icon.name: "media-playback-start"
                display: PlasmaComponents.AbstractButton.IconOnly
                visible: pane.listIsTracks && pane.entries.length > 0
                text: i18n("Play All")
                onClicked: client.enqueue(
                    { tracks: pane.entries.map(e => e.item) }, "replace", true)

                PlasmaComponents.ToolTip.text: text
                PlasmaComponents.ToolTip.visible: hovered
                PlasmaComponents.ToolTip.delay: Kirigami.Units.toolTipDelay
            }

            PlasmaComponents.ToolButton {
                icon.name: "list-add"
                display: PlasmaComponents.AbstractButton.IconOnly
                visible: pane.listIsTracks && pane.entries.length > 0
                text: i18n("Add All to Queue")
                onClicked: client.enqueue(
                    { tracks: pane.entries.map(e => e.item) }, "append", false)

                PlasmaComponents.ToolTip.text: text
                PlasmaComponents.ToolTip.visible: hovered
                PlasmaComponents.ToolTip.delay: Kirigami.Units.toolTipDelay
            }
        }

        PlasmaComponents.ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true

            ListView {
                id: list
                model: pane.entries
                clip: true
                reuseItems: true

                delegate: LibraryRow {
                    width: list.width
                    entry: modelData
                    onActivated: pane.activate(modelData)
                    onPlayRequested: {
                        const spec = pane.specFor(modelData);
                        if (spec) {
                            client.enqueue(spec, "replace", true);
                        }
                    }
                    onQueueRequested: {
                        const spec = pane.specFor(modelData);
                        if (spec) {
                            client.enqueue(spec, "append", false);
                        }
                    }
                }
            }
        }
    }

    PlasmaComponents.BusyIndicator {
        anchors.centerIn: parent
        running: pane.loading && pane.entries.length === 0
        visible: running
    }

    PlasmaExtras.PlaceholderMessage {
        anchors.centerIn: parent
        width: parent.width - Kirigami.Units.gridUnit * 4
        visible: !pane.loading && pane.entries.length === 0 && client.online
        iconName: pane.loadError ? "dialog-error" : "view-media-album-cover"
        text: pane.loadError ? i18n("Could not read the library")
            : !client.linked ? i18n("No music server is connected")
            : pane.here.mode === "search" ? i18n("Nothing matched")
                                          : i18n("Nothing here")
        explanation: pane.loadError ? pane.loadError : ""
    }
}
