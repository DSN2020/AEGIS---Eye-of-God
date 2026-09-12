using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;

namespace EternalVoidPanel;

internal sealed class NativeWindowFrame
{
    private readonly Window window;
    private readonly nint handle;
    private readonly bool nativeCorners;

    public NativeWindowFrame(Window window)
    {
        this.window = window;
        handle = new WindowInteropHelper(window).Handle;
        SetAttribute(20, 1); // DWMWA_USE_IMMERSIVE_DARK_MODE
        // Windows 11 owns the outside rounding, including shadows and resize edges.
        // https://learn.microsoft.com/windows/win32/api/dwmapi/ne-dwmapi-dwmwindowattribute
        nativeCorners = SetAttribute(33, 2); // DWMWA_WINDOW_CORNER_PREFERENCE: ROUND
        SetAttribute(34, 0x414141); // Neutral frame, independent of the Windows accent color.
        SetAttribute(35, 0x222222); // Dark caption while the WPF surface initializes.
        window.Activated += (_, _) => SetAttribute(34, 0x414141);
        window.Deactivated += (_, _) => SetAttribute(34, 0x333333);
        window.SizeChanged += (_, _) => UpdateRegion();
        window.StateChanged += (_, _) => UpdateRegion();
        window.DpiChanged += (_, _) => UpdateRegion();
        window.Loaded += (_, _) => RefreshAppearance();
        window.StateChanged += (_, _) => window.Dispatcher.BeginInvoke(RefreshAppearance);
        UpdateRegion();
    }

    private void RefreshAppearance()
    {
        SetAttribute(20,1);
        if(nativeCorners) SetAttribute(33,2);
        SetAttribute(34,window.IsActive?0x414141:0x333333);
        SetAttribute(35,0x222222);
    }

    private bool SetAttribute(int attribute, int value) =>
        DwmSetWindowAttribute(handle, attribute, ref value, sizeof(int)) >= 0;

    internal object VerifyAppearance()
    {
        if (!nativeCorners) return new { nativeCorners=false, windows10Region=true };
        int cornerResult=DwmGetWindowAttribute(handle,33,out int corners,sizeof(int));
        // BORDER_COLOR is a set-only attribute; querying it returns E_INVALIDARG.
        int border=window.IsActive?0x414141:0x333333;
        bool borderApplied=SetAttribute(34,border);
        if (cornerResult<0 || corners!=2 || !borderApplied)
            throw new InvalidOperationException($"Windows frame check failed: corners={corners} ({cornerResult:X8}), borderApplied={borderApplied}.");
        return new {nativeCorners=true,cornerPreference=corners,borderColorApplied=border.ToString("X6")};
    }

    private void UpdateRegion()
    {
        // Windows 10 has no DWM corner preference. Shape the native window there,
        // rather than leaving a square backing surface outside the rounded border.
        if (nativeCorners || window.WindowState == WindowState.Minimized) return;
        if (window.WindowState == WindowState.Maximized)
        {
            SetWindowRgn(handle, 0, true);
            return;
        }
        if (!GetWindowRect(handle, out var rect)) return;
        int diameter = (int)Math.Round(18 * GetDpiForWindow(handle) / 96.0);
        var region = CreateRoundRectRgn(0, 0, rect.Right - rect.Left + 1, rect.Bottom - rect.Top + 1, diameter, diameter);
        // SetWindowRgn takes ownership only on success.
        if (region != 0 && SetWindowRgn(handle, region, true) == 0) DeleteObject(region);
    }

    [StructLayout(LayoutKind.Sequential)] private struct Rect { public int Left, Top, Right, Bottom; }
    [DllImport("dwmapi.dll")] private static extern int DwmSetWindowAttribute(nint hwnd, int attribute, ref int value, int size);
    [DllImport("dwmapi.dll")] private static extern int DwmGetWindowAttribute(nint hwnd, int attribute, out int value, int size);
    [DllImport("user32.dll")] private static extern bool GetWindowRect(nint hwnd, out Rect rect);
    [DllImport("user32.dll")] private static extern uint GetDpiForWindow(nint hwnd);
    [DllImport("user32.dll")] private static extern int SetWindowRgn(nint hwnd, nint region, bool redraw);
    [DllImport("gdi32.dll")] private static extern nint CreateRoundRectRgn(int left, int top, int right, int bottom, int width, int height);
    [DllImport("gdi32.dll")] private static extern bool DeleteObject(nint value);
}
