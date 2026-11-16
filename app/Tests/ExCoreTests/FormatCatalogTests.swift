import Testing
@testable import ExCore

@Suite struct FormatCatalogTests {
    @Test(arguments: [
        ("x.zip", "ZIP"), ("X.RAR", "RAR"), ("x.tar.gz", "TAR.GZ"), ("x.7z.001", "7Z"),
        ("x.part2.rar", "RAR"), ("x.tar.zst", "TAR.ZST"), ("disk.iso", "ISO"), ("app.apk", "APK"),
    ])
    func recognisesArchives(name: String, label: String) {
        #expect(FormatCatalog.info(forFileName: name)?.label == label)
    }

    @Test(arguments: ["notes.txt", "photo.jpg", "zip", ".zip", "report.docx", "movie.mp4.001"])
    func ignoresOtherFiles(name: String) {
        #expect(!FormatCatalog.isArchive(fileName: name))
    }

    @Test func families() {
        #expect(FormatCatalog.info(forFileName: "a.7z")?.family == .sevenZip)
        #expect(FormatCatalog.info(forFileName: "a.dmg")?.family == .disk)
    }

    @Test func ratio() {
        #expect(Formatting.ratio(packed: 25, size: 100) == 0.25)
        #expect(Formatting.ratio(packed: nil, size: 100) == nil)
        #expect(Formatting.ratio(packed: 1, size: 0) == nil)
    }
}
