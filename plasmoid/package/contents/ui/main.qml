/* Stream Playing: a thin view over the streamplay daemon. */

import QtQuick
import QtQuick.Layouts

import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.plasmoid
import org.kde.kirigami as Kirigami

import "Formatting.js" as Fmt

PlasmoidItem {
    id: root

    readonly property Client client: sharedClient
    readonly property Service service: sharedService
    readonly property var track: client.track
    readonly property bool playing: client.playback.status === "playing"
    readonly property bool hasTrack: !!track

    Plasmoid.icon: "media-playback-start"
    Plasmoid.backgroundHints: PlasmaCore.Types.DefaultBackground
                            | PlasmaCore.Types.ConfigurableBackground

    // Stay out of the way in the system tray until something is actually going on.
    Plasmoid.status: (playing || client.playback.status === "paused")
                     ? PlasmaCore.Types.ActiveStatus
                     : PlasmaCore.Types.PassiveStatus

    toolTipMainText: hasTrack ? track.title : i18n("Stream Playing")
    toolTipSubText: {
        if (!client.online) {
            return i18n("The streamplay service is not running");
        }
        if (!client.linked) {
            return i18n("No music server is connected");
        }
        if (!hasTrack) {
            return i18n("Nothing is playing");
        }
        const where = client.outputName;
        return where ? i18n("%1 — on %2", Fmt.subtitle(track), where)
                     : Fmt.subtitle(track);
    }

    switchWidth: Kirigami.Units.gridUnit * 18
    switchHeight: Kirigami.Units.gridUnit * 18

    Client {
        id: sharedClient
        host: Plasmoid.configuration.daemonHost
        port: Plasmoid.configuration.daemonPort
    }

    Service {
        id: sharedService
        client: sharedClient
        appletVersion: Plasmoid.metaData.version
        autoStart: Plasmoid.configuration.startService
    }

    compactRepresentation: CompactRepresentation {}
    fullRepresentation: FullRepresentation {}
}
