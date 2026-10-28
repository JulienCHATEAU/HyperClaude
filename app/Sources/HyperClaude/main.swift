import AppKit

// Auto-test d'integration (donnees Python -> Swift) sans lancer la boucle UI.
if CommandLine.arguments.contains("--selftest") {
    let root = DataSource.repoRoot() ?? "(introuvable)"
    let sessions = DataSource.sessions()
    let usage = DataSource.usage()
    let iconFound = Bundle.module.url(forResource: "menubar-icon", withExtension: "png") != nil
    FileHandle.standardOutput.write(Data("repoRoot: \(root)\n".utf8))
    FileHandle.standardOutput.write(Data("icon resource found: \(iconFound)\n".utf8))
    FileHandle.standardOutput.write(Data("sessions: \(sessions.count)\n".utf8))
    for s in sessions {
        FileHandle.standardOutput.write(Data("  - \(s.name ?? "?") [\(s.status)] tty=\(s.tty ?? "-") focusable=\(s.focusable)\n".utf8))
    }
    if let u = usage {
        FileHandle.standardOutput.write(Data("usage: available=\(u.available) session=\(u.sessionPercent.map { String($0) } ?? "-") weekly=\(u.weeklyPercent.map { String($0) } ?? "-") err=\(u.error ?? "-")\n".utf8))
    } else {
        FileHandle.standardOutput.write(Data("usage: (nil)\n".utf8))
    }
    let rc = RemoteControl.state()
    FileHandle.standardOutput.write(Data("rc: server=\(rc.serverRunning) sleepDisabled=\(rc.sleepDisabled) dir=\(RemoteControl.directory)\n".utf8))
    exit(sessions.isEmpty ? 2 : 0)
}

// App agent (sans icone Dock) : vit uniquement dans la barre de menus.
let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
