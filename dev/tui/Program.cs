using System.Collections.ObjectModel;
using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;
using Terminal.Gui.App;
using Terminal.Gui.Configuration;
using Terminal.Gui.Drawing;
using Terminal.Gui.Input;
using Terminal.Gui.ViewBase;
using Terminal.Gui.Views;
using TuiAttribute = Terminal.Gui.Drawing.Attribute;

internal static class Program
{
    public static int Main(string[] args)
    {
        try
        {
            bool inline = false;
            bool selfTest = false;
            bool showHelp = false;
            string? requestedRoot = null;
            for (int i = 0; i < args.Length; i++)
            {
                switch (args[i])
                {
                    case "--help":
                        showHelp = true;
                        break;
                    case "--inline":
                        inline = true;
                        break;
                    case "--self-test":
                        selfTest = true;
                        break;
                    case "--root":
                        if (requestedRoot is not null
                            || i == args.Length - 1
                            || args[++i].StartsWith('-'))
                        {
                            throw new ArgumentException("--root requires one value");
                        }
                        requestedRoot = args[i];
                        break;
                    default:
                        throw new ArgumentException($"unknown option: {args[i]}");
                }
            }

            if (showHelp)
            {
                Console.WriteLine(
                    """
                    Usage: dotnet run --project dev/tui -- [--inline] [--root PATH]
                           dotnet run --project dev/tui -- --self-test [--root PATH]

                    Browse, preview, and run this repository's scripts.
                    Full-screen mode is the default; --inline keeps terminal scrollback.
                    """);
                return 0;
            }

            string root = RootLocator.Find(requestedRoot);
            IReadOnlyList<ScriptSpec> scripts = ScriptCatalog.Load(root);

            if (selfTest)
            {
                SelfTest.Run(root, scripts);
                return 0;
            }

            TuiConfigurationBuilder configuration = new("Scripts");
            configuration.ApplyToStaticFacades();
            Palette.Register(configuration.SchemeManager);
            using IApplication app = Application.Create();
            app.AppModel = inline ? AppModel.Inline : AppModel.FullScreen;
            app.Init();
            using MainWindow window = new(root, scripts);
            app.Run(window);
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine($"scripts-tui: {error.Message}");
            return 1;
        }
    }
}

internal sealed class MainWindow : Runnable
{
    private readonly string _root;
    private readonly IReadOnlyList<ScriptSpec> _scripts;
    private ObservableCollection<ScriptSpec> _visible = [];
    private readonly ListView<ScriptSpec> _list = new();
    private readonly TextField _search = new();
    private readonly Markdown _help = new();
#pragma warning disable CS0618 // Terminal.Gui has no replacement log view yet.
    private readonly TextView _log = new();
#pragma warning restore CS0618
    private readonly FrameView _browser = new() { Title = " Scripts " };
    private readonly FrameView _details = new() { Title = " Help " };
    private readonly View _activity = new() { Visible = false };
    private readonly Button _run = new() { Text = "_Run" };
    private readonly Button _test = new() { Text = "Self-_test" };
    private readonly Button _cancel = new() { Text = "_Cancel" };
    private readonly Button _back = new() { Text = "_Back" };
    private readonly Label _phase = new();
    private readonly Label _elapsed = new();
    private readonly ProgressBar _progress = new() { BidirectionalMarquee = true };
    private readonly List<RunRecord> _history = [];
    private readonly Label _platform = new();
    private readonly View _content;
    private CancellationTokenSource? _cancellation;
    private Stopwatch? _clock;
    private bool _running;

    public MainWindow(string root, IReadOnlyList<ScriptSpec> scripts)
    {
        _root = root;
        _scripts = scripts;
        Title = "Scripts";
        SchemeName = Palette.Base;

        MenuBar menu = new()
        {
            SchemeName = Palette.Accent,
            Menus =
            [
                new MenuBarItem(
                    "_Scripts",
                    [
                        new MenuItem("_Run", "Configure and run", StartWorkflow, Key.F2),
                        new MenuItem("Self-_test", "Run the selected script's self-test", StartSelfTest),
                        new MenuItem("_History", "Show runs from this session", ShowHistory),
                        new MenuItem("_Quit", "", RequestQuit)
                    ]),
                new MenuBarItem(
                    "_Help",
                    [
                        new MenuItem("_Selected script", "Open its help page", ShowSelectedHelp, Key.F1)
                    ])
            ]
        };

        StatusBar status = new() { SchemeName = Palette.Accent };
        status.Add(new Shortcut(Key.F1, "Help", ShowSelectedHelp));
        status.Add(new Shortcut(Key.F2, "Run", StartWorkflow));
        status.Add(new Shortcut(Key.F3, "Filter", () => _search.SetFocus()));
        status.Add(
            new Shortcut(
                Application.GetDefaultKey(Command.Quit),
                "Quit",
                RequestQuit));

        _content = new View
        {
            Y = Pos.Bottom(menu),
            Width = Dim.Fill(),
            Height = Dim.Fill(status)
        };
        _browser.Height = Dim.Fill();
        _details.Height = Dim.Fill();
        ConfigureBrowser();
        ConfigureDetails();
        _content.Add(_browser, _details);
        _content.FrameChanged += (_, _) => ApplyResponsiveLayout();
        Add(menu, _content, status);

        RefreshFilter();
        _search.SetFocus();
    }

