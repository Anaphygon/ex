import ExCore
import SwiftUI

struct PasswordSheet: View {
    let prompt: PasswordPrompt
    @State private var password = ""
    @State private var shake = false

    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: "lock.fill")
                .font(.system(size: 26, weight: .semibold))
                .foregroundStyle(.white)
                .frame(width: 60, height: 60)
                .background(LinearGradient(colors: [.exOrange, Color(red: 0.9, green: 0.33, blue: 0.0)], startPoint: .top, endPoint: .bottom), in: Circle())
                .shadow(color: .exOrange.opacity(0.4), radius: 10, y: 4)
            VStack(spacing: 4) {
                Text(prompt.archiveName).font(.title3.weight(.semibold)).lineLimit(1).truncationMode(.middle)
                Text(prompt.retry ? "Wrong password. Try again." : "This archive is locked. Enter its password.")
                    .foregroundStyle(prompt.retry ? .red : .secondary)
            }
            SecureField("Password", text: $password)
                .textFieldStyle(.roundedBorder)
                .controlSize(.large)
                .onSubmit(submit)
                .offset(x: shake ? -6 : 0)
                .animation(prompt.retry ? .bouncy(duration: 0.2, extraBounce: 0.6).repeatCount(3) : nil, value: shake)
            HStack {
                Button("Cancel", role: .cancel) { prompt.respond(nil) }
                    .keyboardShortcut(.cancelAction)
                Spacer()
                Button("Open", action: submit)
                    .keyboardShortcut(.defaultAction)
                    .buttonStyle(.glassProminent)
                    .tint(.exOrange)
                    .disabled(password.isEmpty)
            }
        }
        .padding(24)
        .frame(width: 360)
        .onAppear { if prompt.retry { shake.toggle() } }
    }

    private func submit() {
        guard !password.isEmpty else { return }
        prompt.respond(password)
    }
}

struct CompressSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State var draft: CompressDraft
    @State private var totalBytes: Int64?

    private static let levels = [(0, "Store"), (1, "Fast"), (5, "Normal"), (9, "Maximum")]
    private static let volumes: [(Int64?, String)] = [
        (nil, "Don't split"), (100_000_000, "100 MB"), (700_000_000, "700 MB"),
        (1_000_000_000, "1 GB"), (4_000_000_000, "4 GB"),
    ]

    private var supportsPassword: Bool { ["zip", "7z", "rar"].contains(draft.format) }
    private var supportsHiddenNames: Bool { ["7z", "rar"].contains(draft.format) }
    private var supportsVolumes: Bool { ["zip", "7z", "rar"].contains(draft.format) }

    private var problem: String? {
        let name = draft.name.trimmingCharacters(in: .whitespaces)
        if name.isEmpty || name.contains("/") || name == "." || name == ".." { return "Enter a valid archive name" }
        if supportsPassword, draft.password != draft.confirmation { return "Passwords don't match" }
        return nil
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 12) {
                FormatTile(info: FormatCatalog.info(forFileName: "x.\(draft.format)") ?? FormatInfo(label: draft.format.uppercased(), family: .other), size: 44)
                VStack(alignment: .leading, spacing: 2) {
                    Text("New Archive").font(.title3.weight(.semibold))
                    Text(summary).foregroundStyle(.secondary).font(.callout).lineLimit(1)
                }
                Spacer()
            }
            .padding([.horizontal, .top], 22)
            .padding(.bottom, 6)

            Form {
                Section {
                    HStack(spacing: 2) {
                        TextField("Name", text: $draft.name).textFieldStyle(.plain)
                        Text(".\(draft.format)").foregroundStyle(.secondary)
                    }
                    Picker("Format", selection: $draft.format) {
                        ForEach(model.packFormats, id: \.self) { Text($0.uppercased()).tag($0) }
                    }
                    Picker("Compression", selection: $draft.level) {
                        ForEach(Self.levels, id: \.0) { Text($0.1).tag($0.0) }
                    }
                    .pickerStyle(.segmented)
                }
                Section {
                    SecureField("Password", text: $draft.password, prompt: Text(supportsPassword ? "Optional" : "Not supported by \(draft.format)"))
                        .disabled(!supportsPassword)
                    if supportsPassword && !draft.password.isEmpty {
                        SecureField("Confirm", text: $draft.confirmation)
                        Toggle("Hide file names", isOn: $draft.encryptNames)
                            .disabled(!supportsHiddenNames)
                            .help(supportsHiddenNames ? "The file list needs the password too" : "7Z and RAR only")
                    }
                } header: {
                    Text("Security")
                }
                Section {
                    Picker("Split into volumes", selection: $draft.volumeBytes) {
                        ForEach(Self.volumes, id: \.1) { Text($0.1).tag($0.0) }
                    }
                    .disabled(!supportsVolumes)
                    LabeledContent("Save to") {
                        HStack {
                            Text(draft.folder.path(percentEncoded: false).replacingOccurrences(of: NSHomeDirectory(), with: "~"))
                                .lineLimit(1).truncationMode(.head).foregroundStyle(.secondary)
                            Button("Change…", action: chooseFolder)
                        }
                    }
                }
            }
            .formStyle(.grouped)
            .scrollDisabled(true)

            HStack {
                if let problem {
                    Label(problem, systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.orange).font(.callout)
                }
                Spacer()
                Button("Cancel", role: .cancel) { dismiss() }
                    .keyboardShortcut(.cancelAction)
                Button("Compress") {
                    var final = draft
                    if !supportsPassword { final.password = "" }
                    if !supportsVolumes { final.volumeBytes = nil }
                    final.name = final.name.trimmingCharacters(in: .whitespaces)
                    model.compress(final)
                    dismiss()
                }
                .keyboardShortcut(.defaultAction)
                .buttonStyle(.glassProminent)
                .tint(.exOrange)
                .disabled(problem != nil)
            }
            .padding(.horizontal, 22)
            .padding(.bottom, 18)
        }
        .frame(width: 480)
        .task {
            let sources = draft.sources
            totalBytes = await Task.detached { FileSystem.totalSize(of: sources) }.value
        }
    }

    private var summary: String {
        let names = draft.sources.count == 1 ? draft.sources[0].lastPathComponent : "\(draft.sources.count) items"
        guard let totalBytes else { return "\(names) · calculating…" }
        return "\(names) · \(Formatting.bytes(totalBytes))"
    }

    private func chooseFolder() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        panel.directoryURL = draft.folder
        if panel.runModal() == .OK, let url = panel.url { draft.folder = url }
    }
}
