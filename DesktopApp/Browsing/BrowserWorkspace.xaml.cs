using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Threading;

namespace EternalVoidPanel.Browsing;

public partial class BrowserWorkspace : UserControl, IDisposable
{
    public List<BrowserPane> Panes { get; } = [];
    private readonly WorkspaceState state;
    private readonly string root;
    private readonly DispatcherTimer saveTimer = new() { Interval = TimeSpan.FromMilliseconds(750) };
    private int focused = -1;
    private bool closed, ready, syncingWidth;
    private Task? startup;
    internal string DataRoot => root;
    internal bool HasStarted => startup is not null;

    public BrowserWorkspace()
    {
        InitializeComponent();
        bool verification = Environment.GetCommandLineArgs().Any(a => a is "--verify-browsers" or "--preview-ui" or "--verify-ui" or "--smoke-test");
        root = verification ? Path.Combine(Path.GetTempPath(), "EOGBrowserChecks", Guid.NewGuid().ToString("N"))
            : Environment.GetEnvironmentVariable("EOG_BROWSER_DATA_ROOT") ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "AnispoBrowser");
        state = WorkspaceState.Load(root);
        accountStore = new BrowserAccountStore(root);
        foreach (int index in state.Order.Where(i => state.Panes[i].IsOpen)) CreatePane(index);
        saveTimer.Tick += (_, _) => { saveTimer.Stop(); Save(); };
        WidthSlider.Value = state.PaneWidth;
        ready = true; BuildLayout();
        BrowserScroll.ScrollChanged += (_, e) => { if (e.ViewportWidthChange != 0 || e.ViewportHeightChange != 0) UpdateCanvasSize(); };
        BrowserScroll.PreviewDragOver += ScrollDuringDrag;
        PreviewKeyDown += (_, e) =>
        {
            if (e.Key == Key.Escape && focused >= 0) { ShowAll(); e.Handled = true; }
            if (Keyboard.Modifiers == ModifierKeys.Control && e.Key == Key.L && Panes.Count > 0)
            {
                var active = Panes.FirstOrDefault(p => p.IsKeyboardFocusWithin) ?? Panes.FirstOrDefault(p => p.Index == focused) ?? OrderedPanes().First();
                active.FocusAddress(); e.Handled = true;
            }
        };
    }
    private BrowserPane CreatePane(int index)
    {
        var pane = new BrowserPane(index, state.Panes[index], root);
        pane.FocusRequested += ToggleFocus; pane.StateChanged += QueueSave; pane.CloseRequested += ClosePane;
        pane.AccountRequested += ShowAccounts; pane.FillLoginRequested += FillLogin;
        pane.AssistantRequested += ShowAssistant; pane.AssistantRevoked += RevokeAssistant;
        ConfigureDragSource(pane.DragHandle, pane); ConfigureDropTarget(pane); Panes.Add(pane);
        return pane;
    }
    private IEnumerable<BrowserPane> OrderedPanes() => state.Order.Select(id => Panes.FirstOrDefault(p => p.Index == id)).OfType<BrowserPane>();
    public Task EnsureStartedAsync() => closed ? Task.CompletedTask : startup ??= StartAsync();
    private async Task StartAsync()
    {
        bool failed = false;
        // Stagger saved game pages instead of loading every game's assets and
        // account connections in the same burst when opening a large workspace.
        foreach (var pane in OrderedPanes().ToArray()) {
            if (closed) return;
            if (!Panes.Contains(pane)) continue;
            failed |= !await StartPaneAsync(pane);
            if (pane != OrderedPanes().LastOrDefault()) await Task.Delay(1200);
        }
        if (!closed && failed) StatusText.Text = "Some browsers could not start. Check their messages or restart them in options.";
    }
    private static async Task<bool> StartPaneAsync(BrowserPane pane)
    {
        try { await pane.InitializeAsync(); return true; }
        catch { return false; } // Recoverable startup errors are displayed inside the pane.
    }
    public async Task<BrowserPane?> AddBrowserAsync(bool newProfile = false)
    {
        if (closed) return null;
        int index = newProfile ? -1 : Enumerable.Range(0, state.Panes.Length).Where(i => !state.Panes[i].IsOpen).OrderByDescending(i => state.Panes[i].ClosedAt).DefaultIfEmpty(-1).First();
        if (index < 0)
        {
            index = state.Panes.Length;
            var entry = new PaneState { Name = $"Browser {index + 1:00}", Muted = Panes.Count > 0 && Panes.All(p => p.State.Muted) };
            state.Panes = [.. state.Panes, entry]; state.Order = [.. state.Order, index];
        }
        state.Panes[index].IsOpen = true; state.Panes[index].ClosedAt = 0;
        var pane = CreatePane(index); focused = -1; BuildLayout(); QueueSave();
        await StartPaneAsync(pane);
        return pane;
    }
    public void ClosePane(BrowserPane pane)
    {
        if (!Panes.Contains(pane)) return;
        pane.State.IsOpen = false; pane.State.ClosedAt = DateTime.UtcNow.Ticks;
        pane.FocusRequested -= ToggleFocus; pane.StateChanged -= QueueSave; pane.CloseRequested -= ClosePane;
        pane.AccountRequested -= ShowAccounts; pane.FillLoginRequested -= FillLogin;
        Panes.Remove(pane); BrowserGrid.Children.Remove(pane); pane.Dispose();
        if (focused == pane.Index) focused = -1;
        BuildLayout(); QueueSave();
    }
    public void CloseLastBrowser()
    {
        var pane = Panes.FirstOrDefault(p => p.Index == focused) ?? OrderedPanes().LastOrDefault();
        if (pane is not null) ClosePane(pane);
    }
    public void Dispose()
    {
        if (closed) return;
        closed = true; saveTimer.Stop();
        assistantTimer.Stop();
        if (HasStarted) Save();
        foreach (var pane in Panes.ToArray()) pane.Dispose();
    }
    private void OneRow_Click(object sender, RoutedEventArgs e) => SetRows(1);
    private void TwoRows_Click(object sender, RoutedEventArgs e) => SetRows(2);
    private void Restore_Click(object sender, RoutedEventArgs e) => ShowAll();
    private async void Add_Click(object sender, RoutedEventArgs e) => await AddBrowserAsync();
    private void Remove_Click(object sender, RoutedEventArgs e) => CloseLastBrowser();
    private void Width_Changed(object sender, RoutedPropertyChangedEventArgs<double> e) { if (ready && !syncingWidth) SetPaneWidth(e.NewValue); }
    private void Fit_Click(object sender, RoutedEventArgs e) => FitToWindow();
    private void Viewport_Changed(object sender, SizeChangedEventArgs e) { if (ready) UpdateCanvasSize(); }
    private void MuteAll_Click(object sender, RoutedEventArgs e) => SetAllMuted(!Panes.All(p => p.State.Muted));
    public void SetAllMuted(bool value) { foreach (var pane in Panes.ToArray()) pane.SetMuted(value); RefreshControlLabels(); }
    private void OpenAll_Click(object sender, RoutedEventArgs e)
    {
        if (Panes.Count == 0) return;
        var url = TextDialog.Ask(Window.GetWindow(this), $"Open in all {Panes.Count} browsers", "Enter a website or search. Each open browser will use its own session.");
        if (!string.IsNullOrWhiteSpace(url)) foreach (var pane in Panes.ToArray()) pane.Navigate(url);
    }
    private void Help_Click(object sender, RoutedEventArgs e) => TextDialog.Info(Window.GetWindow(this), "Mobile browser workspace",
        "1 row puts every open browser alongside the others. 2 rows divides them evenly.\n\nUse + to add and − to close. Each header also has its own −. Saved logins stay on this PC; + reopens the most recently closed profile first.\n\nAuto fit adjusts all panes when adding, closing or resizing. The Mobile width slider switches to manual sizing. Each complete mobile screen scales to its pane without cropping. Extra browsers scroll horizontally.\n\nAccounts assigns a username and names its browser. Choose a saved scanner account or enter a separate password. Blank keeps the saved password. Assigning keeps the current page and session. Open the game’s login screen, then use Fill login to fill the assigned credentials; press LOG IN in the game yourself.\n\nDrag headers to swap positions. The globe button opens the address bar; Enter hides it again. Expand a browser for more room. The speaker buttons and Mute all include popups.");
}