    private ScriptSpec? Selected => _list.Value;

    private void ConfigureBrowser()
    {
        Label filterLabel = new() { Text = "Filter:", Y = 0 };
        _search.X = Pos.Right(filterLabel) + 1;
        _search.Width = Dim.Fill();
        _search.Y = 0;
        _search.ValueChanged += (_, _) => RefreshFilter();

        _list.Y = Pos.Bottom(_search);
        _list.Width = Dim.Fill();
        _list.Height = Dim.Fill(2);
        _list.ValueChanged += (_, _) => ShowSelection();
        _list.Accepted += (_, _) => StartWorkflow();

        _run.Y = Pos.AnchorEnd(1);
        _run.SchemeName = Palette.Accent;
        _run.Accepted += (_, _) => StartWorkflow();
        _test.X = Pos.Right(_run) + 1;
        _test.Y = Pos.AnchorEnd(1);
        _test.Accepted += (_, _) => StartSelfTest();
        _platform.X = Pos.Right(_test) + 2;
        _platform.Y = Pos.AnchorEnd(1);
        _platform.Width = Dim.Fill();

        _browser.Add(filterLabel, _search, _list, _run, _test, _platform);
    }

    private void ConfigureDetails()
    {
        _help.Width = Dim.Fill();
        _help.Height = Dim.Fill();
        _help.ShowHeadingPrefix = false;
        _help.ShowCopyButtons = true;

        _phase.Width = Dim.Fill();
        _elapsed.Y = 1;
        _elapsed.Width = Dim.Fill();
        _progress.Y = 2;
        _progress.Width = Dim.Fill();
        _progress.SchemeName = Palette.Accent;
        _log.Y = 3;
        _log.Width = Dim.Fill();
        _log.Height = Dim.Fill(1);
        _log.ReadOnly = true;
        _log.WordWrap = false;
        _cancel.Y = Pos.AnchorEnd(1);
        _cancel.Accepted += (_, _) => CancelRun();
        _back.Y = Pos.AnchorEnd(1);
        _back.Accepted += (_, _) => ShowBrowser();
        _activity.Add(_phase, _elapsed, _progress, _log, _cancel, _back);
        _activity.Width = Dim.Fill();
        _activity.Height = Dim.Fill();

        _details.Add(_help, _activity);
    }

    private void RefreshFilter()
    {
        string query = _search.Value?.Trim() ?? "";
        ScriptSpec? previous = Selected;
        IEnumerable<ScriptSpec> matches = _scripts.Where(
            script =>
                query.Length == 0
                || script.Title.Contains(query, StringComparison.OrdinalIgnoreCase)
                || script.Id.Contains(query, StringComparison.OrdinalIgnoreCase)
                || script.Summary.Contains(query, StringComparison.OrdinalIgnoreCase)
                || script.Platform.ToString().Contains(query, StringComparison.OrdinalIgnoreCase));

        _visible = new ObservableCollection<ScriptSpec>(matches);
        _list.SetSource(_visible);

        if (previous is not null && _visible.Contains(previous))
        {
            _list.Value = previous;
        }
        else
        {
            _list.Value = _visible.FirstOrDefault();
        }
        ShowSelection();
    }

    private void ShowSelection()
    {
        ScriptSpec? script = Selected;
        _help.Text = script?.Markdown
            ?? "# No matching scripts\n\nClear or change the filter.";
        bool available = script?.IsSupported == true && !_running;
        _run.Text = script?.RequiresConfirmation == true ? "_Preview" : "_Run";
        _run.Enabled = available;
        _test.Enabled = available;
        _platform.Text = script is null
            ? ""
            : script.IsSupported
                ? $"{script.Platform} · ready"
                : $"{script.Platform} · view only on this OS";
    }

    private void ApplyResponsiveLayout()
    {
        bool narrow = _content.Frame.Width < 82;
        if (narrow)
        {
            bool showActivity = _activity.Visible;
            _browser.Visible = !showActivity;
            _details.Visible = showActivity;
            _browser.X = 0;
            _browser.Width = Dim.Fill();
            _details.X = 0;
            _details.Width = Dim.Fill();
        }
        else
        {
            _browser.Visible = true;
            _details.Visible = true;
            _browser.X = 0;
            _browser.Width = Dim.Percent(34);
            _details.X = Pos.Right(_browser);
            _details.Width = Dim.Fill();
        }
    }

