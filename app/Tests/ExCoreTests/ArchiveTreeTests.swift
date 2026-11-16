import Foundation
import Testing
@testable import ExCore

@Suite struct ArchiveTreeTests {
    let tree = ArchiveTree(entries: [
        ArchiveEntry(path: "project/b.txt", isDir: false, size: 20, packed: 5, modified: 100),
        ArchiveEntry(path: "project/A.txt", isDir: false, size: 10, packed: 4, modified: 300),
        ArchiveEntry(path: "project/sub/c.bin", isDir: false, size: 70, packed: 70, encrypted: true),
        ArchiveEntry(path: "readme.md", isDir: false, size: 1, packed: 1),
    ])

    @Test func missingFoldersAreCreated() throws {
        let project = try #require(tree.node(at: "project"))
        #expect(project.isDir)
        #expect(project.children.map(\.name) == ["sub", "A.txt", "b.txt"])
        #expect(tree.node(at: "project/sub")?.isDir == true)
    }

    @Test func foldersAddUpWhatIsBelowThem() throws {
        let project = try #require(tree.node(at: "project"))
        #expect(project.size == 100)
        #expect(project.packed == 79)
        #expect(project.fileCount == 3)
        #expect(project.encrypted)
        #expect(tree.fileCount == 4)
        #expect(tree.totalSize == 101)
    }

    @Test func folderDateIsTheNewestInside() throws {
        #expect(tree.node(at: "project")?.modified == Date(timeIntervalSince1970: 300))
    }

    @Test func rootListsFoldersFirst() {
        #expect(tree.root.children.map(\.name) == ["project", "readme.md"])
    }

    @Test func unknownPackedSizeMakesTheTotalUnknown() {
        let partial = ArchiveTree(entries: [
            ArchiveEntry(path: "a", isDir: false, size: 1, packed: 1),
            ArchiveEntry(path: "b", isDir: false, size: 1, packed: nil),
        ])
        #expect(partial.packedSize == nil)
    }

    @Test func explicitFolderEntriesAndDuplicatesAreMerged() {
        let merged = ArchiveTree(entries: [
            ArchiveEntry(path: "d", isDir: true, modified: 50),
            ArchiveEntry(path: "d/x", isDir: false, size: 3),
            ArchiveEntry(path: "d/x", isDir: false, size: 3),
        ])
        #expect(merged.root.children.count == 1)
        #expect(merged.node(at: "d")?.children.count == 1)
        #expect(merged.node(at: "d")?.modified == Date(timeIntervalSince1970: 50))
    }

    @Test func aFileThatAlsoHasChildrenIsAFolder() {
        let odd = ArchiveTree(entries: [
            ArchiveEntry(path: "d", isDir: false, size: 0),
            ArchiveEntry(path: "d/x", isDir: false, size: 3),
        ])
        #expect(odd.node(at: "d")?.isDir == true)
    }

    @Test func encryptedEntriesAreReported() {
        #expect(tree.hasEncryptedEntries)
    }

    @Test func emptyArchiveHasAnEmptyRoot() {
        let empty = ArchiveTree(entries: [])
        #expect(empty.root.children.isEmpty && empty.fileCount == 0)
    }
}
