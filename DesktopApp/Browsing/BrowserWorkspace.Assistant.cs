using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Threading;

namespace EternalVoidPanel.Browsing;

public partial class BrowserWorkspace
{
    private sealed record AssistantSession(string Token,string Account,string Target,int Port,bool Scan,bool Upgrades) {
        public bool Releasing { get; set; }
    }
    private readonly Dictionary<BrowserPane,AssistantSession> assistantSessions=[];
    private readonly DispatcherTimer assistantTimer=new() { Interval=TimeSpan.FromSeconds(2) };
    private Func<object,Task<JsonElement>>? assistantRequest;
    private string assistantRoot="";
    private bool assistantPolling;
    public void ConfigureAssistant(string projectRoot,Func<object,Task<JsonElement>> request)
    {
        assistantRoot=projectRoot; assistantRequest=request;
        assistantTimer.Tick+=async(_,_)=>await RefreshAssistantAsync(); assistantTimer.Start();
    }
    private string LeasePath(AssistantSession session)=>Path.Combine(assistantRoot,"data","workspace-leases",session.Token+".json");
    private void WriteLease(AssistantSession s)
    {
        string path=LeasePath(s);Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        string json=JsonSerializer.Serialize(new {token=s.Token,account=s.Account,targetId=s.Target,port=s.Port,
            enabled=true,identityConfirmed=true,expires=DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()/1000.0+10,
            features=new {scan=s.Scan,upgrades=s.Upgrades}});
        File.WriteAllText(path+".tmp",json);File.Move(path+".tmp",path,true);
    }
    private void Assistant_Click(object sender,RoutedEventArgs e)=>ShowAssistant(null);
    private void ShowAssistant(BrowserPane? selected)
    {
        if (assistantRequest is null) {
            TextDialog.Info(Window.GetWindow(this), "Browser assistant", "Your browsers are in manual control. Automation inside these panes is not available in this build.\n\nAll navigation, accounts and layout controls work independently of scanning. Resume scan starts the separate scanner sessions shown in Live overview.");
            return;
        }
        var dialog=new BrowserAssistantDialog(this,OrderedPanes().ToArray(),selected) {Owner=Window.GetWindow(this)};
        dialog.ShowDialog();
    }
    internal async Task<string> EnableAssistantAsync(BrowserPane pane,bool scan,bool upgrades,bool identityConfirmed)
    {
        if(assistantRequest is null) throw new InvalidOperationException("Automation inside these browsers is not available in this build. You can use all browser controls manually. Resume scan runs the separate scanner sessions.");
        if(!scan && !upgrades) throw new InvalidOperationException("Choose at least one permission.");
        if(!identityConfirmed) throw new InvalidOperationException("Confirm the account currently signed in to this browser.");
        if(!Panes.Contains(pane) || string.IsNullOrWhiteSpace(pane.State.Account)) throw new InvalidOperationException("Assign a saved scanner account to this browser in Accounts first.");
        if(assistantSessions.ContainsKey(pane)) throw new InvalidOperationException("Take control before changing permissions.");
        string target=await pane.AssistantTargetAsync();
        var session=new AssistantSession(Guid.NewGuid().ToString("N"),pane.State.Account,target,pane.DebugPort,scan,upgrades);
        assistantSessions.Add(pane,session);WriteLease(session);pane.SetAssistantControl(true,"Connecting assistant to this browser…");
        try {
            var result=await assistantRequest(new {command="controller_workspace_enable",account=session.Account,token=session.Token});
            pane.SetAssistantControl(true);UpdateAssistantLabel();return result.GetProperty("message").GetString()!;
        } catch {
            RevokeAssistant(pane);
            // Keep manual input blocked until the backend confirms it has released.
            session.Releasing=true;UpdateAssistantLabel();throw;
        }
    }
    internal async Task<string> DisableAssistantAsync(BrowserPane pane)
    {
        if(!assistantSessions.TryGetValue(pane,out var session)) return "Manual control · Assistant off";
        RevokeAssistant(pane);session.Releasing=true;
        pane.SetAssistantControl(true,"Releasing control; finishing any pending action…");
        if(assistantRequest is not null) await assistantRequest(new {command="controller_workspace_disable",account=session.Account,token=session.Token});
        await RefreshAssistantAsync();return pane.AssistantControlled ? "Releasing control… Your browser will unlock when the worker stops." : "Manual control · Assistant off";
    }
    private void RevokeAssistant(BrowserPane pane)
    {
        if(!assistantSessions.TryGetValue(pane,out var session)) return;
        session.Releasing=true;
        try {File.Delete(LeasePath(session));} catch(IOException) { }
    }
    private void UpdateAssistantLabel()=>AssistantButton.Content=$"Assistant · {assistantSessions.Count(s=>!s.Value.Releasing)} enabled";
    internal (bool Scan,bool Upgrades) AssistantPermissions(BrowserPane? pane)=>pane is not null&&assistantSessions.TryGetValue(pane,out var s)?(s.Scan,s.Upgrades):(false,false);
    private async Task RefreshAssistantAsync()
    {
        if(assistantPolling || closed || assistantRequest is null)return;
        assistantPolling=true;
        try {
            foreach(var (pane,session) in assistantSessions.ToArray()) {
                if(!Panes.Contains(pane) || !pane.IsGamePage || pane.State.Account!=session.Account) RevokeAssistant(pane);
                if(session.Releasing) {
                    await assistantRequest(new {command="controller_workspace_disable",account=session.Account,token=session.Token});
                    var result=await assistantRequest(new {command="controller_workspace_released",account=session.Account,token=session.Token});
                    if(result.GetProperty("released").GetBoolean()) {
                        assistantSessions.Remove(pane);if(Panes.Contains(pane))pane.SetAssistantControl(false);
                    }
                } else {
                    WriteLease(session);
                    var health=await assistantRequest(new {command="controller_workspace_status",account=session.Account});
                    if(health.TryGetProperty("error",out var error) && error.ValueKind==JsonValueKind.String) {
                        RevokeAssistant(pane);StatusText.Text=error.GetString();
                        pane.SetAssistantControl(true,error.GetString()!);
                    } else pane.SetAssistantControl(true,health.GetProperty("message").GetString()!+" · Take control to interact");
                }
            }
            UpdateAssistantLabel();
        } catch { foreach(var pane in assistantSessions.Keys.ToArray())RevokeAssistant(pane); }
        finally {assistantPolling=false;}
    }
}