    private void StartWorkflow()
    {
        ScriptSpec? script = Selected;
        if (_running || script is null)
        {
            return;
        }
        if (!script.IsSupported)
        {
            MessageBox.Query(
                App!,
                "Unavailable",
                $"{script.Title} runs on {script.Platform}.",
                "OK");
            return;
        }

        RunSelection? selection = ConfigureRun(script);
        if (selection is not null)
        {
            if (script.RequiresConfirmation)
            {
                StartPreview(selection);
            }
            else
            {
                StartDirect(selection);
            }
        }
    }

    private RunSelection? ConfigureRun(ScriptSpec script)
    {
        using Wizard wizard = new()
        {
            Title = $"{(script.RequiresConfirmation ? "Preview" : "Run")} · {script.Title}",
            Width = Dim.Percent(78),
            Height = Dim.Percent(78),
            SchemeName = Palette.Base
        };

        WizardStep optionStep = new()
        {
            Title = "Options",
            HelpText = script.RequiresConfirmation
                ? "Choose only what you need. The next run is a dry run."
                : "Choose only what you need."
        };
        Dictionary<OptionSpec, CheckBox> checks = [];
        int row = 0;
        foreach (OptionSpec option in script.Options)
        {
            CheckBox check = new() { Text = option.Label, Y = row++ };
            checks.Add(option, check);
            optionStep.Add(check);
            if (!string.IsNullOrWhiteSpace(option.Warning))
            {
                Label warning = new()
                {
                    Text = $"  ! {option.Warning}",
                    X = 2,
                    Y = row++,
                    Width = Dim.Fill()
                };
                optionStep.Add(warning);
            }
        }

        WizardStep folderStep = new()
        {
            Title = "Working directory",
            HelpText = "The script path is fixed; this only controls its working directory."
        };
        Label folderLabel = new() { Text = "Directory:" };
        TextField folder = new()
        {
            X = Pos.Right(folderLabel) + 1,
            Width = Dim.Fill(11),
            Value = _root
        };
        Button browse = new()
        {
            Text = "_Browse",
            X = Pos.AnchorEnd(9)
        };
        browse.Accepted += (_, _) =>
        {
            using OpenDialog dialog = new()
            {
                Title = "Choose working directory",
                OpenMode = OpenMode.Directory,
                Path = folder.Value,
                MustExist = true
            };
            App!.Run(dialog);
            if (!dialog.Canceled && Directory.Exists(dialog.Path))
            {
                folder.Value = dialog.Path;
            }
        };
        folderStep.Add(folderLabel, folder, browse);

        WizardStep reviewStep = new()
        {
            Title = "Review",
            HelpText = script.RequiresConfirmation
                ? "Finish starts a preview. Applying always requires a second confirmation."
                : "Finish runs the script."
        };
        Label review = new()
        {
            Width = Dim.Fill(),
            Height = Dim.Fill()
        };
        reviewStep.Add(review);

        void UpdateReview()
        {
            string chosen = string.Join(
                "\n",
                checks
                    .Where(pair => pair.Value.Value == CheckState.Checked)
                    .Select(pair => $"  • {pair.Key.Label}"));
            review.Text =
                $"{script.Title}\n\n"
                + (chosen.Length == 0 ? "  Default options" : chosen)
                + $"\n\nWorking directory:\n  {folder.Value}\n\n"
                + (script.RequiresConfirmation
                    ? "Finish runs a read-only preview."
                    : "Finish runs the script.");
        }

        wizard.AddStep(optionStep);
        wizard.AddStep(folderStep);
        wizard.AddStep(reviewStep);
        wizard.StepChanged += (_, _) => UpdateReview();
        bool accepted = false;
        wizard.Accepting += (_, eventArgs) =>
        {
            if (!Directory.Exists(folder.Value))
            {
                eventArgs.Handled = true;
                MessageBox.Query(App!, "Invalid directory", "Choose an existing directory.", "OK");
                return;
            }
            accepted = true;
        };

        App!.Run(wizard);
        if (!accepted)
        {
            return null;
        }

        string workingDirectory = Path.GetFullPath(folder.Value);
        string[] options = checks
            .Where(pair => pair.Value.Value == CheckState.Checked)
            .Select(pair => pair.Key.Flag)
            .ToArray();
        return new RunSelection(script, options, workingDirectory);
    }

    private async void StartPreview(RunSelection selection)
    {
        BeginActivity(selection.Script, "Preview", applying: false);
        RunResult result = await Execute(
            selection,
            apply: false);
        App?.Invoke(() => FinishPreview(selection, result));
    }

