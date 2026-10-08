import SwiftUI

private struct LaunchConfiguration {
    static let durations = [5, 10, 15, 25, 50]

    var seed = 0
    var duration = 25
    var quiet = false
    var prefill = ""
    var scroll = false

    init(arguments: [String]) throws {
        var index = 0
        while index < arguments.count {
            let option = arguments[index]
            guard ["--seed", "--duration", "--quiet", "--prefill", "--scroll"].contains(option) else {
                index += 1
                continue
            }
            guard index + 1 < arguments.count else { throw ArgumentError.invalid }
            let value = arguments[index + 1]
            switch option {
            case "--seed":
                guard let number = Int(value) else { throw ArgumentError.invalid }
                seed = number
            case "--duration":
                guard let number = Int(value), Self.durations.contains(number) else {
                    throw ArgumentError.invalid
                }
                duration = number
            case "--quiet", "--scroll":
                guard value == "true" || value == "false" else { throw ArgumentError.invalid }
                if option == "--quiet" { quiet = value == "true" }
                else { scroll = value == "true" }
            case "--prefill":
                prefill = value
            default:
                break
            }
            index += 2
        }
    }

    var durationOrder: [Int] {
        var choices = Self.durations
        var random = UInt64(truncatingIfNeeded: seed)
        for index in stride(from: choices.count - 1, through: 1, by: -1) {
            random = random &* 6_364_136_223_846_793_005 &+ 1_442_695_040_888_963_407
            choices.swapAt(index, Int(random % UInt64(index + 1)))
        }
        return choices
    }

    private enum ArgumentError: Error { case invalid }
}

private enum Phase: String, Codable {
    case home, editing, running
}

private struct BenchmarkState: Codable {
    var phase: Phase = .home
    var name: String
    var duration: Int
    var quiet: Bool
    let seed: Int
    var screenWidth: Double = 0
    var screenHeight: Double = 0

    enum CodingKeys: String, CodingKey {
        case phase, name, duration, quiet, seed
        case screenWidth = "screen_width"
        case screenHeight = "screen_height"
    }
}

@MainActor
private final class BenchmarkModel: ObservableObject {
    @Published private(set) var state: BenchmarkState {
        didSet { persist() }
    }
    @Published private(set) var stateWriteFailed = false
    let configuration: LaunchConfiguration

    init(configuration: LaunchConfiguration) {
        self.configuration = configuration
        state = BenchmarkState(
            name: configuration.prefill,
            duration: configuration.duration,
            quiet: configuration.quiet,
            seed: configuration.seed
        )
    }

    func edit() { state.phase = .editing }
    func setName(_ name: String) { state.name = name }
    func setDuration(_ duration: Int) { state.duration = duration }
    func setQuiet(_ quiet: Bool) { state.quiet = quiet }

    func start() {
        guard state.phase == .editing,
              !state.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        state.phase = .running
    }

    func updateScreen(_ size: CGSize) {
        guard size.width > 0, size.height > 0 else { return }
        var next = state
        next.screenWidth = Double(size.width)
        next.screenHeight = Double(size.height)
        state = next
    }

    private func persist() {
        do {
            let documents = try FileManager.default.url(
                for: .documentDirectory, in: .userDomainMask,
                appropriateFor: nil, create: true
            )
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.sortedKeys]
            try encoder.encode(state).write(
                to: documents.appendingPathComponent("axe-benchmark-state.json"),
                options: .atomic
            )
            stateWriteFailed = false
        } catch {
            stateWriteFailed = true
        }
    }
}

@main
@MainActor
struct FocusBenchApp: App {
    @StateObject private var model: BenchmarkModel

    init() {
        do {
            let configuration = try LaunchConfiguration(
                arguments: Array(ProcessInfo.processInfo.arguments.dropFirst())
            )
            _model = StateObject(wrappedValue: BenchmarkModel(configuration: configuration))
        } catch {
            fatalError("Invalid FocusBench launch arguments.")
        }
    }

    var body: some Scene {
        WindowGroup { FocusBenchView(model: model) }
    }
}

private struct FocusBenchView: View {
    @ObservedObject var model: BenchmarkModel
    @FocusState private var nameFocused: Bool

