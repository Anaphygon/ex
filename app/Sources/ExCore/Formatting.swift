import Foundation

public enum Formatting {
    public static func bytes(_ count: Int64) -> String {
        ByteCountFormatter.string(fromByteCount: count, countStyle: .file)
    }

    /// Share of the original size the archive takes, e.g. 0.42 for "42%".
    public static func ratio(packed: Int64?, size: Int64) -> Double? {
        guard let packed, size > 0 else { return nil }
        return Double(packed) / Double(size)
    }
}