    private async void StartDirect(RunSelection selection)
    {
        BeginActivity(
            selection.Script,
            "Run",
            applying: false);
        RunResult result = await Execute(selection, apply: false);
        App?.Invoke(() =>
        {
            AddHistory(selection.Script, "run", result);
            FinishPhase(result);
            _back.Visible = true;
        });
    }

    private void FinishPreview(RunSelection selection, RunResult result)
    {
        AddHistory(selection.Script, "preview", result);
        FinishPhase(result);
        if (result.ExitCode == 0 && !result.Cancelled && ConfirmApply(selection))
        {
            StartApply(selection);
            return;
        }
        _back.Visible = true;
    }

    private async void StartApply(RunSelection selection)
    {
        BeginActivity(selection.Script, "Apply", applying: true);
        AppendLog("\n── apply ───────────────────────────────────────────────\n");
        RunResult result = await Execute(
            selection,
            apply: true);
        App?.Invoke(() =>
        {
            AddHistory(selection.Script, "apply", result);
            FinishPhase(result);
            _back.Visible = true;
        });
    }

    private async void StartSelfTest()
    {
        ScriptSpec? script = Selected;
        if (_running || script?.IsSupported != true)
        {
            return;
        }

        RunSelection selection = new(script, [script.SelfTestFlag], _root);
        BeginActivity(script, "Self-test", applying: false);
        RunResult result = await Execute(
            selection,
            apply: false);
        App?.Invoke(() =>
        {
            AddHistory(selection.Script, "self-test", result);
            FinishPhase(result);
            _back.Visible = true;
        });
    }

    private async Task<RunResult> Execute(
        RunSelection selection,
        bool apply)
    {
        CancellationToken token = _cancellation!.Token;
        RunResult result = await ScriptRunner.RunAsync(
            selection.Script,
            selection.Options,
            apply,
            selection.WorkingDirectory,
            token,
            (line, error) =>
                App?.Invoke(() => AppendLog($"{(error ? "! " : "  ")}{line}\n")));
        return result;
    }

    private void AddHistory(ScriptSpec script, string phase, RunResult result) =>
        _history.Add(
            new RunRecord(
                DateTimeOffset.Now,
                script.Title,
                phase,
                result.ExitCode,
                result.Duration));

    private void BeginActivity(
        ScriptSpec script,
        string phase,
        bool applying)
    {
        _running = true;
        _cancellation?.Dispose();
        _cancellation = new CancellationTokenSource();
        _clock = Stopwatch.StartNew();
        _details.Title = $" {script.Title} ";
        _help.Visible = false;
        _activity.Visible = true;
        _phase.Text = $"{phase} · {script.Id}";
        _elapsed.Text = "Elapsed 00:00";
        _progress.ProgressBarStyle = ProgressBarStyle.MarqueeContinuous;
        _progress.Text = phase.ToLowerInvariant();
        _progress.Fraction = 0;
        _cancel.Enabled = !applying;
        _cancel.Visible = !applying;
        _back.Visible = false;
        if (!applying)
        {
            SetLog($"── {phase.ToLowerInvariant()} ───────────────────────────────────────────\n");
        }
        ShowSelection();
        ApplyResponsiveLayout();

        App!.AddTimeout(
            TimeSpan.FromMilliseconds(100),
            () =>
            {
                if (!_running)
                {
                    return false;
                }
                _progress.Pulse();
                _elapsed.Text = $"Elapsed {_clock!.Elapsed:mm\\:ss}";
                return true;
            });
    }

    private void FinishPhase(RunResult result)
    {
        _running = false;
        _clock?.Stop();
        _cancel.Enabled = false;
        _cancel.Visible = false;
        _progress.ProgressBarStyle = ProgressBarStyle.Blocks;
        _progress.Fraction = result.ExitCode == 0 ? 1 : 0;
        _progress.Text = result.Cancelled
            ? "cancelled"
            : result.ExitCode == 0
                ? "complete"
                : $"failed ({result.ExitCode})";
        _elapsed.Text = $"Elapsed {result.Duration:mm\\:ss}";
        AppendLog(
            $"\n{_progress.Text} in {result.Duration:mm\\:ss}\n");
        _cancellation?.Dispose();
        _cancellation = null;
        ShowSelection();
    }

