import Foundation

/// Etat normalise d'une session Claude Code (fourni par le socle Python `hyperclaude`).
struct Session: Decodable {
    let pid: Int
    let sessionId: String?
    let name: String?
    let title: String?
    let cwd: String?
    let status: String
    let waitingFor: String?
    let tty: String?
    let shellPid: Int?
    let focusable: Bool
    let stale: Bool
    let remote: Bool
    let model: String?
    let contextPercent: Double?
    let guardFiveHour: Int?
    let guardSevenDay: Int?
}

/// Instantane d'usage de quota (fourni par `hyperclaude.usage`).
struct Usage: Decodable {
    let available: Bool
    let sessionPercent: Double?
    let weeklyPercent: Double?
    let sessionSeverity: String?
    let weeklySeverity: String?
    let error: String?
}
