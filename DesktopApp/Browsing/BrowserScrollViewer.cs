using System.Windows.Controls;
using System.Windows.Input;

namespace EternalVoidPanel.Browsing;

// The workspace must not steal focus or navigation keys from embedded pages.
public sealed class BrowserScrollViewer : ScrollViewer
{
    public BrowserScrollViewer() { Focusable = false; }
    protected override void OnKeyDown(KeyEventArgs e) { }
}