    private bool ConfirmApply(RunSelection selection)
    {
        string warnings = string.Join(
            "\n",
            selection.Script.Options
                .Where(option => selection.Options.Contains(option.Flag))
                .Select(option => option.Warning)
                .Where(warning => !string.IsNullOrWhiteSpace(warning))
                .Select(warning => $"• {warning}"));
        using Dialog dialog = new()
        {
            Title = "Apply cleanup?",
            Width = Dim.Percent(76),
            Height = Dim.Percent(64),
            SchemeName = Palette.Base
        };
        Label message = new()
        {
            Text =
                "The preview completed successfully.\n\n"
                + "Applying reruns the same options and permanently deletes "
                + "matching regenerable data. Targets may have changed since "
                + "the preview."
                + (selection.Script.Platform == PlatformKind.Linux
                    ? "\n\nPrime elevation first with `sudo -v`; TUI runs never display password prompts."
                    : "")
                + (warnings.Length == 0 ? "" : $"\n\nSelected warnings:\n{warnings}")
                + "\n\nType CLEAN to enable Apply:",
            Width = Dim.Fill(),
            Height = Dim.Fill(3)
        };
        TextField confirmation = new()
        {
            Y = Pos.Bottom(message),
            Width = Dim.Fill()
        };
        Button cancel = new() { Text = "_Cancel", Y = Pos.AnchorEnd(1) };
        Button apply = new()
        {
            Text = "_Apply",
            X = Pos.Right(cancel) + 1,
            Y = Pos.AnchorEnd(1),
            Enabled = false,
            SchemeName = Palette.Accent
        };
        bool confirmed = false;
        confirmation.ValueChanged += (_, _) =>
            apply.Enabled = confirmation.Value == "CLEAN";
        cancel.Accepted += (_, _) => dialog.App?.RequestStop(dialog);
        apply.Accepted += (_, _) =>
        {
            confirmed = confirmation.Value == "CLEAN";
            dialog.App?.RequestStop(dialog);
        };
        dialog.Add(message, confirmation, cancel, apply);
        App!.Run(dialog);
        return confirmed;
    }

    private void CancelRun()
    {
        if (_running
            && _cancel.Visible
            && _cancellation?.IsCancellationRequested == false)
        {
            AppendLog("\n! cancellation requested\n");
            _cancellation.Cancel();
            _cancel.Enabled = false;
        }
    }

    private void SetLog(string text)
    {
        _log.ReadOnly = false;
        _log.Text = text;
        _log.ReadOnly = true;
        _log.MoveEnd();
    }

    private void AppendLog(string text)
    {
        _log.ReadOnly = false;
        _log.MoveEnd();
        _log.InsertText(text);
        _log.ReadOnly = true;
        _log.MoveEnd();
    }

    private void ShowBrowser()
    {
        if (_running)
        {
            return;
        }
        _activity.Visible = false;
        _help.Visible = true;
        _details.Title = " Help ";
        ApplyResponsiveLayout();
        _list.SetFocus();
    }

    private void ShowSelectedHelp()
    {
        ScriptSpec? script = Selected;
        if (script is null)
        {
            return;
        }

        using Dialog dialog = new()
        {
            Title = script.Title,
            Width = Dim.Percent(88),
            Height = Dim.Percent(88),
            SchemeName = Palette.Base
        };
        Markdown markdown = new()
        {
            Text = script.Markdown,
            Width = Dim.Fill(),
            Height = Dim.Fill(1),
            ShowCopyButtons = true
        };
        Button close = new()
        {
            Text = "_Close",
            Y = Pos.AnchorEnd(1),
            X = Pos.Center()
        };
        close.Accepted += (_, _) => dialog.App?.RequestStop(dialog);
        dialog.Add(markdown, close);
        App!.Run(dialog);
    }

    private void ShowHistory()
    {
        if (_history.Count == 0)
        {
            MessageBox.Query(App!, "Run history", "Nothing has run in this session.", "OK");
            return;
        }

        Dictionary<string, Func<RunRecord, object>> columns = new()
        {
            ["Time"] = run => run.Started.ToString("HH:mm:ss"),
            ["Script"] = run => run.Script,
            ["Phase"] = run => run.Phase,
            ["Exit"] = run => run.ExitCode,
            ["Elapsed"] = run => run.Duration.ToString("mm\\:ss")
        };
        TableView table = new(new EnumerableTableSource<RunRecord>(_history, columns))
        {
            Width = Dim.Fill(),
            Height = Dim.Fill(1)
        };
        using Dialog dialog = new()
        {
            Title = "Run history",
            Width = Dim.Percent(88),
            Height = Dim.Percent(72),
            SchemeName = Palette.Base
        };
        Button close = new()
        {
            Text = "_Close",
            Y = Pos.AnchorEnd(1),
            X = Pos.Center()
        };
        close.Accepted += (_, _) => dialog.App?.RequestStop(dialog);
        dialog.Add(table, close);
        App!.Run(dialog);
    }

    private void RequestQuit()
    {
        if (!_running)
        {
            App?.RequestStop();
            return;
        }
        if (!_cancel.Visible)
        {
            MessageBox.Query(
                App!,
                "Cleanup is running",
                "Cleanup is being applied. Wait for it to finish.",
                "OK");
            return;
        }
        if (MessageBox.Query(
                App!,
                "A script is running",
                "Cancel the run before quitting.",
                "Keep running",
                "Cancel run") == 1)
        {
            CancelRun();
        }
    }
}

