import Foundation

// Bundle.module (SwiftPM) cherche à la racine du .app puis dans le .build absolu de compilation,
// et crashe s'il ne trouve rien : il casse dès que le dépôt est déplacé.
extension Bundle {
    static let appResources: Bundle =
        Bundle.main.url(forResource: "HyperClaude_HyperClaude", withExtension: "bundle")
            .flatMap(Bundle.init(url:)) ?? .main
}
