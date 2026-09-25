/* Starts the daemon bundled in contents/code when nothing answers on the port. */

import QtQuick

import org.kde.plasma.plasma5support as P5Support

QtObject {
    id: service

    required property var client
    property string appletVersion: ""
    property bool autoStart: false

    readonly property string codeDir:
        decodeURIComponent(Qt.resolvedUrl("../code").toString().replace(/^file:\/\//, ""))
    property bool bundled: false
    property bool busy: false
    property var missing: []
    property string error: ""

    readonly property bool ours: !!client.daemonInfo.home && client.daemonInfo.home === codeDir
    readonly property bool outdated: ours && !!appletVersion
                                     && client.daemonInfo.version !== appletVersion

    property bool _triedStart: false
    property bool _triedUpgrade: false

    function check() { _run("check"); }

    function start() {
        _triedStart = true;
        _run("start");
    }

    function _run(action) {
        busy = true;
        error = "";
        runner.connectSource("sh '" + codeDir.replace(/'/g, "'\\''") + "/service.sh' " + action);
    }

    function _finished(action, code, stdout, stderr) {
        busy = false;
        bundled = code !== 3 && code !== 127;
        missing = code === 2 ? stdout.split("\n").filter(line => line) : [];
        if (action === "start" && code !== 0 && code !== 2) {
            error = stderr.trim() || i18n("The service could not be started");
        }
    }

    property P5Support.DataSource _runner: P5Support.DataSource {
        id: runner
        engine: "executable"
        connectedSources: []
        onNewData: (sourceName, data) => {
            disconnectSource(sourceName);
            service._finished(sourceName.split(" ").pop(), data["exit code"],
                              data["stdout"] || "", data["stderr"] || "");
        }
    }

    // A daemon launched by plasmashell itself might start a moment later, so give it one retry first.
    property Timer _autoStart: Timer {
        interval: 6000
        running: service.autoStart && service.bundled && !service._triedStart
                 && !service.client.online
        onTriggered: service.start()
    }

    onOutdatedChanged: {
        if (outdated && !_triedUpgrade) {
            _triedUpgrade = true;
            start();
        }
    }

    Component.onCompleted: check()
}