internal static class ScriptCatalog
{
    private const string HelpSuffix = ".help";
    private static readonly Regex FlagPattern =
        new(@"^--?[A-Za-z][A-Za-z0-9-]*$", RegexOptions.CultureInvariant);
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow
    };

    public static IReadOnlyList<ScriptSpec> Load(string root)
    {
        List<ScriptSpec> scripts = [];
        IEnumerable<string> helpPaths = new[] { "bin", "dev", "sys" }
            .Select(directory => Path.Combine(root, directory))
            .Where(Directory.Exists)
            .SelectMany(
                directory => Directory.EnumerateFiles(
                    directory,
                    $"*{HelpSuffix}",
                    SearchOption.AllDirectories));
        foreach (string helpPath in helpPaths)
        {
            string scriptPath = helpPath[..^HelpSuffix.Length];
            string relative = Path.GetRelativePath(root, scriptPath).Replace('\\', '/');
            (ScriptMetadata metadata, string markdown) = Parse(helpPath);
            if (!File.Exists(scriptPath))
            {
                throw new InvalidDataException($"{relative}: script is missing");
            }
            if (string.IsNullOrWhiteSpace(metadata.Summary)
                || string.IsNullOrWhiteSpace(metadata.Platform)
                || metadata.Options is null)
            {
                throw new InvalidDataException(
                    $"{helpPath}: summary, platform, and options are required");
            }

            if (!Enum.TryParse(
                    metadata.Platform,
                    ignoreCase: true,
                    out PlatformKind platform)
                || !Enum.IsDefined(platform))
            {
                throw new InvalidDataException(
                    $"{helpPath}: unsupported platform {metadata.Platform}");
            }
            bool hasApply = !string.IsNullOrWhiteSpace(metadata.ApplyFlag);
            bool hasYes = !string.IsNullOrWhiteSpace(metadata.YesFlag);
            if (hasApply != hasYes)
            {
                throw new InvalidDataException(
                    $"{helpPath}: applyFlag and yesFlag must be used together");
            }
            HashSet<string> flags = new(StringComparer.OrdinalIgnoreCase);
            if (hasApply)
            {
                ValidateFlag(helpPath, metadata.ApplyFlag!);
                ValidateFlag(helpPath, metadata.YesFlag!);
                flags.Add(metadata.ApplyFlag!);
                flags.Add(metadata.YesFlag!);
            }
            foreach (OptionSpec option in metadata.Options)
            {
                ValidateFlag(helpPath, option.Flag);
                if (!flags.Add(option.Flag))
                {
                    throw new InvalidDataException(
                        $"{helpPath}: duplicate flag {option.Flag}");
                }
                if (!markdown.Contains(option.Flag, StringComparison.OrdinalIgnoreCase))
                {
                    throw new InvalidDataException(
                        $"{helpPath}: help does not mention {option.Flag}");
                }
            }
            if (!markdown.StartsWith("# ", StringComparison.Ordinal))
            {
                throw new InvalidDataException(
                    $"{helpPath}: Markdown must start with a heading");
            }

            scripts.Add(
                new ScriptSpec(
                    relative,
                    markdown.Split('\n', 2)[0][2..].Trim(),
                    metadata.Summary,
                    platform,
                    metadata.ApplyFlag,
                    metadata.YesFlag,
                    metadata.Options,
                    scriptPath,
                    markdown));
        }

        if (scripts.Count == 0)
        {
            throw new InvalidDataException("no scripts with .help pages were found");
        }
        return scripts
            .OrderByDescending(script => script.IsSupported)
            .ThenBy(script => script.Platform)
            .ThenBy(script => script.Title, StringComparer.OrdinalIgnoreCase)
            .ToArray();
    }

    private static (ScriptMetadata Metadata, string Markdown) Parse(string path)
    {
        string text = File.ReadAllText(path).Replace("\r\n", "\n");
        const string separator = "\n---\n";
        if (!text.StartsWith("---\n", StringComparison.Ordinal))
        {
            throw new InvalidDataException($"{path}: missing JSON front matter");
        }
        int end = text.IndexOf(separator, 4, StringComparison.Ordinal);
        if (end < 0)
        {
            throw new InvalidDataException($"{path}: unterminated JSON front matter");
        }

        string json = text[4..end];
        ScriptMetadata metadata = JsonSerializer.Deserialize<ScriptMetadata>(
            json,
            JsonOptions) ?? throw new InvalidDataException($"{path}: empty metadata");
        string markdown = text[(end + separator.Length)..].TrimStart();
        return (metadata, markdown);
    }

    private static void ValidateFlag(string path, string flag)
    {
        if (!FlagPattern.IsMatch(flag))
        {
            throw new InvalidDataException($"{path}: invalid flag {flag}");
        }
    }
}

