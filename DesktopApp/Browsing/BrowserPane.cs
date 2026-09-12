using System.IO;
using System.Net;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.Wpf;

namespace EternalVoidPanel.Browsing;

public sealed partial class BrowserPane : Border, IDisposable
{
    public readonly int Index;
    public readonly PaneState State;
    public WebView2CompositionControl Browser { get; private set; } = null!;
    public string DataFolder { get; }
    public event Action<BrowserPane>? FocusRequested;
    public event Action<BrowserPane>? CloseRequested;
    public event Action<BrowserPane>? AccountRequested;
    public event Action<BrowserPane>? FillLoginRequested;
    internal FrameworkElement DragHandle { get; private set; } = null!;
    public event Action? StateChanged;
    private readonly Grid body = new();
    // Keep the game's layout viewport stable; scale the complete phone screen as panes change.
    internal const double MobileViewportWidth = 470, MobileViewportHeight = 912;
    private readonly Viewbox mobileScreen = new() { Stretch = Stretch.Uniform, StretchDirection = StretchDirection.Both };
    private readonly Grid nav = new() { Visibility = Visibility.Collapsed };
    private readonly RowDefinition statusRow = new() { Height = new(0) };
    private readonly TextBox address = new();
    private readonly TextBlock title = new() { TextTrimming = TextTrimming.CharacterEllipsis, VerticalAlignment = VerticalAlignment.Center };
    private readonly TextBlock status = new() { FontSize = 10, Foreground = Brush("#A1A1A1"), TextTrimming = TextTrimming.CharacterEllipsis };
    private readonly Button back, forward, reload, focus, mute;
    private readonly BrowserAudioGroup audio;
    private readonly Border dropCover = new() { Background = Brush("#21191C"), BorderBrush = Brush("#78404C"), BorderThickness = new(1), Visibility = Visibility.Collapsed };
    private readonly List<Window> popups = [];
    private readonly string root;
    private bool disposed, busy, loading;
    public Task Ready { get; private set; } = Task.CompletedTask;
    public static SolidColorBrush Brush(string hex) => new((Color)ColorConverter.ConvertFromString(hex));

