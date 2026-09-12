using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace EternalVoidPanel.Browsing;

internal sealed class BrowserAccountsDialog : Window
{
    private readonly List<(BrowserPane Pane, ComboBox Account, PasswordBox Password)> rows = [];
    private readonly TextBlock message = new() { TextWrapping = TextWrapping.Wrap, Foreground = BrowserPane.Brush("#B7B7B7"), Margin = new(0, 10, 0, 10) };

    public BrowserAccountsDialog(BrowserWorkspace workspace, BrowserPane[] panes, BrowserAccountStore store, BrowserPane? selected)
    {
        Owner = Window.GetWindow(workspace); Title = "Browser accounts"; Width = 850; Height = Math.Min(650, 270 + panes.Length * 80);
        Background = BrowserPane.Brush("#181818"); Foreground = BrowserPane.Brush("#ECECEC"); FontFamily = new FontFamily("Segoe UI"); FontSize = 12;
        MinWidth = 760; MinHeight = 350; WindowStartupLocation = WindowStartupLocation.CenterOwner;
        WindowAppearance.UseDarkTitleBar(this);
        Resources.MergedDictionaries.Add(new ResourceDictionary { Source = new Uri("/EOG;component/Browsing/BrowserTheme.xaml", UriKind.Relative) });
        var layout = new DockPanel { Margin = new(24) }; Content = layout;
        var heading = new StackPanel(); DockPanel.SetDock(heading, Dock.Top); layout.Children.Add(heading);
        heading.Children.Add(new TextBlock { Text = "Browser accounts", FontSize = 23, FontWeight = FontWeights.SemiBold });
        heading.Children.Add(new TextBlock { Text = "Choose a saved account or type a new username. Browser titles follow the assigned account.", TextWrapping = TextWrapping.Wrap, Foreground = BrowserPane.Brush("#A5A5A5"), Margin = new(0, 8, 0, 8) });
        heading.Children.Add(new TextBlock { Text = "Blank password keeps the saved login. Browser passwords are protected by Windows; scanner settings stay unchanged.", TextWrapping = TextWrapping.Wrap, Foreground = BrowserPane.Brush("#A5A5A5"), Margin = new(0, 0, 0, 18) });
        var footer = new StackPanel(); DockPanel.SetDock(footer, Dock.Bottom); layout.Children.Add(footer);
        footer.Children.Add(message);
        var buttons = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right }; footer.Children.Add(buttons);
        var close = new Button { Content = "Close", IsCancel = true, Margin = new(0, 0, 8, 0) }; buttons.Children.Add(close);
        var save = new Button { Content = "Save assignments", IsDefault = true }; buttons.Children.Add(save);
        var list = new StackPanel(); layout.Children.Add(new ScrollViewer { VerticalScrollBarVisibility = ScrollBarVisibility.Auto, Content = list });
        string[] names = store.Names.Concat(panes.Select(p => p.State.Account)).Where(n => !string.IsNullOrWhiteSpace(n)).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
        foreach (var pane in panes)
        {
            var row = new Grid { Margin = new(0, 0, 0, 12) };
            foreach (var width in new[] { new GridLength(110), new GridLength(1, GridUnitType.Star), new GridLength(210), new GridLength(92) }) row.ColumnDefinitions.Add(new() { Width = width });
            row.Children.Add(new TextBlock { Text = $"Browser {pane.Index + 1:00}", VerticalAlignment = VerticalAlignment.Center, Foreground = BrowserPane.Brush("#A5A5A5") });
            var accountPanel = new StackPanel { Margin = new(0, 0, 12, 0) }; Grid.SetColumn(accountPanel, 1); row.Children.Add(accountPanel);
            accountPanel.Children.Add(new TextBlock { Text = "Account", Foreground = BrowserPane.Brush("#999999"), FontSize = 11, Margin = new(0, 0, 0, 5) });
            var account = new ComboBox { IsEditable = true, ItemsSource = names, Text = pane.State.Account, MinHeight = 34, IsTextSearchEnabled = false };
            accountPanel.Children.Add(account);
            var savedLabel = new TextBlock { Foreground = BrowserPane.Brush("#999999"), FontSize = 10, Margin = new(0, 4, 0, 0) }; accountPanel.Children.Add(savedLabel);
            var passwordPanel = new StackPanel { Margin = new(0, 0, 12, 0) }; Grid.SetColumn(passwordPanel, 2); row.Children.Add(passwordPanel);
            passwordPanel.Children.Add(new TextBlock { Text = "Password · blank keeps saved", Foreground = BrowserPane.Brush("#999999"), FontSize = 11, Margin = new(0, 0, 0, 5) });
            var password = new PasswordBox { MinHeight = 34, Padding = new(8), Background = BrowserPane.Brush("#222222"), Foreground = Brushes.White, BorderBrush = BrowserPane.Brush("#3A3A3A") };
            passwordPanel.Children.Add(password); rows.Add((pane, account, password));
            void UpdateSaved()
            {
                try { savedLabel.Text = password.Password.Length > 0 ? "Ready to save" : string.IsNullOrWhiteSpace(account.Text) ? "No account assigned" : string.IsNullOrEmpty(store.Password(account.Text.Trim())) ? "No saved password" : "Saved password available"; }
                catch { savedLabel.Text = "Saved password unavailable"; }
            }
            account.AddHandler(TextBox.TextChangedEvent, new TextChangedEventHandler((_, _) => UpdateSaved()));
            password.PasswordChanged += (_, _) => UpdateSaved(); UpdateSaved();
            var fill = new Button { Content = "Fill login", VerticalAlignment = VerticalAlignment.Bottom, MinHeight = 34, ToolTip = "Save assignments and fill this browser's game login screen. You press LOG IN in the game." }; Grid.SetColumn(fill, 3); row.Children.Add(fill);
            fill.Click += async (_, _) =>
            {
                if (!Save()) return;
                fill.IsEnabled = false;
                try { message.Text = await workspace.FillAccountLoginAsync(pane); }
                finally { fill.IsEnabled = true; }
            };
            list.Children.Add(row);
            if (selected == pane) Loaded += (_, _) => { account.BringIntoView(); account.Focus(); };
        }
        if (panes.Length == 0) message.Text = "Add a browser, then assign its account here.";
        save.IsEnabled = panes.Length > 0;
        save.Click += (_, _) => { if (Save()) message.Text = "Assignments saved. Browser titles now match the accounts. Saved sessions were kept."; };
        bool Save()
        {
            try
            {
                workspace.SaveAccounts(rows.Select(r => (r.Pane, r.Account.Text.Trim(), r.Password.Password)));
                foreach (var row in rows) row.Password.Clear();
                return true;
            }
            catch (Exception ex) { message.Text = ex.Message; return false; }
        }
        Closed += (_, _) => { foreach (var row in rows) row.Password.Clear(); };
    }
}
