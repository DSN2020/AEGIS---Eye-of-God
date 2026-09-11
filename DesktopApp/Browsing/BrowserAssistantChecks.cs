using System.Diagnostics;
using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace EternalVoidPanel.Browsing;

internal static class BrowserAssistantChecks
{
    internal static async Task<int> RunAsync(BrowserWorkspace workspace)
    {
        string output=Path.Combine(AppContext.BaseDirectory,"ui-review","assistant");Directory.CreateDirectory(output);
        try {
            if(workspace.Panes.Any(p=>p.AssistantControlled))throw new Exception("A browser started with control enabled");
            var pane=workspace.Panes[0];var other=workspace.Panes[1];
            var info=await pane.Browser.CoreWebView2.CallDevToolsProtocolMethodAsync("Target.getTargetInfo","{}");
            string target=JsonDocument.Parse(info).RootElement.GetProperty("targetInfo").GetProperty("targetId").GetString()!;
            pane.SetAssistantControl(true);
            if(pane.Browser.IsEnabled)throw new Exception("Manual keyboard input was not disabled");
            string fixture=Path.Combine(output,"connection.json");
            await File.WriteAllTextAsync(fixture,JsonSerializer.Serialize(new {port=pane.DebugPort,targetId=target,otherPort=other.DebugPort}));
            var directory=new DirectoryInfo(AppContext.BaseDirectory);
            while(directory is not null&&!File.Exists(Path.Combine(directory.FullName,"app_bridge.py")))directory=directory.Parent;
            string root=directory!.FullName;
            string python=JsonDocument.Parse(await File.ReadAllTextAsync(Path.Combine(root,"desktop-runtime.json"))).RootElement.GetProperty("pythonPath").GetString()!;
            var start=new ProcessStartInfo(python) {WorkingDirectory=root,UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true};
            start.ArgumentList.Add("tools/verify_workspace_attachment.py");start.ArgumentList.Add(fixture);
            using var process=Process.Start(start)!;
            var stdout=process.StandardOutput.ReadToEndAsync();var stderr=process.StandardError.ReadToEndAsync();
            await process.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(75));
            await File.WriteAllTextAsync(Path.Combine(output,"checks.txt"),await stdout+await stderr);
            if(process.ExitCode!=0)throw new Exception("Workspace attachment check failed; see checks.txt");
            if(await pane.Browser.ExecuteScriptAsync("window.fixtureClicks")!="1")throw new Exception("Disconnect closed or changed the borrowed pane");
            pane.SetAssistantControl(true);
            if(pane.Browser.IsHitTestVisible)throw new Exception("Manual input was not blocked while enabled");
            pane.SetAssistantControl(false);
            if(!pane.Browser.IsHitTestVisible || !pane.Browser.IsEnabled)throw new Exception("Manual control was not restored");
            var dialog=new BrowserAssistantDialog(workspace,workspace.Panes.ToArray(),pane) {Owner=Window.GetWindow(workspace)};
            dialog.Show();await Task.Delay(250);dialog.UpdateLayout();
            var bitmap=new RenderTargetBitmap((int)dialog.ActualWidth,(int)dialog.ActualHeight,96,96,PixelFormats.Pbgra32);
            bitmap.Render(dialog);var encoder=new PngBitmapEncoder();encoder.Frames.Add(BitmapFrame.Create(bitmap));
            using(var file=File.Create(Path.Combine(output,"assistant-panel.png")))encoder.Save(file);
            dialog.Close();
            await File.AppendAllTextAsync(Path.Combine(output,"checks.txt"),"\nPASS: pane survives disconnect; manual control restored; all browsers start off.\n");
            return 0;
        } catch(Exception ex) {await File.WriteAllTextAsync(Path.Combine(output,"error.txt"),ex.ToString());return 1;}
    }
}
