using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using Microsoft.Web.WebView2.Core;

namespace EternalVoidPanel.Browsing;

// Exercises real WebView2 profiles against one loopback origin. Never uses personal browser data.
internal static class BrowserChecks
{
    public static async Task<int> RunAsync(BrowserWorkspace window, string dataRoot, Action<bool> selectBrowsers)
    {
        string artifacts = Path.Combine(AppContext.BaseDirectory, "ui-review", "browsers");
        Directory.CreateDirectory(artifacts);
        var log = new List<string>();
        using var server = new LocalPage();
        try
        {
            Check(window.Panes.All(p => p.Browser.CoreWebView2 is not null), "All six browser engines initialized", log);
            Check(window.Panes.Select(p => p.Browser.CoreWebView2.Environment.UserDataFolder).Distinct(StringComparer.OrdinalIgnoreCase).Count() == 6, "Six different actual browser data folders", log);
            Check(BrowserPane.ResolveAddress("example.com") == "https://example.com/", "Bare host navigation", log);
            Check(BrowserPane.ResolveAddress("localhost:5081") == "http://localhost:5081/", "Localhost with port navigation", log);
            Check(BrowserPane.ResolveAddress("two words").Contains("q=two%20words"), "Search input encoding", log);
            foreach (var pane in window.Panes)
            {
                await Load(pane, server.Url);
                string key = "pane" + pane.Index;
                await Script(pane, $$"""
                    document.cookie='isolation={{key}}; max-age=86400; path=/';
                    localStorage.setItem('isolation','{{key}}'); sessionStorage.setItem('isolation','{{key}}');
                    const db=await new Promise((resolve,reject)=>{let r=indexedDB.open('check',1);r.onupgradeneeded=()=>r.result.createObjectStore('values');r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error)});
                    await new Promise((resolve,reject)=>{let t=db.transaction('values','readwrite');t.objectStore('values').put('{{key}}','isolation');t.oncomplete=resolve;t.onerror=()=>reject(t.error)});db.close();
                    const cache=await caches.open('check');await cache.put('/isolation',new Response('{{key}}'));return true;
                    """);
            }
            foreach (var pane in window.Panes)
            {
                var actual = await ReadStorage(pane);
                string expected = "pane" + pane.Index;
                Check(actual.Cookie == "isolation=" + expected && actual.Local == expected && actual.Session == expected && actual.Indexed == expected && actual.Cache == expected,
                    $"Pane {pane.Index + 1}: cookie, localStorage, sessionStorage, IndexedDB and Cache Storage isolated", log);
            }
            var engines = window.Panes.Select(p => p.Browser.CoreWebView2).ToArray();
            selectBrowsers(false); window.UpdateLayout();
            Check(window.Visibility == Visibility.Collapsed, "Sidebar switch hides the browser workspace", log);
            selectBrowsers(true); await window.EnsureStartedAsync(); window.UpdateLayout();
            Check(window.Visibility == Visibility.Visible && window.Panes.Select((p, i) => ReferenceEquals(p.Browser.CoreWebView2, engines[i])).All(x => x), "Returning from another EOG section preserves all six browser engines", log);
            Check((await ReadStorage(window.Panes[2])).Session == "pane2", "Sidebar navigation preserves page sessionStorage", log);
            window.ToggleFocus(window.Panes[3]); window.UpdateLayout();
            Check(window.Panes.Count(p => p.Visibility == Visibility.Visible) == 1, "Focus view shows one pane", log);
            window.SetRows(2); window.UpdateLayout();
            Check(window.Panes.All(p => p.Visibility == Visibility.Visible) && System.Windows.Controls.Grid.GetRow(window.Panes[5]) == 2, "Two rows show every open browser", log);
            window.SetRows(1); window.UpdateLayout();
            Check(window.Panes.All(p => System.Windows.Controls.Grid.GetRow(p) == 0 && p.Visibility == Visibility.Visible), "One row puts every browser side by side", log);
            window.SetPaneWidth(300); window.UpdateLayout();
            Check(window.Panes.All(p => Math.Abs(p.ActualWidth - 300) < 1), "All panes use the selected mobile width", log);
            var viewport = await window.Panes[0].Browser.ExecuteScriptAsync("JSON.stringify([innerWidth,innerHeight])");
            window.SetPaneWidth(420); window.UpdateLayout(); await Task.Delay(200);
            window.SetPaneWidth(260); window.UpdateLayout(); await Task.Delay(200);
            Check(await window.Panes[0].Browser.ExecuteScriptAsync("JSON.stringify([innerWidth,innerHeight])") == viewport,
                "Resizing preserves the loaded game's mobile viewport", log);
            Check(window.Panes.All(p => {
                var bounds = p.Browser.TransformToAncestor(p).TransformBounds(new Rect(0, 0, p.Browser.ActualWidth, p.Browser.ActualHeight));
                return bounds.Left >= 0 && bounds.Top >= 0 && bounds.Right <= p.ActualWidth + 1 && bounds.Bottom <= p.ActualHeight + 1;
            }), "The complete mobile screen fits inside every resized pane", log);
            window.FitToWindow(); window.UpdateLayout();
            Check(window.MobileWidth >= BrowserWorkspace.MinimumPaneWidth && window.Panes.All(p => p.ActualWidth >= BrowserWorkspace.MinimumPaneWidth), "Fit preserves the minimum playable width", log);
            window.Panes[0].SetMuted(true);
            Check(window.Panes[0].Browser.CoreWebView2.IsMuted && window.Panes.Skip(1).All(p => !p.Browser.CoreWebView2.IsMuted), "Mute affects only the selected browser", log);
            window.SetRows(2); window.SwapPanes(5, 1); window.UpdateLayout();
            Check(window.PaneOrder.SequenceEqual(new[] {0,5,2,3,4,1}), "Rearrangement follows profile IDs in a dynamic layout", log);
            Check((await ReadStorage(window.Panes[5])).Session == "pane5" && window.Panes.Select((p, i) => ReferenceEquals(p.Browser.CoreWebView2, engines[i])).All(x => x), "Rearranging preserves engines, sessions and profiles", log);
            window.ToggleFocus(window.Panes[0]); window.SetAllMuted(true);
            Check(window.Panes.All(p => p.Browser.CoreWebView2.IsMuted && p.State.Muted), "Mute all includes browsers hidden by expand", log);
            await Task.Delay(1000);
            var saved = WorkspaceState.Load(dataRoot);
            Check(saved.Rows == 2 && saved.Order.SequenceEqual(new[] {0,5,2,3,4,1}) && saved.Panes.All(p => p.Muted), "Arrangement, rows, width and mute preferences persist", log);
            window.SetAllMuted(false); window.Panes[0].SetMuted(true);
            window.ShowAll(); window.SwapPanes(5, 1);
            foreach (var pane in window.Panes)
            {
                await pane.RestartAsync(); await Load(pane, server.Url);
                var actual = await ReadStorage(pane);
                Check(actual.Cookie == "isolation=pane" + pane.Index && actual.Local == "pane" + pane.Index && actual.Indexed == "pane" + pane.Index && actual.Cache == "pane" + pane.Index,
                    $"Pane {pane.Index + 1}: persistent data survives browser close/reopen", log);
            }
            Check(window.Panes[0].Browser.CoreWebView2.IsMuted, "Mute survives browser restart", log);
            window.SetAllMuted(false);
            var first = window.Panes[0];
            await first.Browser.CoreWebView2.Profile.ClearBrowsingDataAsync(); await Load(first, server.Url);
            var cleared = await ReadStorage(first);
            Check(cleared.Cookie == "" && cleared.Local is null && cleared.Indexed is null && cleared.Cache is null, "Clear data removes pane 1 persistent storage", log);
            var other = await ReadStorage(window.Panes[1]);
            Check(other.Cookie == "isolation=pane1" && other.Local == "pane1", "Clearing pane 1 preserves pane 2 session", log);
            first.State.Temporary = true; await first.RestartAsync(); await Load(first, server.Url);
            await Script(first, "document.cookie='temporary=one; path=/';localStorage.setItem('temporary','one');return true;");
            first.State.Temporary = false; await first.RestartAsync(); await Load(first, server.Url);
            Check(await first.Browser.ExecuteScriptAsync("localStorage.getItem('temporary')") == "null", "Temporary storage does not leak into saved profile", log);
            first.State.Temporary = true; await first.RestartAsync(); await Load(first, server.Url);
            Check(await first.Browser.ExecuteScriptAsync("localStorage.getItem('temporary')") == "null", "Temporary data is discarded after session closes", log);
            first.State.Temporary = false; await first.RestartAsync();

            // A real window.open must get the originating pane's profile and cookie.
            var second = window.Panes[1];
            await second.Browser.ExecuteScriptAsync("window.open('" + server.Url + "popup','isolation-popup')");
            BrowserPane? popupPane = null;
            await Until(async () => { popupPane = Window.GetWindow(window).OwnedWindows.Cast<Window>().Select(w => w.Content).OfType<BrowserPane>().FirstOrDefault(); return popupPane?.Browser?.CoreWebView2 is not null && await popupPane.Browser.ExecuteScriptAsync("location.pathname") == "\"/popup\""; });
            Check(await popupPane!.Browser.ExecuteScriptAsync("document.cookie") == "\"isolation=pane1\"", "Popup inherits originating pane's session", log);
            Check(popupPane.Browser.CoreWebView2.Environment.UserDataFolder == second.Browser.CoreWebView2.Environment.UserDataFolder, "Popup stays in originating data folder", log);
            second.SetMuted(true);
            Check(second.Browser.CoreWebView2.IsMuted && popupPane.Browser.CoreWebView2.IsMuted && !window.Panes[2].Browser.CoreWebView2.IsMuted, "Mute includes existing popups without affecting another profile", log);
            popupPane.SetMuted(false);
            Check(!second.Browser.CoreWebView2.IsMuted && !popupPane.Browser.CoreWebView2.IsMuted && !second.State.Muted, "Unmute from a popup synchronizes the parent browser", log);
            foreach (Window popup in Window.GetWindow(window).OwnedWindows.Cast<Window>().ToArray()) popup.Close();
            var loadedViewport = await window.Panes[0].Browser.ExecuteScriptAsync("JSON.stringify([innerWidth,innerHeight])");
            var seventh = (await window.AddBrowserAsync().WaitAsync(TimeSpan.FromSeconds(30)))!;
            await Load(seventh, server.Url);
            Check(window.Panes.Count == 7 && seventh.Index == 6 && (await ReadStorage(seventh)).Cookie == "", "Plus opens a seventh independent browser with a fresh profile", log);
            window.SetRows(2); window.UpdateLayout();
            Check(window.Panes.All(p => p.Visibility == Visibility.Visible) && window.Panes.Select(System.Windows.Controls.Grid.GetRow).Distinct().Count() == 2, "Odd browser counts distribute across two rows", log);
            Check(window.Panes.All(p => Math.Abs(p.ActualWidth - seventh.ActualWidth) <= 1)
                && await window.Panes[0].Browser.ExecuteScriptAsync("JSON.stringify([innerWidth,innerHeight])") == loadedViewport,
                "Adding a browser fits older and new panes equally without changing the loaded game layout", log);
            window.FitToWindow(); window.UpdateLayout();
            var widthWithSeven = window.MobileWidth;
            var removed = window.Panes.First(p => p.Index == 1);
            var oldCore = removed.Browser.CoreWebView2;
            window.ClosePane(removed);
            bool disposed = false;
            try { await oldCore.ExecuteScriptAsync("1").WaitAsync(TimeSpan.FromSeconds(3)); }
            catch (TimeoutException) { throw; }
            catch { disposed = true; }
            Check(disposed && window.Panes.Count == 6 && window.Panes.All(p => p.Index != 1), "Closing stops and removes the selected browser instance", log);
            window.UpdateLayout();
            Check(window.MobileWidth >= widthWithSeven && window.Panes.All(p => Math.Abs(p.ActualWidth - window.MobileWidth) <= 1), "Auto fit resizes existing panes after closing an instance", log);
            await Task.Delay(1000);
            Check(!WorkspaceState.Load(dataRoot).Panes[1].IsOpen, "Closed instances stay closed after app restart", log);
            var restored = (await window.AddBrowserAsync())!;
            await Load(restored, server.Url);
            Check(restored.Index == 1 && (await ReadStorage(restored)).Cookie == "isolation=pane1", "Plus restores the recently closed profile and its login cookie", log);
            window.ClosePane(seventh);
            await BrowserAccountChecks.RunAsync(window, dataRoot, (ok, name) => Check(ok, name, log));
            window.SetRows(2); window.FitToWindow(); window.UpdateLayout();
            foreach (var pane in window.Panes) pane.Home();
            foreach (var pane in window.Panes)
                await Until(async () => (await pane.Browser.ExecuteScriptAsync("document.readyState === 'complete' && document.querySelector('h1')?.textContent === " + JsonSerializer.Serialize(pane.State.Name))) == "true");
            await Capture(window, Path.Combine(artifacts, "workspace.png"));
            window.ToggleFocus(window.Panes[0]); window.UpdateLayout();
            await Capture(window, Path.Combine(artifacts, "focused.png"));
            window.ShowAll();
            window.SetRows(1); window.FitToWindow(); window.UpdateLayout();
            await Capture(window, Path.Combine(artifacts, "one-row.png"));
            window.ShowAll();
            foreach (var pane in window.Panes.ToArray()) window.ClosePane(pane);
            window.UpdateLayout();
            Check(window.Panes.Count == 0, "All instances can close without losing saved profiles", log);
            var reopened = await window.AddBrowserAsync();
            Check(reopened is not null && window.Panes.Count == 1, "Plus works from the empty workspace", log);
            log.Add("PASS: Rendered mobile workspace, focused view and one-row previews");
            log.Add("Test data only: " + dataRoot);
            await File.WriteAllLinesAsync(Path.Combine(artifacts, "checks.txt"), log);
            return 0;
        }
        catch (Exception ex)
        {
            log.Add("FAIL: " + ex);
            await File.WriteAllLinesAsync(Path.Combine(artifacts, "checks.txt"), log);
            return 1;
        }
    }
    private static void Check(bool condition, string name, List<string> log)
    {
        if (!condition) throw new InvalidOperationException(name);
        log.Add("PASS: " + name);
        File.WriteAllLines(Path.Combine(AppContext.BaseDirectory, "ui-review", "browsers", "checks.txt"), log);
    }
    private static async Task Until(Func<Task<bool>> condition)
    {
        var end = DateTime.UtcNow.AddSeconds(25);
        while (DateTime.UtcNow < end) { try { if (await condition().WaitAsync(TimeSpan.FromSeconds(2))) return; } catch { } await Task.Delay(100); }
        throw new TimeoutException("Browser check timed out.");
    }
    private static async Task Load(BrowserPane pane, string url)
    {
        pane.Browser.CoreWebView2.Navigate(url);
        await Until(async () => await pane.Browser.ExecuteScriptAsync("location.href === " + JsonSerializer.Serialize(url) + " && document.readyState === 'complete' && document.title === 'Isolation check'") == "true");
    }
    private static async Task<JsonElement> Script(BrowserPane pane, string body)
    {
        // ExecuteScriptAsync does not await JS promises. Poll a completion slot instead.
        string id = "check_" + Guid.NewGuid().ToString("N");
        await pane.Browser.ExecuteScriptAsync("window." + id + "=null;(async()=>{" + body + "})().then(value=>window." + id + "={ok:true,value},error=>window." + id + "={ok:false,error:String(error)});");
        string result = "null";
        await Until(async () => { result = await pane.Browser.ExecuteScriptAsync("window." + id); return result != "null"; });
        using var doc = JsonDocument.Parse(result);
        if (!doc.RootElement.GetProperty("ok").GetBoolean()) throw new Exception(doc.RootElement.GetProperty("error").GetString());
        return doc.RootElement.GetProperty("value").Clone();
    }
    private sealed record Storage(string Cookie, string? Local, string? Session, string? Indexed, string? Cache);
    private static async Task<Storage> ReadStorage(BrowserPane pane)
    {
        var json = await Script(pane, """
            const db=await new Promise((resolve,reject)=>{let r=indexedDB.open('check',1);r.onupgradeneeded=()=>r.result.createObjectStore('values');r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error)});
            const value=await new Promise((resolve,reject)=>{let r=db.transaction('values').objectStore('values').get('isolation');r.onsuccess=()=>resolve(r.result??null);r.onerror=()=>reject(r.error)});db.close();
            const cache=await caches.open('check');const response=await cache.match('/isolation');
            return {Cookie:document.cookie,Local:localStorage.getItem('isolation'),Session:sessionStorage.getItem('isolation'),Indexed:value,Cache:response?await response.text():null};
            """);
        return json.Deserialize<Storage>()!;
    }
    private static async Task Capture(BrowserWorkspace workspace, string path)
    {
        workspace.UpdateLayout();
        await Task.Delay(300);
        var host = Window.GetWindow(workspace);
        var bitmap = new RenderTargetBitmap((int)host.ActualWidth, (int)host.ActualHeight, 96, 96, PixelFormats.Pbgra32);
        bitmap.Render(host);
        var encoder = new PngBitmapEncoder(); encoder.Frames.Add(BitmapFrame.Create(bitmap));
        using var file = File.Create(path); encoder.Save(file);
    }
    private sealed class LocalPage : IDisposable
    {
        private readonly TcpListener listener = new(IPAddress.Loopback, 0);
        private readonly CancellationTokenSource stop = new();
        public string Url { get; }
        public LocalPage() { listener.Start(); Url = $"http://127.0.0.1:{((IPEndPoint)listener.LocalEndpoint).Port}/"; _ = Serve(); }
        private async Task Serve()
        {
            try
            {
                while (!stop.IsCancellationRequested)
                {
                    var client = await listener.AcceptTcpClientAsync(stop.Token);
                    _ = Reply(client, stop.Token);
                }
            }
            catch (OperationCanceledException) { }
            catch (ObjectDisposedException) { }
        }
        private static async Task Reply(TcpClient client, CancellationToken token)
        {
            // Chromium can preconnect without sending a request; it must not block other profiles.
            using (client)
            using (var timeout = CancellationTokenSource.CreateLinkedTokenSource(token))
            {
                timeout.CancelAfter(TimeSpan.FromSeconds(5));
                try
                {
                    using var stream = client.GetStream(); using var reader = new StreamReader(stream, leaveOpen: true);
                    while (!string.IsNullOrEmpty(await reader.ReadLineAsync(timeout.Token))) { }
                    const string html = "<!doctype html><title>Isolation check</title><body>Local isolation test</body>";
                    byte[] response = Encoding.UTF8.GetBytes("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nCache-Control: no-store\r\nConnection: close\r\nContent-Length: " + Encoding.UTF8.GetByteCount(html) + "\r\n\r\n" + html);
                    await stream.WriteAsync(response, timeout.Token);
                }
                catch (OperationCanceledException) { }
                catch (IOException) { }
            }
        }
        public void Dispose() { stop.Cancel(); listener.Stop(); stop.Dispose(); }
    }
}