internal static class ScriptRunner
{
    public static ProcessStartInfo BuildStartInfo(
        ScriptSpec script,
        IReadOnlyList<string> options,
        bool apply,
        string workingDirectory)
    {
        bool powershell = script.Path.EndsWith(
            ".ps1",
            StringComparison.OrdinalIgnoreCase);
        ProcessStartInfo start = new()
        {
            FileName = powershell ? PowerShell() : script.Path,
            WorkingDirectory = workingDirectory,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true
        };
        start.Environment["SCRIPTS_TUI"] = "1";

        if (powershell)
        {
            start.ArgumentList.Add("-NoLogo");
            start.ArgumentList.Add("-NoProfile");
            start.ArgumentList.Add("-NonInteractive");
            start.ArgumentList.Add("-ExecutionPolicy");
            start.ArgumentList.Add("Bypass");
            start.ArgumentList.Add("-File");
            start.ArgumentList.Add(script.Path);
        }
        foreach (string option in options)
        {
            start.ArgumentList.Add(option);
        }
        if (apply)
        {
            if (!script.RequiresConfirmation)
            {
                throw new InvalidOperationException(
                    $"{script.Id} has no apply workflow");
            }
            start.ArgumentList.Add(script.ApplyFlag!);
            start.ArgumentList.Add(script.YesFlag!);
        }
        return start;
    }

    public static async Task<RunResult> RunAsync(
        ScriptSpec script,
        IReadOnlyList<string> options,
        bool apply,
        string workingDirectory,
        CancellationToken cancellation,
        Action<string, bool> output)
    {
        Stopwatch clock = Stopwatch.StartNew();
        try
        {
            using Process process = new()
            {
                StartInfo = BuildStartInfo(script, options, apply, workingDirectory)
            };
            process.Start();
            using CancellationTokenRegistration registration = cancellation.Register(
                () =>
                {
                    try
                    {
                        if (!process.HasExited)
                        {
                            process.Kill(entireProcessTree: true);
                        }
                    }
                    catch (InvalidOperationException)
                    {
                        // The process exited between the check and Kill.
                    }
                    catch (System.ComponentModel.Win32Exception)
                    {
                        // The process exited or became inaccessible before Kill.
                    }
                    catch (UnauthorizedAccessException)
                    {
                        // Cancellation is best-effort if process ownership changed.
                    }
                });

            Task stdout = Pump(process.StandardOutput, false, output, cancellation);
            Task stderr = Pump(process.StandardError, true, output, cancellation);
            try
            {
                await Task.WhenAll(
                    process.WaitForExitAsync(cancellation),
                    stdout,
                    stderr);
            }
            catch (OperationCanceledException)
            {
                try
                {
                    await process.WaitForExitAsync(CancellationToken.None);
                }
                catch (InvalidOperationException)
                {
                    // Start failures are handled by the outer catch.
                }
                return new RunResult(130, true, clock.Elapsed);
            }
            return new RunResult(process.ExitCode, false, clock.Elapsed);
        }
        catch (Exception error) when (
            error is InvalidOperationException
            or System.ComponentModel.Win32Exception
            or IOException)
        {
            output($"launcher: {error.Message}", true);
            return new RunResult(127, false, clock.Elapsed);
        }
    }

    private static async Task Pump(
        StreamReader reader,
        bool error,
        Action<string, bool> output,
        CancellationToken cancellation)
    {
        while (await reader.ReadLineAsync(cancellation) is { } line)
        {
            output(line, error);
        }
    }

    private static string PowerShell()
    {
        string? systemRoot = Environment.GetEnvironmentVariable("SystemRoot");
        if (!string.IsNullOrWhiteSpace(systemRoot))
        {
            string powershell = Path.Combine(
                systemRoot,
                "System32",
                "WindowsPowerShell",
                "v1.0",
                "powershell.exe");
            if (File.Exists(powershell))
            {
                return powershell;
            }
        }
        return "pwsh";
    }
}

internal static class RootLocator
{
    public static string Find(string? requested)
    {
        if (!string.IsNullOrWhiteSpace(requested))
        {
            return Validate(requested);
        }

        foreach (string start in new[]
                 {
                     Environment.CurrentDirectory,
                     AppContext.BaseDirectory
                 })
        {
            DirectoryInfo? directory = new(Path.GetFullPath(start));
            while (directory is not null)
            {
                if (Directory.Exists(Path.Combine(directory.FullName, "sys"))
                    && File.Exists(Path.Combine(directory.FullName, "README.md")))
                {
                    return directory.FullName;
                }
                directory = directory.Parent;
            }
        }
        throw new DirectoryNotFoundException(
            "repository root not found; pass --root PATH");
    }

