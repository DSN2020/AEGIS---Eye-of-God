using System.Net;
using System.Net.Sockets;
using System.Text.Json;

namespace EternalVoidPanel.Browsing;

public sealed partial class BrowserPane
{
    private static readonly Dictionary<string,int> DebugPorts = new(StringComparer.OrdinalIgnoreCase);
    internal bool AssistantControlled { get; private set; }
    internal event Action<BrowserPane>? AssistantRequested;
    internal event Action<BrowserPane>? AssistantRevoked;
    internal int DebugPort {
        get {
            if (!DebugPorts.TryGetValue(DataFolder, out int port)) {
                var socket = new TcpListener(IPAddress.Loopback,0); socket.Start();
                port=((IPEndPoint)socket.LocalEndpoint).Port; socket.Stop(); DebugPorts[DataFolder]=port;
            }
            return port;
        }
    }
    internal async Task<string> AssistantTargetAsync()
    {
        await Ready;
        if (!IsGamePage || State.Temporary) throw new InvalidOperationException("Open Eternal Void in a saved browser session first.");
        var json=await Browser.CoreWebView2.CallDevToolsProtocolMethodAsync("Target.getTargetInfo","{}");
        using var doc=JsonDocument.Parse(json);
        return doc.RootElement.GetProperty("targetInfo").GetProperty("targetId").GetString()!;
    }
    internal void SetAssistantControl(bool enabled,string message="")
    {
        AssistantControlled=enabled;
        if (Browser is not null) { Browser.IsHitTestVisible=!enabled; Browser.IsEnabled=!enabled; }
        reload.IsEnabled=!enabled; address.IsEnabled=!enabled;
        back.IsEnabled=!enabled && Browser?.CoreWebView2?.CanGoBack==true;
        forward.IsEnabled=!enabled && Browser?.CoreWebView2?.CanGoForward==true;
        UpdateHeading();
        if(enabled) title.Text+=" · ASSISTANT";
        SetStatus(enabled ? (message.Length>0 ? message : "Assistant enabled · Use Assistant → Take control to interact") : "Manual control · Assistant off");
    }
}
