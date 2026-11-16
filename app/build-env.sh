# Sourced by the build scripts.
# The macOS 27 SDK in Command Line Tools turns SwiftUI's @State into a macro
# whose plugin those tools do not ship, so build against the 26.5 SDK.
export SDKROOT=/Library/Developer/CommandLineTools/SDKs/MacOSX26.5.sdk
