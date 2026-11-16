// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "Ex",
    platforms: [.macOS("26.0")],
    products: [.executable(name: "Ex", targets: ["Ex"])],
    targets: [
        .target(name: "ExCore"),
        .executableTarget(name: "Ex", dependencies: ["ExCore"]),
        .testTarget(name: "ExCoreTests", dependencies: ["ExCore"]),
    ]
)
