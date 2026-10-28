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

// Rendu des icones de barre de menus en PNG (clair/sombre) pour verification visuelle.
if let i = CommandLine.arguments.firstIndex(of: "--render-icons"), i + 1 < CommandLine.arguments.count {
    let dir = CommandLine.arguments[i + 1]
    let cases: [(String, Int, RemoteControl.State)] = [
        ("neutre", 0, .init()),
        ("rc-actif", 0, .init(serverRunning: true, sleepDisabled: true)),
        ("rc-incoherent", 0, .init(serverRunning: true, sleepDisabled: false)),
        ("attente-rc-actif", 2, .init(serverRunning: true, sleepDisabled: true)),
    ]
    for (name, waiting, rc) in cases {
        for dark in [false, true] {
            let img = AppDelegate.statusImage(waiting: waiting, rc: rc, dark: dark)
            guard let tiff = img.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff),
                  let png = rep.representation(using: .png, properties: [:]) else { continue }
            try? png.write(to: URL(fileURLWithPath: "\(dir)/\(name)-\(dark ? "sombre" : "clair").png"))
        }
    }
    exit(0)
}

// App agent (sans icone Dock) : vit uniquement dans la barre de menus.
let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
