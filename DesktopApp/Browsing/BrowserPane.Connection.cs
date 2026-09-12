using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using Microsoft.Web.WebView2.Core;

namespace EternalVoidPanel.Browsing;

public sealed partial class BrowserPane
{
    private readonly TextBlock connectionText = new() { TextWrapping = TextWrapping.Wrap, FontSize = 11, VerticalAlignment = VerticalAlignment.Center };
    private readonly Button reconnect = new() { Content = "Reconnect", Padding = new(8, 4, 8, 4), MinHeight = 28, Margin = new(8, 0, 0, 0) };
    private readonly Border connectionNotice = new() { Background = Brush("#35282B"), CornerRadius = new(6), Padding = new(8), Margin = new(4), Visibility = Visibility.Collapsed };
    private readonly Dictionary<string, string> connectionRequests = [];
    internal bool HasConnectionFailure => connectionNotice.Visibility == Visibility.Visible;

    private void BuildConnectionNotice(Grid layout)
    {
        var contents = new DockPanel();
        DockPanel.SetDock(reconnect, Dock.Right); contents.Children.Add(reconnect); contents.Children.Add(connectionText);
        connectionNotice.Child = contents; Grid.SetRow(connectionNotice, 4); layout.Children.Add(connectionNotice);
        reconnect.Click += (_, _) => Reconnect();
    }

    internal void Reconnect()
    {
        if (disposed || busy || loading || AssistantControlled || !IsGamePage) return;
        // Reload only on an explicit click. Never loop login submissions or reload
        // a player's active game automatically after a background request fails.
        ClearConnectionFailure();
        Browser.CoreWebView2.Reload();
    }

    private void ClearConnectionFailure()
    {
        connectionNotice.Visibility = Visibility.Collapsed;
        connectionRequests.Clear();
    }

    private void ConnectionFailed(string message)
    {
        if (disposed || !IsGamePage) return;
        connectionText.Text = message; connectionText.ToolTip = message;
        reconnect.IsEnabled = !loading && !AssistantControlled;
        connectionNotice.Visibility = Visibility.Visible;
    }

    private static string ConnectionService(string url)
    {
        if (!Uri.TryCreate(url, UriKind.Absolute, out var uri) || !uri.IsDefaultPort || uri.Scheme is not ("https" or "wss")) return "";
        if (uri.Host == "master.eternal-void.online" && uri.AbsolutePath.StartsWith("/auth/", StringComparison.Ordinal)) return "Account server";
        if (uri.Host.EndsWith(".eternal-void.online", StringComparison.Ordinal) && uri.AbsolutePath.StartsWith("/socket.io/", StringComparison.Ordinal)) return "Game server";
        return "";
    }

    private async Task WatchConnectionsAsync(CoreWebView2 core)
    {
        connectionRequests.Clear();
        core.WebResourceResponseReceived += (_, e) => {
            if (disposed || Browser?.CoreWebView2 != core) return;
            string service = ConnectionService(e.Request.Uri);
            if (service.Length == 0) return;
            int code = e.Response.StatusCode;
            if (code >= 500) ConnectionFailed($"{service} error {code}. Reconnect to try again.");
            else if (code == 429) ConnectionFailed($"{service} is limiting requests. Wait a moment before reconnecting.");
        };
        void Observe(string name, Action<JsonElement> handle)
        {
            core.GetDevToolsProtocolEventReceiver(name).DevToolsProtocolEventReceived += (_, e) => {
                if (disposed || Browser?.CoreWebView2 != core) return;
                try { using var json = JsonDocument.Parse(e.ParameterObjectAsJson); handle(json.RootElement); }
                catch (JsonException) { } // Monitoring must never interrupt browsing.
            };
        }
        void Track(JsonElement e, string url)
        {
            string service = ConnectionService(url);
            if (service.Length == 0) return;
            if (connectionRequests.Count >= 256) connectionRequests.Clear();
            connectionRequests[e.GetProperty("requestId").GetString()!] = service;
        }
        Observe("Network.requestWillBeSent", e => Track(e, e.GetProperty("request").GetProperty("url").GetString()!));
        Observe("Network.webSocketCreated", e => Track(e, e.GetProperty("url").GetString()!));
        Observe("Network.loadingFinished", e => connectionRequests.Remove(e.GetProperty("requestId").GetString()!));
        Observe("Network.loadingFailed", e => {
            if (!connectionRequests.Remove(e.GetProperty("requestId").GetString()!, out string? service)) return;
            if (e.TryGetProperty("canceled", out var canceled) && canceled.GetBoolean()) return;
            ConnectionFailed($"{service} connection failed. Reconnect to try again.");
        });
        Observe("Network.webSocketFrameError", e => {
            if (connectionRequests.ContainsKey(e.GetProperty("requestId").GetString()!))
                ConnectionFailed("Game connection interrupted. Reconnect to try again.");
        });
        Observe("Network.webSocketClosed", e => connectionRequests.Remove(e.GetProperty("requestId").GetString()!));
        try { await core.CallDevToolsProtocolMethodAsync("Network.enable", "{}").WaitAsync(TimeSpan.FromSeconds(3)); }
        catch (Exception) { /* HTTP monitoring and manual refresh remain available. */ }
    }
}