    var body: some View {
        GeometryReader { viewport in
            VStack(alignment: .leading, spacing: 20) {
                Text("FocusBench")
                    .font(.headline)
                    .foregroundStyle(.secondary)
                switch model.state.phase {
                case .home: home
                case .editing: editor(viewportHeight: viewport.size.height)
                case .running: running
                }
                if model.stateWriteFailed {
                    Text("State file unavailable")
                        .foregroundStyle(.red)
                        .accessibilityIdentifier("stateWriteError")
                }
            }
            .padding(24)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
        .onGeometryChange(for: CGSize.self) { geometry in
            // Screenshots and HID points include the safe areas around app content.
            CGSize(
                width: geometry.size.width + geometry.safeAreaInsets.leading
                    + geometry.safeAreaInsets.trailing,
                height: geometry.size.height + geometry.safeAreaInsets.top
                    + geometry.safeAreaInsets.bottom
            )
        } action: { model.updateScreen($0) }
        .background(Color(.systemGroupedBackground).ignoresSafeArea())
    }

    private var home: some View {
        VStack(alignment: .leading, spacing: 24) {
            Text("Make time to focus.")
                .font(.largeTitle.bold())
            Text("Plan one session.")
                .foregroundStyle(.secondary)
            Button { model.edit() } label: { primaryLabel("New session") }
                .buttonStyle(.plain)
                .accessibilityIdentifier("newSession")
        }
    }

    private func editor(viewportHeight: CGFloat) -> some View {
        VStack(spacing: 16) {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    Text("New session")
                        .font(.largeTitle.bold())
                    nameField
                    durationPicker
                    quietToggle
                    if model.configuration.scroll {
                        // A viewport of space keeps Start below the fold at every window size.
                        Color.clear
                            .frame(height: viewportHeight)
                            .accessibilityHidden(true)
                        startButton
                    }
                }
                .padding(.bottom, 8)
            }
            .accessibilityIdentifier("sessionScroll")
            .scrollDismissesKeyboard(.interactively)
            if !model.configuration.scroll { startButton }
        }
    }

    private var nameField: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Session name").font(.headline)
            TextField("Session name", text: Binding(get: { model.state.name }, set: model.setName))
                .textFieldStyle(.plain)
                .focused($nameFocused)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .submitLabel(.done)
                .onSubmit { nameFocused = false }
                .padding(16)
                .frame(maxWidth: .infinity, minHeight: 56, alignment: .leading)
                .background(Color(.secondarySystemGroupedBackground))
                .contentShape(Rectangle())
                .onTapGesture { nameFocused = true }
                .accessibilityLabel("Session name")
                .accessibilityIdentifier("sessionName")
        }
    }

    private var durationPicker: some View {
        let columnCount = model.configuration.seed.isMultiple(of: 2) ? 2 : 3
        return VStack(alignment: .leading, spacing: 8) {
            Text("Duration").font(.headline)
            LazyVGrid(columns: Array(repeating: GridItem(.flexible()), count: columnCount), spacing: 8) {
                ForEach(model.configuration.durationOrder, id: \.self) { duration in
                    Button {
                        nameFocused = false
                        model.setDuration(duration)
                    } label: {
                        Text("\(duration) min")
                            .font(.body.weight(.semibold))
                            .frame(maxWidth: .infinity, minHeight: 56)
                            .foregroundStyle(model.state.duration == duration ? .white : .primary)
                            .background(model.state.duration == duration
                                        ? Color.accentColor : Color(.secondarySystemGroupedBackground))
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("\(duration) minutes")
                    .accessibilityIdentifier("duration\(duration)")
                    .accessibilityValue(model.state.duration == duration ? "Selected" : "Not selected")
                    .accessibilityAddTraits(model.state.duration == duration ? .isSelected : [])
                }
            }
        }
    }

    private var quietToggle: some View {
        Toggle(isOn: Binding(get: { model.state.quiet }, set: { quiet in
            nameFocused = false
            model.setQuiet(quiet)
        })) {
            HStack(spacing: 12) {
                Text("Quiet mode")
                Spacer()
                Text(model.state.quiet ? "On" : "Off")
                Image(systemName: model.state.quiet ? "checkmark.square.fill" : "square")
            }
            .padding(16)
            .frame(maxWidth: .infinity, minHeight: 56)
            .background(Color(.secondarySystemGroupedBackground))
            .contentShape(Rectangle())
        }
        .toggleStyle(.button)
        .buttonStyle(.plain)
        .accessibilityLabel("Quiet mode")
        .accessibilityValue(model.state.quiet ? "On" : "Off")
        .accessibilityIdentifier("quietMode")
    }

    private var startButton: some View {
        Button {
            nameFocused = false
            model.start()
        } label: { primaryLabel("Start session") }
            .buttonStyle(.plain)
            .disabled(model.state.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            .accessibilityIdentifier("startSession")
    }

    private var running: some View {
        VStack(alignment: .leading, spacing: 24) {
            Text("Session started")
                .font(.largeTitle.bold())
                .accessibilityIdentifier("sessionStarted")
            Text(model.state.name)
                .font(.title2)
                .accessibilityIdentifier("runningName")
            Text("\(model.state.duration) minutes")
                .font(.title3)
                .accessibilityIdentifier("runningDuration")
            Text(model.state.quiet ? "Quiet mode on" : "Quiet mode off")
                .font(.title3)
                .accessibilityIdentifier("runningQuietMode")
        }
    }

    private func primaryLabel(_ title: String) -> some View {
        Text(title)
            .font(.body.weight(.semibold))
            .foregroundStyle(.white)
            .frame(maxWidth: .infinity, minHeight: 56)
            .background(Color.accentColor)
            .contentShape(Rectangle())
    }
}
