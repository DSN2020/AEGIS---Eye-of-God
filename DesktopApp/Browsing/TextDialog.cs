using System.Windows;
using System.Windows.Controls;

namespace EternalVoidPanel.Browsing;

public static class TextDialog
{
    public static string? Ask(Window owner, string title, string description, string initial = "") => Show(owner, title, description, initial, false);
    public static bool Confirm(Window owner, string title, string description) => Show(owner, title, description, null, true) is not null;
    public static void Info(Window owner, string title, string description) => Show(owner, title, description, null, false);
    private static string? Show(Window owner, string title, string description, string? initial, bool confirm)
    {
        var window = new Window { Owner = owner, Title = title, Width = 480, SizeToContent = SizeToContent.Height, ResizeMode = ResizeMode.NoResize, WindowStartupLocation = WindowStartupLocation.CenterOwner };
        WindowAppearance.UseDarkTitleBar(window);
        window.Resources.MergedDictionaries.Add(new ResourceDictionary { Source = new Uri("/EOG;component/Browsing/BrowserTheme.xaml", UriKind.Relative) });
        var panel = new StackPanel { Margin = new(24) }; window.Content = panel;
        panel.Children.Add(new TextBlock { Text = title, FontSize = 20, FontWeight = FontWeights.SemiBold, Margin = new(0, 0, 0, 12) });
        panel.Children.Add(new TextBlock { Text = description, TextWrapping = TextWrapping.Wrap, Foreground = BrowserPane.Brush("#A1A1A1"), Margin = new(0, 0, 0, 18), LineHeight = 21 });
        TextBox? input = null;
        if (initial is not null) { input = new TextBox { Text = initial, Margin = new(0, 0, 0, 18) }; panel.Children.Add(input); window.Loaded += (_, _) => { input.Focus(); input.SelectAll(); }; }
        var buttons = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right };
        if (initial is not null || confirm) { var cancel = new Button { Content = "Cancel", IsCancel = true, Margin = new(0, 0, 8, 0), MinWidth = 82 }; buttons.Children.Add(cancel); }
        var accept = new Button { Content = confirm ? "Continue" : initial is null ? "Got it" : "Save", IsDefault = true, MinWidth = 82 };
        accept.Click += (_, _) => window.DialogResult = true; buttons.Children.Add(accept); panel.Children.Add(buttons);
        return window.ShowDialog() == true ? input?.Text ?? "ok" : null;
    }
}
