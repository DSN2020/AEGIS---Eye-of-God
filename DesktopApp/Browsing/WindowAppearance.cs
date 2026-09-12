using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;

namespace EternalVoidPanel.Browsing;

internal static class WindowAppearance
{
    [DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attribute, ref int value, int size);

    public static void UseDarkTitleBar(Window window)
    {
        window.SourceInitialized += (_, _) =>
        {
            int enabled = 1;
            DwmSetWindowAttribute(new WindowInteropHelper(window).Handle, 20, ref enabled, sizeof(int));
        };
    }
}
