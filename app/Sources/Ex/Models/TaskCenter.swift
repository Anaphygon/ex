import ExCore
import Foundation
import Observation

/// One unit of background work shown in the task panel.
@MainActor @Observable final class TaskItem: Identifiable {
    enum Kind {
        case extract, pack, open
    }

    enum State: Equatable {
        case running
        case waitingPassword
        case done(EngineResult)
        case failed(String)
        case cancelled
    }

    let id = UUID()
    let kind: Kind
    let title: String
    var percent: Int?
    var state: State = .running
    fileprivate let run: EngineRun

    init(kind: Kind, title: String, run: EngineRun) {
        self.kind = kind
        self.title = title
        self.run = run
    }

    var isFinished: Bool {
        switch state {
        case .running, .waitingPassword: false
        default: true
        }
    }
}

/// Runs engine commands and keeps their state for the task panel.
@MainActor @Observable final class TaskCenter {
    private(set) var tasks: [TaskItem] = []

    /// Called when an engine asks for a password: the archive, whether it is a retry, and the run to answer.
    @ObservationIgnored var onPassword: ((URL, Bool, EngineRun) -> Void)?
    /// Called once a run has produced its last event.
    @ObservationIgnored var onRunEnded: ((EngineRun) -> Void)?

    var visibleTasks: [TaskItem] { tasks }
    var activeCount: Int { tasks.filter { !$0.isFinished }.count }

    @discardableResult
    func start(
        _ kind: TaskItem.Kind,
        title: String,
        archive: URL?,
        run: EngineRun,
        onSuccess: @escaping @MainActor (EngineResult) -> Void
    ) -> TaskItem {
        let item = TaskItem(kind: kind, title: title, run: run)
        tasks.append(item)
        Task { @MainActor [weak self] in
            for await event in run.events {
                switch event {
                case .progress(let percent):
                    item.percent = percent
                    item.state = .running
                case .password(_, let retry):
                    item.state = .waitingPassword
                    if let archive { self?.onPassword?(archive, retry, run) } else { run.reply(password: nil) }
                case .done(let result):
                    item.state = .done(result)
                    onSuccess(result)
                    // Opening a file is not something to keep a record of.
                    if kind == .open { self?.remove(item) }
                case .error(let message):
                    item.state = .failed(message)
                case .cancelled:
                    item.state = .cancelled
                    if kind == .open { self?.remove(item) }
                case .listing, .formats:
                    break
                }
            }
            self?.onRunEnded?(run)
        }
        return item
    }

    func cancel(_ item: TaskItem) {
        item.run.cancel()
    }

    func remove(_ item: TaskItem) {
        tasks.removeAll { $0.id == item.id }
    }

    func clearFinished() {
        tasks.removeAll(where: \.isFinished)
    }
}
