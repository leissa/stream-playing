/*
 * Manage the music servers.
 *
 * Several can be connected at the same time; each one has its own on/off switch
 * and they all feed the same queue. This page talks to the daemon directly --
 * the servers live there, not in the applet's own settings -- so edits apply as
 * soon as you save them.
 */

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kcmutils as KCM
import org.kde.kirigami as Kirigami

import ".." as Sp

KCM.SimpleKCM {
    id: page

    // Read-only here; edited on the General page. The config system fills them in.
    property string cfg_daemonHost: "127.0.0.1"
    property int cfg_daemonPort: 8760

    /* The profile being edited, or null while showing the list. */
    property var draft: null
    property string status: ""
    property bool statusIsError: false

    function blankProfile(type) {
        return type === "kodi"
            ? { type: "kodi", name: i18n("Kodi"), host: "", port: 8080,
                wsPort: 9090, username: "", password: "", useTls: false,
                enabled: true }
            : { type: "subsonic", name: i18n("Navidrome"), url: "",
                username: "", password: "", legacyAuth: false, verifyTls: true,
                enabled: true };
    }

    function editExisting(id) {
        for (let i = 0; i < client.profileList.length; ++i) {
            if (client.profileList[i].id === id) {
                // A copy, so Cancel really cancels.
                page.draft = JSON.parse(JSON.stringify(client.profileList[i]));
                page.status = "";
                return;
            }
        }
    }

    /* Only send a password when one was typed; blank means "keep the old one". */
    function draftForWire() {
        const out = JSON.parse(JSON.stringify(page.draft));
        if (!out.password) {
            delete out.password;
        }
        delete out.hasPassword;
        return out;
    }

    function report(message, isError) {
        page.status = message;
        page.statusIsError = !!isError;
    }

    Sp.Client {
        id: client
        host: page.cfg_daemonHost
        port: page.cfg_daemonPort
    }

    ColumnLayout {
        anchors.left: parent.left
        anchors.right: parent.right
        spacing: Kirigami.Units.largeSpacing

        // ------------------------------------------------------------ list

        Kirigami.InlineMessage {
            Layout.fillWidth: true
            visible: !client.online
            type: Kirigami.MessageType.Warning
            text: i18n("Cannot reach the streamplay service on %1:%2. "
                     + "Start it with: systemctl --user start streamplay",
                       page.cfg_daemonHost, page.cfg_daemonPort)
        }

        ColumnLayout {
            Layout.fillWidth: true
            visible: page.draft === null
            spacing: Kirigami.Units.smallSpacing

            Repeater {
                model: client.sources

                QQC2.Frame {
                    required property var modelData
                    Layout.fillWidth: true

                    RowLayout {
                        anchors.fill: parent
                        spacing: Kirigami.Units.largeSpacing

                        Kirigami.Icon {
                            implicitWidth: Kirigami.Units.iconSizes.medium
                            implicitHeight: Kirigami.Units.iconSizes.medium
                            source: modelData.type === "kodi"
                                    ? "kodi" : "server-database"
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 0

                            QQC2.Label {
                                Layout.fillWidth: true
                                elide: Text.ElideRight
                                text: modelData.name
                            }

                            QQC2.Label {
                                Layout.fillWidth: true
                                elide: Text.ElideRight
                                font: Kirigami.Theme.smallFont
                                color: modelData.state === "error"
                                       ? Kirigami.Theme.negativeTextColor
                                       : Kirigami.Theme.disabledTextColor
                                text: {
                                    switch (modelData.state) {
                                    case "connected":  return i18n("Connected");
                                    case "connecting": return i18n("Connecting…");
                                    case "error":      return modelData.message
                                                           || i18n("Connection failed");
                                    default:           return i18n("Not connected");
                                    }
                                }
                            }
                        }

                        QQC2.Switch {
                            checked: modelData.enabled
                            enabled: client.online
                            QQC2.ToolTip.text: i18n("Connect to this server")
                            QQC2.ToolTip.visible: hovered
                            onToggled: {
                                client.send(checked ? "sources.connect"
                                                    : "sources.disconnect",
                                            { id: modelData.id });
                            }
                        }

                        QQC2.Button {
                            icon.name: "document-edit"
                            display: QQC2.AbstractButton.IconOnly
                            text: i18n("Edit")
                            QQC2.ToolTip.text: text
                            QQC2.ToolTip.visible: hovered
                            onClicked: page.editExisting(modelData.id)
                        }

                        QQC2.Button {
                            icon.name: "edit-delete"
                            display: QQC2.AbstractButton.IconOnly
                            text: i18n("Remove")
                            QQC2.ToolTip.text: text
                            QQC2.ToolTip.visible: hovered
                            onClicked: {
                                removeDialog.profileId = modelData.id;
                                removeDialog.profileName = modelData.name;
                                removeDialog.open();
                            }
                        }
                    }
                }
            }

            QQC2.Label {
                Layout.fillWidth: true
                Layout.topMargin: Kirigami.Units.largeSpacing
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                visible: client.sources.length === 0
                opacity: 0.7
                text: i18n("No music servers yet. Add a Subsonic-compatible "
                         + "server such as Navidrome, or a Kodi instance.")
            }

            RowLayout {
                Layout.topMargin: Kirigami.Units.smallSpacing

                QQC2.Button {
                    icon.name: "list-add"
                    text: i18n("Add Navidrome / Subsonic…")
                    onClicked: {
                        page.draft = page.blankProfile("subsonic");
                        page.status = "";
                    }
                }

                QQC2.Button {
                    icon.name: "list-add"
                    text: i18n("Add Kodi…")
                    onClicked: {
                        page.draft = page.blankProfile("kodi");
                        page.status = "";
                    }
                }

                Item { Layout.fillWidth: true }
            }
        }

        // ------------------------------------------------------------ form

        ColumnLayout {
            Layout.fillWidth: true
            visible: page.draft !== null
            spacing: Kirigami.Units.smallSpacing

            Kirigami.FormLayout {
                Layout.fillWidth: true

                QQC2.TextField {
                    Kirigami.FormData.label: i18n("Name:")
                    Layout.fillWidth: true
                    text: page.draft ? (page.draft.name || "") : ""
                    onTextEdited: page.draft.name = text
                }

                // -- Subsonic ------------------------------------------------

                QQC2.TextField {
                    Kirigami.FormData.label: i18n("Server address:")
                    Layout.fillWidth: true
                    visible: page.draft && page.draft.type === "subsonic"
                    placeholderText: "https://music.example.org"
                    text: page.draft ? (page.draft.url || "") : ""
                    onTextEdited: page.draft.url = text
                }

                // -- Kodi ----------------------------------------------------

                QQC2.TextField {
                    Kirigami.FormData.label: i18n("Host:")
                    Layout.fillWidth: true
                    visible: page.draft && page.draft.type === "kodi"
                    placeholderText: "192.168.1.20"
                    text: page.draft ? (page.draft.host || "") : ""
                    onTextEdited: page.draft.host = text
                }

                QQC2.SpinBox {
                    Kirigami.FormData.label: i18n("Web interface port:")
                    visible: page.draft && page.draft.type === "kodi"
                    from: 1
                    to: 65535
                    editable: true
                    value: page.draft && page.draft.port ? page.draft.port : 8080
                    textFromValue: value => value.toString()
                    valueFromText: text => parseInt(text, 10)
                    onValueModified: page.draft.port = value
                }

                QQC2.SpinBox {
                    Kirigami.FormData.label: i18n("Event port:")
                    visible: page.draft && page.draft.type === "kodi"
                    from: 1
                    to: 65535
                    editable: true
                    value: page.draft && page.draft.wsPort ? page.draft.wsPort : 9090
                    textFromValue: value => value.toString()
                    valueFromText: text => parseInt(text, 10)
                    onValueModified: page.draft.wsPort = value
                }

                // -- shared --------------------------------------------------

                QQC2.TextField {
                    Kirigami.FormData.label: i18n("Username:")
                    Layout.fillWidth: true
                    text: page.draft ? (page.draft.username || "") : ""
                    onTextEdited: page.draft.username = text
                }

                Kirigami.PasswordField {
                    id: passwordField
                    Kirigami.FormData.label: i18n("Password:")
                    Layout.fillWidth: true
                    placeholderText: page.draft && page.draft.hasPassword
                                     ? i18n("Unchanged") : ""
                    text: ""
                    onTextEdited: page.draft.password = text
                }

                QQC2.CheckBox {
                    visible: page.draft && page.draft.type === "kodi"
                    text: i18n("Connect over HTTPS")
                    checked: page.draft ? !!page.draft.useTls : false
                    onToggled: page.draft.useTls = checked
                }

                QQC2.CheckBox {
                    visible: page.draft && page.draft.type === "subsonic"
                    text: i18n("Send the password in the old plain format")
                    checked: page.draft ? !!page.draft.legacyAuth : false
                    onToggled: page.draft.legacyAuth = checked
                }

                QQC2.CheckBox {
                    text: i18n("Check the TLS certificate")
                    checked: page.draft ? page.draft.verifyTls !== false : true
                    onToggled: page.draft.verifyTls = checked
                }
            }

            QQC2.Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                visible: page.status.length > 0
                color: page.statusIsError ? Kirigami.Theme.negativeTextColor
                                          : Kirigami.Theme.positiveTextColor
                text: page.status
            }

            RowLayout {
                Layout.topMargin: Kirigami.Units.smallSpacing

                QQC2.Button {
                    icon.name: "network-connect"
                    text: i18n("Test Connection")
                    enabled: client.online
                    onClicked: {
                        page.report(i18n("Testing…"), false);
                        client.call("profiles.test",
                                    { profile: page.draftForWire() },
                                    function (result, error) {
                            page.report(error ? error
                                              : i18n("The server answered."),
                                        !!error);
                        });
                    }
                }

                Item { Layout.fillWidth: true }

                QQC2.Button {
                    text: i18n("Cancel")
                    onClicked: {
                        page.draft = null;
                        page.status = "";
                        passwordField.text = "";
                    }
                }

                QQC2.Button {
                    icon.name: "document-save"
                    text: i18n("Save and Connect")
                    enabled: client.online
                    onClicked: {
                        client.call("profiles.save",
                                    { profile: page.draftForWire(), connect: true },
                                    function (result, error) {
                            if (error) {
                                page.report(error, true);
                                return;
                            }
                            if (result && result.connectError) {
                                page.report(i18n("Saved, but connecting failed: %1",
                                                 result.connectError), true);
                                return;
                            }
                            page.draft = null;
                            page.status = "";
                            passwordField.text = "";
                        });
                    }
                }
            }
        }
    }

    Kirigami.PromptDialog {
        id: removeDialog

        property string profileId: ""
        property string profileName: ""

        title: i18n("Remove music server")
        subtitle: i18n("Remove “%1”? Its tracks stay in the queue but will not "
                     + "play until you add the server again.", profileName)
        standardButtons: Kirigami.Dialog.Cancel

        customFooterActions: Kirigami.Action {
            text: i18n("Remove")
            icon.name: "edit-delete"
            onTriggered: {
                client.send("profiles.delete", { id: removeDialog.profileId });
                removeDialog.close();
            }
        }
    }
}