    private static string Validate(string path)
    {
        string root = Path.GetFullPath(path);
        if (!Directory.Exists(Path.Combine(root, "sys"))
            || !File.Exists(Path.Combine(root, "README.md")))
        {
            throw new DirectoryNotFoundException(
                $"{root} is not this scripts repository");
        }
        return root;
    }
}

internal static class SelfTest
{
    public static void Run(string root, IReadOnlyList<ScriptSpec> scripts)
    {
        if (scripts.Select(script => script.Id).Distinct().Count() != scripts.Count)
        {
            throw new InvalidDataException("script ids are not unique");
        }

        foreach (ScriptSpec script in scripts)
        {
            ProcessStartInfo preview = ScriptRunner.BuildStartInfo(
                script,
                script.Options.Select(option => option.Flag).ToArray(),
                apply: false,
                root);
            ProcessStartInfo apply = ScriptRunner.BuildStartInfo(
                script,
                [],
                apply: script.RequiresConfirmation,
                root);
            ProcessStartInfo test = ScriptRunner.BuildStartInfo(
                script,
                [script.SelfTestFlag],
                apply: false,
                root);
            if (preview.UseShellExecute
                || !preview.RedirectStandardOutput
                || preview.FileName != script.Path
                    && !preview.ArgumentList.Contains(script.Path)
                || script.RequiresConfirmation
                    && (preview.ArgumentList.Contains(script.ApplyFlag!)
                        || !apply.ArgumentList.Contains(script.ApplyFlag!)
                        || !apply.ArgumentList.Contains(script.YesFlag!))
                || !test.ArgumentList.Contains(script.SelfTestFlag))
            {
                throw new InvalidDataException(
                    $"{script.Id}: unsafe or incomplete process arguments");
            }
        }

        Console.WriteLine(
            $"self-test passed: {scripts.Count} scripts and help pages validated");
    }
}

internal static class Palette
{
    public const string Base = "Scripts";
    public const string Accent = "ScriptsAccent";

    public static void Register(ISchemeManager schemes)
    {
        Color background = new(24, 28, 38, 255);
        Color foreground = new(200, 211, 245, 255);
        Color muted = new(99, 109, 166, 255);
        Color blue = new(130, 170, 255, 255);
        Color gold = new(255, 199, 119, 255);
        Color green = new(195, 232, 141, 255);

        Scheme baseScheme = new()
        {
            Normal = new TuiAttribute(foreground, background),
            HotNormal = new TuiAttribute(gold, background),
            Focus = new TuiAttribute(background, blue),
            HotFocus = new TuiAttribute(background, gold),
            Active = new TuiAttribute(green, background),
            Highlight = new TuiAttribute(background, green),
            Editable = new TuiAttribute(foreground, background),
            ReadOnly = new TuiAttribute(muted, background),
            Disabled = new TuiAttribute(muted, background)
        };
        Scheme accentScheme = new(baseScheme)
        {
            Normal = new TuiAttribute(background, blue),
            HotNormal = new TuiAttribute(background, gold),
            Focus = new TuiAttribute(background, green),
            HotFocus = new TuiAttribute(background, gold)
        };
        schemes.AddScheme(Base, baseScheme);
        schemes.AddScheme(Accent, accentScheme);
    }
}

internal sealed record ScriptMetadata(
    string Summary,
    string Platform,
    IReadOnlyList<OptionSpec> Options,
    string? ApplyFlag = null,
    string? YesFlag = null);

internal sealed record OptionSpec(string Flag, string Label, string? Warning = null);

internal sealed record ScriptSpec(
    string Id,
    string Title,
    string Summary,
    PlatformKind Platform,
    string? ApplyFlag,
    string? YesFlag,
    IReadOnlyList<OptionSpec> Options,
    string Path,
    string Markdown)
{
    public bool IsSupported => Platform == HostPlatform.Current;
    public bool RequiresConfirmation => ApplyFlag is not null;
    public string SelfTestFlag =>
        Platform == PlatformKind.Windows ? "-SelfTest" : "--self-test";

    public override string ToString() =>
        $"{(IsSupported ? "●" : "○")} {Title} [{Platform}]";
}

internal sealed record RunSelection(
    ScriptSpec Script,
    IReadOnlyList<string> Options,
    string WorkingDirectory);

internal sealed record RunResult(int ExitCode, bool Cancelled, TimeSpan Duration);

internal sealed record RunRecord(
    DateTimeOffset Started,
    string Script,
    string Phase,
    int ExitCode,
    TimeSpan Duration);

internal enum PlatformKind
{
    Linux,
    MacOS,
    Windows
}

internal static class HostPlatform
{
    public static PlatformKind Current =>
        OperatingSystem.IsWindows()
            ? PlatformKind.Windows
            : OperatingSystem.IsMacOS()
                ? PlatformKind.MacOS
                : PlatformKind.Linux;
}
