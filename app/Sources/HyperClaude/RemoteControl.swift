import Foundation

/// Equivalent Swift de la fonction shell `rc` (~/.zshrc) : meme session tmux et memes
/// commandes pmset, pour qu'un `rc on` / `rc off` au terminal se reflete dans le switch.
/// `sudo -n` exige la regle /etc/sudoers.d/claude-rc-pmset : l'app ne demande jamais de mot de passe.
enum RemoteControl {

    static let session = "claude-rc"

    struct State: Equatable {
        var serverRunning = false
        var sleepDisabled = false
        var active: Bool { serverRunning && sleepDisabled }
        var inconsistent: Bool { serverRunning != sleepDisabled }
    }

    enum Failure: Error {
        case sudo
        case start
    }

    /// Meme dossier que CLAUDE_RC_DIR dans ~/.zshrc.
    static let directory = NSHomeDirectory() + "/Documents/Repositories"

    /// Nom optionnel de la session, comme `rc on <nom>` (`defaults write ... rcName "Mac Background Agent"`).
    static var name: String? {
        UserDefaults.standard.string(forKey: "rcName").flatMap { $0.isEmpty ? nil : $0 }
    }

    /// Shell de login : recupere le PATH de brew (.zprofile) que l'app n'herite pas.
    @discardableResult
    private static func zsh(_ script: String) -> (status: Int32, output: String) {
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/bin/zsh")
        // ~/.local/bin (claude) n'est ajoute que par .zshrc, que `zsh -l` ne lit pas.
        proc.arguments = ["-lc", "export PATH=\"$HOME/.local/bin:$PATH\"\n" + script]
        let out = Pipe()
        proc.standardOutput = out
        proc.standardError = Pipe()
        do { try proc.run() } catch { return (-1, "") }
        let data = out.fileHandleForReading.readDataToEndOfFile()
        proc.waitUntilExit()
        return (proc.terminationStatus, String(decoding: data, as: UTF8.self))
    }

    private static func quote(_ s: String) -> String {
        "'" + s.replacingOccurrences(of: "'", with: "'\\''") + "'"
    }

    static func state() -> State {
        let out = zsh("""
        tmux has-session -t \(session) 2>/dev/null && echo server
        pmset -g | grep -q 'SleepDisabled[[:space:]]*1' && echo nosleep
        true
        """).output
        return State(serverRunning: out.contains("server"), sleepDisabled: out.contains("nosleep"))
    }

    static func start() -> Failure? {
        if zsh("sudo -n /usr/bin/pmset -a disablesleep 1").status != 0 { return .sudo }
        // Sans session pre-creee, l'arret archive les sessions : le prochain demarrage repart de zero.
        var cmd = "claude remote-control --no-create-session-in-dir"
        if let name { cmd += " --name " + quote(name) }
        let script = "tmux has-session -t \(session) 2>/dev/null"
            + " || tmux new-session -d -s \(session) -c \(quote(directory)) \(quote(cmd))"
        // Une session tmux dont la commande echoue meurt aussitot : on verifie qu'elle tient.
        if zsh(script + "\nsleep 2\ntmux has-session -t \(session) 2>/dev/null").status == 0 { return nil }
        zsh("sudo -n /usr/bin/pmset -a disablesleep 0")
        return .start
    }

    static func stop() -> Failure? {
        zsh("""
        if tmux has-session -t \(session) 2>/dev/null; then
          tmux send-keys -t \(session) C-c
          sleep 2
          tmux kill-session -t \(session) 2>/dev/null
        fi
        if pkill -f '^claude remote-control'; then
          sleep 2
          pkill -9 -f '^claude remote-control'
        fi
        true
        """)
        return zsh("sudo -n /usr/bin/pmset -a disablesleep 0").status == 0 ? nil : .sudo
    }
}