    public BrowserPane(int index, PaneState state, string dataRoot) : this(index, state, dataRoot, new BrowserAudioGroup(state.Muted)) { }
    internal BrowserPane(int index, PaneState state, string dataRoot, BrowserAudioGroup audioGroup)
    {
        Index = index; State = state; root = dataRoot; audio = audioGroup;
        DataFolder = Path.Combine(root, "Profiles", $"Browser{index + 1:00}");
        Background = Brush("#222222"); BorderBrush = Brush("#363636"); BorderThickness = new(1); CornerRadius = new(9); Padding = new(1);
        var layout = new Grid(); Child = layout;
        layout.RowDefinitions.Add(new() { Height = GridLength.Auto });
        layout.RowDefinitions.Add(new() { Height = GridLength.Auto });
        layout.RowDefinitions.Add(new() { Height = new(1, GridUnitType.Star) });
        layout.RowDefinitions.Add(statusRow);
        layout.RowDefinitions.Add(new() { Height = GridLength.Auto });
        BuildConnectionNotice(layout);
        var heading = new Grid { Margin = new(6, 3, 3, 3) };
        heading.ColumnDefinitions.Add(new() { Width = new(1, GridUnitType.Star) }); heading.ColumnDefinitions.Add(new() { Width = GridLength.Auto });
        title.FontWeight = FontWeights.SemiBold;
        var dragArea = new Border { Background = Brushes.Transparent, Cursor = Cursors.SizeAll, ToolTip = "Drag this header onto another browser to swap positions", Padding = new(0, 3, 4, 3) };
        var dragLabel = new DockPanel();
        dragLabel.Children.Add(new TextBlock { Text = "⠿", FontFamily = new("Segoe UI Symbol"), Foreground = Brush("#777777"), Margin = new(0, 0, 6, 0), VerticalAlignment = VerticalAlignment.Center });
        dragLabel.Children.Add(title); dragArea.Child = dragLabel; heading.Children.Add(dragArea); DragHandle = dragArea;
        var actions = new StackPanel { Orientation = Orientation.Horizontal }; Grid.SetColumn(actions, 1); heading.Children.Add(actions);
        actions.Children.Add(Button("\uE713", "Assistant controls", (_, _) => AssistantRequested?.Invoke(this)));
        mute = Button("\uE767", "Mute browser", (_, _) => SetMuted(!State.Muted)); actions.Children.Add(mute);
        actions.Children.Add(Button("\uE774", "Show / hide address bar", (_, _) => { if (nav.Visibility == Visibility.Visible) nav.Visibility = Visibility.Collapsed; else FocusAddress(); }));
        actions.Children.Add(Button("\uE72C", "Refresh this browser", (_, _) => { if (!AssistantControlled) Browser?.CoreWebView2?.Reload(); }));
        focus = Button("\uE740", "Maximize this pane", (_, _) => FocusRequested?.Invoke(this)); actions.Children.Add(focus);
        actions.Children.Add(Button("\uE712", "Browser options", OpenMenu)); layout.Children.Add(heading);
        var closeButton = new Button { Content = "−", Width = 24, MinHeight = 26, Padding = new(0), Background = Brushes.Transparent, BorderThickness = new(0), ToolTip = "Close this browser. Saved login is kept.", FontSize = 16 };
        System.Windows.Automation.AutomationProperties.SetName(closeButton, $"Close browser {Index + 1}");
        closeButton.Click += (_, _) => CloseRequested?.Invoke(this); actions.Children.Add(closeButton);
        nav.Margin = new(4, 0, 4, 4); Grid.SetRow(nav, 1); layout.Children.Add(nav);
        nav.ColumnDefinitions.Add(new() { Width = GridLength.Auto }); nav.ColumnDefinitions.Add(new() { Width = new(1, GridUnitType.Star) });
        var controls = new StackPanel { Orientation = Orientation.Horizontal }; nav.Children.Add(controls);
        back = Button("\uE72B", "Back", (_, _) => { if (Browser?.CoreWebView2?.CanGoBack == true) Browser.GoBack(); }); controls.Children.Add(back);
        forward = Button("\uE72A", "Forward", (_, _) => { if (Browser?.CoreWebView2?.CanGoForward == true) Browser.GoForward(); }); controls.Children.Add(forward);
        reload = Button("\uE72C", "Reload / stop loading", (_, _) => { if (loading) Browser?.CoreWebView2?.Stop(); else Browser?.CoreWebView2?.Reload(); }); controls.Children.Add(reload);
        address.FontSize = 11.5; address.MinWidth = 40; address.Tag = "Search or enter address"; address.ToolTip = "Enter a website or search, then press Enter"; address.Margin = new(4, 0, 0, 0);
        address.KeyDown += (_, e) => { if (e.Key == Key.Enter) { Navigate(address.Text); nav.Visibility = Visibility.Collapsed; Browser?.Focus(); e.Handled = true; } };
        address.GotKeyboardFocus += (_, _) => address.SelectAll();
        address.LostKeyboardFocus += (_, _) => { if (Browser?.CoreWebView2 is { } core) address.Text = core.Source == "about:blank" ? "" : core.Source; };
        address.PreviewMouseLeftButtonDown += (_, e) => { if (!address.IsKeyboardFocusWithin) { address.Focus(); e.Handled = true; } };
        Grid.SetColumn(address, 1); nav.Children.Add(address);
        Grid.SetRow(body, 2); layout.Children.Add(body);
        status.Margin = new(10, 3, 10, 0); Grid.SetRow(status, 3); layout.Children.Add(status);
        dropCover.Child = new TextBlock { Text = "Drop here to swap", HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center, FontSize = 16, Foreground = Brush("#ECECEC") };
        UpdateHeading(); SetStatus("Starting browser…"); audio.Register(this);
    }
    private static Button Button(string glyph, string hint, RoutedEventHandler action)
    {
        var button = new Button { Content = new TextBlock { Text = glyph, FontFamily = new("Segoe MDL2 Assets"), FontSize = 12 }, FontFamily = new("Segoe MDL2 Assets"), FontSize = 12, Width = 24, MinHeight = 26, Padding = new(0), Background = Brushes.Transparent, BorderThickness = new(0), ToolTip = hint };
        System.Windows.Automation.AutomationProperties.SetName(button, hint); button.Click += action; return button;
    }
    public Task InitializeAsync(bool navigate = true) => Ready = InitializeCoreAsync(navigate);
    private async Task InitializeCoreAsync(bool navigate)
    {
        busy = true;
        try
        {
            SetStatus("Preparing browser support · first setup may take a moment…");
            await BrowserRuntime.EnsureAvailableAsync();
            if (disposed) return;
            Browser = new WebView2CompositionControl { Width = MobileViewportWidth, Height = MobileViewportHeight, DefaultBackgroundColor = System.Drawing.Color.FromArgb(13, 13, 13), CreationProperties = new CoreWebView2CreationProperties { UserDataFolder = DataFolder, ProfileName = "Default", IsInPrivateModeEnabled = State.Temporary, AdditionalBrowserArguments = $"--disable-quic --remote-debugging-address=127.0.0.1 --remote-debugging-port={DebugPort}" } };
            mobileScreen.Child = Browser;
            body.Children.Clear(); body.Children.Add(mobileScreen); body.Children.Add(dropCover);
            await Browser.EnsureCoreWebView2Async();
            if (disposed) return;
            var core = Browser.CoreWebView2;
            core.Profile.PreferredColorScheme = CoreWebView2PreferredColorScheme.Dark;
            var downloads = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Downloads", "EOG Browsers", $"Browser{Index + 1:00}");
            Directory.CreateDirectory(downloads); core.Profile.DefaultDownloadFolderPath = downloads;
            core.Settings.IsStatusBarEnabled = false;
            core.IsMuted = State.Muted; Browser.ZoomFactor = State.Zoom;
            core.IsMutedChanged += (_, _) => { if (core.IsMuted != State.Muted) SetMuted(core.IsMuted); };
            core.NavigationStarting += (_, _) => { ClearConnectionFailure(); loading = true; reconnect.IsEnabled = false; ((TextBlock)reload.Content).Text = "\uE711"; SetStatus("Loading…"); };
            core.NavigationCompleted += (_, e) => { loading = false; reconnect.IsEnabled = !AssistantControlled; ((TextBlock)reload.Content).Text = "\uE72C"; SetStatus(e.IsSuccess ? SessionLabel : $"Page failed to load: {e.WebErrorStatus} · Try refresh"); };
            core.HistoryChanged += (_, _) => { back.IsEnabled = !AssistantControlled && core.CanGoBack; forward.IsEnabled = !AssistantControlled && core.CanGoForward; };
            core.SourceChanged += (_, _) =>
            {
                string url = core.Source;
                if (!address.IsKeyboardFocusWithin) address.Text = url == "about:blank" ? "" : url;
                if (!State.Temporary) { State.Url = url == "about:blank" ? "" : url; StateChanged?.Invoke(); }
            };
            core.DocumentTitleChanged += (_, _) => { title.ToolTip = core.DocumentTitle; };
            core.NewWindowRequested += OnNewWindow;
            core.ProcessFailed += (_, _) => { SetStatus("Browser stopped. Use Restart browser in options."); };
            Browser.ZoomFactorChanged += (_, _) => { State.Zoom = Browser.ZoomFactor; StateChanged?.Invoke(); };
            back.IsEnabled = false; forward.IsEnabled = false;
            await WatchConnectionsAsync(core);
            if (disposed) return;
            if (navigate) { if (!State.Temporary && !string.IsNullOrWhiteSpace(State.Url)) Navigate(State.Url); else Home(); }
            SetStatus(SessionLabel);
        }
        catch (Exception ex)
        {
            SetStatus("Browser could not start");
            var error = new TextBlock { Text = "This browser could not start.\n\n" + ex.Message + "\n\nInstall Microsoft Edge WebView2 Runtime if it is missing, then use Restart browser in options.", TextWrapping = TextWrapping.Wrap, Margin = new(24), VerticalAlignment = VerticalAlignment.Center };
            body.Children.Clear(); body.Children.Add(error);
            throw;
        }
        finally { busy = false; }
    }
    public string SessionLabel => State.Temporary ? "Temporary session · Cleared when closed" : "Saved session · Separate cookies & storage";
    private void SetStatus(string value) { status.Text = value; status.ToolTip = value; statusRow.Height = new(value == SessionLabel || value is "Loading…" or "Starting browser…" ? 0 : 22); }
    private void UpdateHeading() { title.Text = string.IsNullOrWhiteSpace(State.Account) ? $"{Index + 1:00}   {State.Name}" : State.Account; }
    internal void AssignAccount(string account)
    {
        State.Account = account.Trim();
        State.Name = State.Account.Length > 0 ? State.Account : $"Browser {Index + 1:00}";
        UpdateHeading(); StateChanged?.Invoke();
    }
    public void SetMuted(bool value) => audio.SetMuted(value);
    internal void ApplyMute(bool value)
    {
        bool changed = State.Muted != value;
        State.Muted = value;
        if (Browser?.CoreWebView2 is { } core && core.IsMuted != value) core.IsMuted = value;
        ((TextBlock)mute.Content).Text = value ? "\uE74F" : "\uE767";
        ((TextBlock)mute.Content).Foreground = Brush(value ? "#FF8BA1" : "#D0D0D0");
        mute.ToolTip = value ? "Sound is off. Click to unmute this browser and its popups." : "Mute this browser and its popups";
        mute.Background = Brush(value ? "#382027" : "#202020");
        mute.BorderBrush = Brush(value ? "#786269" : "#454545");
        System.Windows.Automation.AutomationProperties.SetName(mute, $"{(value ? "Unmute" : "Mute")} browser {Index + 1}");
        if (changed) StateChanged?.Invoke();
    }
    internal void ShowDropTarget(bool show)
    {
        // Composition rendering allows a WPF drop surface above the live page.
        if (Browser is not null) Browser.IsHitTestVisible = !show && !AssistantControlled;
        dropCover.Visibility = show ? Visibility.Visible : Visibility.Collapsed;
    }
    internal void HighlightDropTarget(bool highlight) => dropCover.Background = Brush(highlight ? "#44222C" : "#21191C");
    public void SetFocused(bool value) { ((TextBlock)focus.Content).Text = value ? "\uE73F" : "\uE740"; focus.ToolTip = value ? "Show all browsers" : "Maximize this pane"; BorderBrush = Brush(value ? "#78404C" : "#363636"); }
    public void FocusAddress() { nav.Visibility = Visibility.Visible; address.Focus(); address.SelectAll(); }
    public static string ResolveAddress(string input)
    {
        input = input.Trim();
        if (input.Length == 0) return "about:blank";
        if (input == "about:blank") return input;
        if (Uri.TryCreate(input, UriKind.Absolute, out var absolute) && absolute.Scheme is "http" or "https") return absolute.AbsoluteUri;
        if (!input.Any(char.IsWhiteSpace) && (input.Contains('.') || input.StartsWith("localhost", StringComparison.OrdinalIgnoreCase) || input.StartsWith("[::1]")))
        {
            string scheme = input.StartsWith("localhost", StringComparison.OrdinalIgnoreCase) || input.StartsWith("127.") || input.StartsWith("[::1]") ? "http://" : "https://";
            if (Uri.TryCreate(scheme + input, UriKind.Absolute, out var host) && host.Host.Length > 0) return host.AbsoluteUri;
        }
        return "https://www.google.com/search?q=" + Uri.EscapeDataString(input);
    }
    public void Navigate(string input)
    {
        if(AssistantControlled) { SetStatus("Take control before navigating this browser"); return; }
        if (Browser?.CoreWebView2 is null) return;
        try { var url = ResolveAddress(input); if (url == "about:blank") Home(); else Browser.CoreWebView2.Navigate(url); }
        catch (Exception ex) { SetStatus("Could not open address: " + ex.Message); }
    }
    public void Home()
    {
        if(AssistantControlled) return;
        if (Browser?.CoreWebView2 is null) return;
        address.Text = "";
        string name = WebUtility.HtmlEncode(State.Name);
        Browser.CoreWebView2.NavigateToString($$"""
            <!doctype html><html><head><meta name="color-scheme" content="dark"><meta name="viewport" content="width=device-width,initial-scale=1"><style>
            *{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0d0d0d;color:#f2f2f2;font:14px 'Segoe UI',sans-serif}main{max-width:390px;padding:26px;width:100%}.eyebrow{font-size:10px;color:#868686;letter-spacing:2px}.mark{display:grid;grid-template-columns:repeat(3,10px);gap:4px;margin-bottom:18px}.mark i{height:10px;background:#323232;border-radius:2px}.mark i:first-child{background:#ff0034}h1{font-size:25px;font-weight:600;margin:10px 0}p{color:#929292;line-height:1.65;font-size:12px;margin-bottom:22px}form{display:flex;gap:7px}input{width:100%;min-width:0;background:#181818;color:#f2f2f2;border:1px solid #333;border-radius:7px;padding:11px;outline:none}input:focus{border-color:#666}button{background:#252525;color:#eee;border:1px solid #3b3b3b;border-radius:7px;padding:8px 13px;cursor:pointer}footer{margin-top:18px;color:#707070;font-size:10px}
            @media(max-height:330px){main{padding:18px 24px}.mark{margin-bottom:12px}h1{font-size:22px;margin:8px 0}p{margin:8px 0 14px}footer{margin-top:12px} }@media(max-height:230px){.mark,footer{display:none}main{padding:14px 24px}p{margin-bottom:10px} }
            </style></head><body><main><div class="mark"><i></i><i></i><i></i><i></i><i></i><i></i></div><div class="eyebrow">YOUR OWN SESSION · {{Index + 1:00}}</div><h1>{{name}}</h1><p>Make room for another account.<br>This browser keeps its cookies and website storage separate.</p><form action="https://www.google.com/search"><input name="q" aria-label="Search the web" placeholder="Search the web"><button>Go</button></form><footer>{{WebUtility.HtmlEncode(SessionLabel)}}</footer></main></body></html>
            """);
    }
    private async void OnNewWindow(object? sender, CoreWebView2NewWindowRequestedEventArgs e)
    {
        e.Handled = true;
        using var deferral = e.GetDeferral();
        BrowserPane? pane = null; Window? popup = null;
        try
        {
            pane = new BrowserPane(Index, new PaneState { Name = State.Name, Temporary = State.Temporary, Muted = State.Muted, Zoom = State.Zoom }, root, audio);
            popup = new Window { Title = $"{State.Name} · EOG Browsers", Width = 960, Height = 740, MinWidth = 460, MinHeight = 360, Owner = Window.GetWindow(this), Content = pane };
            WindowAppearance.UseDarkTitleBar(popup);
            popup.Resources.MergedDictionaries.Add(new ResourceDictionary { Source = new Uri("/EOG;component/Browsing/BrowserTheme.xaml", UriKind.Relative) });
            var captured = popup; var capturedPane = pane;
            pane.CloseRequested += _ => captured.Close();
            popup.Closed += (_, _) => { popups.Remove(captured); capturedPane.Dispose(); };
            popups.Add(popup); popup.Show();
            await pane.InitializeAsync(false);
            e.NewWindow = pane.Browser.CoreWebView2;
            pane.Browser.CoreWebView2.WindowCloseRequested += (_, _) => captured.Close();
        }
        catch (Exception ex) { popup?.Close(); pane?.Dispose(); SetStatus("Could not open popup: " + ex.Message); }
    }
    private void OpenMenu(object sender, RoutedEventArgs e)
    {
        if(AssistantControlled) { AssistantRequested?.Invoke(this); return; }
        var menu = new ContextMenu();
        void Add(string label, Action action) { var item = new MenuItem { Header = label }; item.Click += (_, _) => action(); menu.Items.Add(item); }
        Add("Start page", Home);
        if (AccountRequested is not null) Add("Assign account…", () => AccountRequested.Invoke(this));
        if (!string.IsNullOrWhiteSpace(State.Account) && FillLoginRequested is not null) Add($"Fill login for {State.Account}", () => FillLoginRequested.Invoke(this));
        if (string.IsNullOrWhiteSpace(State.Account)) Add("Rename browser…", () => { var name = TextDialog.Ask(Window.GetWindow(this), "Rename browser", "Choose a name for this session.", State.Name); if (!string.IsNullOrWhiteSpace(name)) { State.Name = name.Trim(); UpdateHeading(); StateChanged?.Invoke(); } });
        Add(State.Muted ? "Unmute browser" : "Mute browser", () => SetMuted(!State.Muted));
        menu.Items.Add(new Separator());
        Add($"Zoom in ({State.Zoom:P0})", () => { if (Browser is not null) Browser.ZoomFactor = Math.Min(3, Browser.ZoomFactor + .1); });
        Add("Zoom out", () => { if (Browser is not null) Browser.ZoomFactor = Math.Max(.25, Browser.ZoomFactor - .1); });
        Add("Reset zoom", () => { if (Browser is not null) Browser.ZoomFactor = 1; });
        menu.Items.Add(new Separator());
        Add(State.Temporary ? "Switch to saved session…" : "Switch to temporary session…", async () =>
        {
            if (busy || !TextDialog.Confirm(Window.GetWindow(this), "Switch session?", "This closes this pane’s current pages and popups. Your saved session remains available when you switch back.")) return;
            State.Temporary = !State.Temporary; await RestartAsync(); StateChanged?.Invoke();
        });
        Add("Clear this browser’s data…", async () =>
        {
            if (busy || Browser?.CoreWebView2 is null || !TextDialog.Confirm(Window.GetWindow(this), "Clear browser data?", "Cookies, website storage, cache, history and saved passwords for this session will be removed. You will be signed out of its websites. Other browsers are unaffected.")) return;
            try { foreach (var popup in popups.ToArray()) popup.Close(); Browser.CoreWebView2.Stop(); await Browser.CoreWebView2.Profile.ClearBrowsingDataAsync(); State.Url = ""; StateChanged?.Invoke(); Home(); SetStatus("Browser data cleared"); }
            catch (Exception ex) { SetStatus("Could not clear data: " + ex.Message); }
        });
        Add("Restart browser", async () => await RestartAsync());
        menu.PlacementTarget = (Button)sender; menu.IsOpen = true;
    }
    public async Task RestartAsync()
    {
        if(AssistantControlled) { SetStatus("Take control before restarting this browser"); return; }
        if (busy || disposed) return;
        foreach (var popup in popups.ToArray()) popup.Close();
        Browser?.Dispose();
        try { await InitializeAsync(); } catch { /* Startup error is displayed in this pane. */ }
    }
    public void Dispose()
    {
        AssistantRevoked?.Invoke(this);
        if (disposed) return; disposed = true;
        foreach (var popup in popups.ToArray()) popup.Close(); audio.Unregister(this); Browser?.Dispose();
    }
}
