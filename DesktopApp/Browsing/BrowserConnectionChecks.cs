using System.IO;
using System.Text;
using Microsoft.Web.WebView2.Core;

namespace EternalVoidPanel.Browsing;

internal static class BrowserConnectionChecks
{
    internal static async Task RunAsync(BrowserPane pane, string root, Action<bool, string> check)
    {
        var core = pane.Browser.CoreWebView2;
        string pages = Path.Combine(root, "connection-fixture"); Directory.CreateDirectory(pages);
        const string endpoint = "https://master.eternal-void.online/auth/eog-local-test";
        await File.WriteAllTextAsync(Path.Combine(pages, "connection.html"), $$"""
            <!doctype html><title>Connection recovery fixture</title>
            <script>
            localStorage.setItem('saved-session','retained');
            sessionStorage.setItem('loads',String(Number(sessionStorage.getItem('loads')||0)+1));
            fetch('{{endpoint}}').then(r=>{document.body.textContent=r.ok?'Connected':'Server error';});
            </script><body>Connecting</body>
            """);
        bool healthy = false, allowCors = true; int requests = 0;
        var streams = new List<MemoryStream>();
        void Respond(object? sender, CoreWebView2WebResourceRequestedEventArgs e)
        {
            if (e.Request.Uri != endpoint) return;
            requests++;
            var stream = new MemoryStream(Encoding.UTF8.GetBytes("{}")); streams.Add(stream);
            e.Response = core.Environment.CreateWebResourceResponse(stream, healthy ? 200 : 520,
                healthy ? "OK" : "Server error", "Content-Type: application/json\r\nCache-Control: no-store" + (allowCors ? "\r\nAccess-Control-Allow-Origin: https://eternal-void.online" : ""));
        }
        core.SetVirtualHostNameToFolderMapping("eternal-void.online", pages, CoreWebView2HostResourceAccessKind.DenyCors);
        core.AddWebResourceRequestedFilter(endpoint, CoreWebView2WebResourceContext.All);
        core.WebResourceRequested += Respond;
        try
        {
            core.Navigate("https://eternal-void.online/connection.html");
            await Until(() => pane.HasConnectionFailure);
            check(pane.HasConnectionFailure, "A real HTTP 520 response exposes the pane's reconnect action");
            await Task.Delay(1500);
            check(requests == 1, "Server failure does not create a login or reload retry loop");
            healthy = true; pane.Reconnect();
            for (int i = 0; i < 150; i++) {
                if (await pane.Browser.ExecuteScriptAsync("document.body.textContent==='Connected'") == "true") break;
                await Task.Delay(100);
            }
            check(await pane.Browser.ExecuteScriptAsync("document.body.textContent==='Connected' && localStorage.getItem('saved-session')==='retained' && sessionStorage.getItem('loads')==='2'") == "true",
                "Reconnect recovers the page after server recovery and preserves saved session storage");
            check(!pane.HasConnectionFailure && requests == 2, "Successful reconnect clears the notice with one additional request");
            allowCors = false;
            await pane.Browser.ExecuteScriptAsync($"fetch('{endpoint}').catch(()=>{{}})");
            await Until(() => pane.HasConnectionFailure);
            check(pane.HasConnectionFailure, "Missing server cross-origin headers expose reconnect without weakening browser security");
            allowCors = true; pane.Reconnect();
            for (int i = 0; i < 150; i++) {
                if (await pane.Browser.ExecuteScriptAsync("document.body.textContent==='Connected' && sessionStorage.getItem('loads')==='3'") == "true") break;
                await Task.Delay(100);
            }
            check(!pane.HasConnectionFailure && requests == 4 && await pane.Browser.ExecuteScriptAsync("document.body.textContent==='Connected' && sessionStorage.getItem('loads')==='3'") == "true",
                "Reconnect also recovers after the server's cross-origin headers are repaired");
        }
        finally
        {
            core.WebResourceRequested -= Respond;
            core.RemoveWebResourceRequestedFilter(endpoint, CoreWebView2WebResourceContext.All);
            core.ClearVirtualHostNameToFolderMapping("eternal-void.online");
            foreach (var stream in streams) stream.Dispose();
        }
    }
    private static async Task Until(Func<bool> condition)
    {
        for (int i = 0; i < 150; i++) { if (condition()) return; await Task.Delay(100); }
        throw new TimeoutException("Connection recovery check timed out.");
    }
}
