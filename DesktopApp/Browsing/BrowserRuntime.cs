using System.Diagnostics;
using System.IO;
using Microsoft.Web.WebView2.Core;

namespace EternalVoidPanel.Browsing;

internal static class BrowserRuntime
{
    private static readonly SemaphoreSlim SetupLock = new(1, 1);
    private static Exception? setupFailure;

    // The package carries Microsoft's signed Evergreen installer. It runs only
    // when the runtime is absent, without elevation (per-user installation).
    internal static async Task EnsureAvailableAsync()
    {
        await SetupLock.WaitAsync();
        try
        {
            try { if (!string.IsNullOrEmpty(CoreWebView2Environment.GetAvailableBrowserVersionString())) return; }
            catch (WebView2RuntimeNotFoundException) { }
            if (setupFailure is not null) throw setupFailure;
            string installer = Path.Combine(AppContext.BaseDirectory, "runtime", "MicrosoftEdgeWebview2Setup.exe");
            if (!File.Exists(installer)) throw new InvalidOperationException("Microsoft WebView2 is missing. Install it from https://developer.microsoft.com/microsoft-edge/webview2/ and reopen EOG.");
            try
            {
                using var process = Process.Start(new ProcessStartInfo(installer, "/silent /install")
                {
                    UseShellExecute = false, CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden
                }) ?? throw new InvalidOperationException("Browser support setup could not start.");
                await process.WaitForExitAsync().WaitAsync(TimeSpan.FromMinutes(5));
                if (string.IsNullOrEmpty(CoreWebView2Environment.GetAvailableBrowserVersionString()))
                    throw new InvalidOperationException("Browser support setup did not finish.");
            }
            catch (Exception ex)
            {
                setupFailure = new InvalidOperationException("Browser support setup could not finish. Check your internet connection, then reopen EOG to retry.", ex);
                throw setupFailure;
            }
        }
        finally { SetupLock.Release(); }
    }
}
