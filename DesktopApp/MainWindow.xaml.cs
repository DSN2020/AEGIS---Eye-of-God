using System.Diagnostics;
using System.Collections.ObjectModel;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;

namespace EternalVoidPanel;

public partial class MainWindow : Window
{
    private const int MaxAgents = 10;
    private Process? bridge;
    private readonly SemaphoreSlim bridgeLock = new(1,1);
    private readonly DispatcherTimer timer = new() { Interval = TimeSpan.FromSeconds(2) };
    private readonly DispatcherTimer highlightTimer = new() { Interval = TimeSpan.FromMilliseconds(50) };
    private readonly DispatcherTimer countTimer = new() { Interval = TimeSpan.FromMilliseconds(650) };
    private readonly Stopwatch activityClock = Stopwatch.StartNew();
    private readonly ObservableCollection<ActivityEntry> activityRows = [];
    private readonly HashSet<string> seenActivity = [];
    private readonly Queue<string> activityHistory = [];
    private bool activityLoaded;
    private readonly Dictionary<string,string> accountColors = new(StringComparer.OrdinalIgnoreCase);
    private readonly List<TextBox> usernames = [];
    private readonly List<PasswordBox> passwords = [];
    private readonly List<TextBlock> credentialLabels = [];
    private readonly List<TextBlock> slotLabels = [];
    private readonly HashSet<string> savedNames = new(StringComparer.OrdinalIgnoreCase);
    private List<PlayerEntry> allPlayers = [];
    private List<PlayerEntry> filteredPlayers = [];
    private List<WorkerEntry> workers = [];
    private bool refreshing, busy, closed;
    private int workerCount = 4, savedWorkerCount = 4;
    private string root = "", frameKey = "", playerKey = "";
    private DateTime messageUntil = DateTime.MinValue;
    private readonly bool verifyUi = Environment.GetCommandLineArgs().Contains("--verify-ui");

    public MainWindow() {
        InitializeComponent(); BuildAccountRows(); ActivityList.ItemsSource=activityRows;
        highlightTimer.Tick+=(_,_)=>ExpireActivityHighlights(activityClock.Elapsed);
        highlightTimer.Start();
        countTimer.Tick+=async (_,_)=> { countTimer.Stop(); await ApplyCountChange(); };
    }

    private static string S(JsonElement e,string key,string fallback="") => e.ValueKind==JsonValueKind.Object && e.TryGetProperty(key,out var v) && v.ValueKind!=JsonValueKind.Null ? v.ToString() : fallback;
    private static int N(JsonElement e,string key,int fallback=0) => int.TryParse(S(e,key),out int v) ? v : fallback;
    private static double D(JsonElement e,string key,double fallback=0) => double.TryParse(S(e,key),System.Globalization.NumberStyles.Any,System.Globalization.CultureInfo.InvariantCulture,out double v) ? v : fallback;
    private static bool B(JsonElement e,string key) => S(e,key).Equals("True",StringComparison.OrdinalIgnoreCase);
    private static string Age(double unix) => unix <= 0 ? "Not yet captured" : DateTimeOffset.FromUnixTimeSeconds((long)unix).LocalDateTime.ToString("MMM d, h:mm:ss tt");

    private async void Window_Loaded(object sender,RoutedEventArgs e)
    {
        try {
            var directory = new DirectoryInfo(AppContext.BaseDirectory);
            while(directory!=null && !File.Exists(Path.Combine(directory.FullName,"app_bridge.py"))) directory=directory.Parent;
            root=directory?.FullName ?? throw new InvalidOperationException("Keep EOG inside its scanner folder. The scanner files could not be found.");
            var runtime=JsonDocument.Parse(await File.ReadAllTextAsync(Path.Combine(root,"desktop-runtime.json"))).RootElement;
            var info=new ProcessStartInfo(S(runtime,"pythonPath")) { WorkingDirectory=root,UseShellExecute=false,CreateNoWindow=true,RedirectStandardInput=true,RedirectStandardOutput=true,RedirectStandardError=true,StandardInputEncoding=new UTF8Encoding(false),StandardOutputEncoding=Encoding.UTF8 };
            info.ArgumentList.Add("-u"); info.ArgumentList.Add("app_bridge.py");
            bridge=Process.Start(info) ?? throw new InvalidOperationException("Could not start the scanner connection.");
            _=bridge.StandardError.ReadToEndAsync();
            LoadSettings(await Request(new { command="settings" }));
            await RefreshSnapshot();
            if(verifyUi) { await VerifyAndCapture(); Close(); return; }
            timer.Tick+=async (_,_) => await RefreshSnapshot(); timer.Start();
        } catch(Exception ex) { ShowMessage(ex.Message,true); if(verifyUi) { await File.WriteAllTextAsync(Path.Combine(AppContext.BaseDirectory,"ui-error.txt"),ex.ToString()); Application.Current.Shutdown(1); } }
    }

    private async Task<JsonElement> Request(object request)
    {
        await bridgeLock.WaitAsync();
        try {
            if(bridge==null || bridge.HasExited) throw new InvalidOperationException("The scanner connection is closed. Reopen EOG to reconnect.");
            await bridge.StandardInput.WriteLineAsync(JsonSerializer.Serialize(request));
            await bridge.StandardInput.FlushAsync();
            string? line=await bridge.StandardOutput.ReadLineAsync().WaitAsync(TimeSpan.FromSeconds(45));
            if(line==null) throw new InvalidOperationException("The scanner connection ended. Reopen EOG to reconnect.");
            using var document=JsonDocument.Parse(line);
            if(!B(document.RootElement,"ok")) throw new InvalidOperationException(S(document.RootElement,"error","Operation failed."));
            return document.RootElement.GetProperty("result").Clone();
        } finally { bridgeLock.Release(); }
    }

    private async Task RefreshSnapshot()
    {
        if(refreshing || busy || closed) return;
        refreshing=true;
        try {
            var snapshot=await Request(new { command="snapshot" });
            var status=snapshot.GetProperty("status");
            string state=S(status,"state","paused");
            RunBadge.Text=state.ToUpperInvariant(); RunBadge.Foreground=new SolidColorBrush(state=="running" ? Color.FromRgb(85,214,160) : Color.FromRgb(230,180,80));
            ResumeButton.IsEnabled=state is not ("running" or "unresponsive"); PauseButton.IsEnabled=state is "running" or "unresponsive";
            int requested=N(status,"requestedWorkers",workerCount);
            AgentStat.Text=$"{N(status,"activeWorkers")} / {(state=="paused" ? requested : N(status,"expectedWorkers",requested))}";
            int starting=snapshot.GetProperty("workers").EnumerateArray().Count(w=>S(w,"state")=="starting");
            AgentNote.Text=B(status,"workerCountPending") ? $"Changing to {requested} agents…" : $"{starting} starting · {N(status,"retryingWorkers")} retrying · {state}";
            int configured=N(snapshot.GetProperty("settings"),"workerCount",savedWorkerCount);
            if(!countTimer.IsEnabled && !busy && workerCount==savedWorkerCount) { workerCount=configured; UpdateCount(); }
            savedWorkerCount=configured;
            if(!countTimer.IsEnabled && !busy && workerCount==configured) {
                CountChangeStatus.Text=B(status,"workerCountPending") ? $"Applying {configured} agents using saved accounts…" : state=="paused" ? $"{configured} agents selected. Resume scan to start them." : $"{configured} agent slots applied · {N(status,"activeWorkers")} scanning. Account edits still use Save & apply.";
                CountChangeStatus.Foreground=(Brush)FindResource("SubTextBrush");
            }
            SlotStat.Text=N(status,"verifiedPlanetSlots").ToString("N0");
            SlotNote.Text=$"of {N(status,"totalPlanetSlots",94311):N0} across 9 galaxies";
            PlayerStat.Text=N(snapshot,"playerCount").ToString("N0"); CoordinateNote.Text=$"{N(snapshot,"coordinateCount"):N0} confirmed coordinates";
            SystemStat.Text=N(status,"completedSystems").ToString("N0"); SystemNote.Text=$"of {N(status,"totalSystems",4491):N0} · all 21 slots required";
            int selected=(WorkerList.SelectedItem as WorkerEntry)?.Id ?? 1;
            workers=snapshot.GetProperty("workers").EnumerateArray().Select(w=>new WorkerEntry {
                Id=N(w,"id"),Account=S(w,"account"),State=S(w,"state"),Detail=S(w,"detail"),Galaxy=S(w,"galaxy","—"),
                LastCompleted=S(w,"lastCompleted","—"),Restarts=N(w,"restarts"),FramePath=S(w,"framePath"),FrameUpdated=D(w,"frameUpdated") }).ToList();
            WorkerList.ItemsSource=workers; WorkerList.SelectedItem=workers.FirstOrDefault(w=>w.Id==selected) ?? workers.FirstOrDefault();
            UpdatePreview();
            var players=snapshot.GetProperty("players");
            string nextKey=players.GetRawText();
            if(playerKey!=nextKey) {
                playerKey=nextKey;
                allPlayers=players.EnumerateArray().Select(p=>new PlayerEntry {
                    Name=S(p,"name"),Alliance=p.GetProperty("alliance").ValueKind==JsonValueKind.Null ? null : S(p,"alliance"),
                    Coordinates=p.GetProperty("coordinates").EnumerateArray().Select(x=>x.GetString()??"").ToArray(),Observed=D(p,"observed") }).ToList();
                ApplyFilters();
            }
            UpdateActivity(snapshot.GetProperty("activity"),activityClock.Elapsed);
            UpdatedText.Text="Updated "+DateTime.Now.ToString("h:mm:ss tt");
            if(DateTime.Now>messageUntil) { StatusText.Text=state=="running" ? "Connected · confirmations and player records update automatically" : "Scan "+state+" · saved findings remain available"; StatusText.Foreground=(Brush)FindResource("SubTextBrush"); }
        } catch(Exception ex) { ShowMessage(ex.Message,true); }
        finally { refreshing=false; }
    }

    private string AccountColor(string account) {
        if(accountColors.TryGetValue(account,out var color)) return color;
        string[] palette=["#80CFFF","#BEA0FF","#F2C66D","#6EDCB5","#FF927C","#F299CE","#B8DD72","#70DFE8","#F6AD62","#ABB8FF"];
        return accountColors[account]=palette[accountColors.Count%palette.Length];
    }
    private void UpdateActivity(JsonElement entries,TimeSpan now) {
        var incoming=entries.EnumerateArray().OrderByDescending(e=>D(e,"timestamp")).ThenBy(e=>S(e,"id"),StringComparer.Ordinal).ToArray();
        var ids=incoming.Select(e=>S(e,"id")).ToHashSet();
        for(int i=activityRows.Count-1;i>=0;i--) if(!ids.Contains(activityRows[i].Id)) activityRows.RemoveAt(i);
        var existing=activityRows.ToDictionary(e=>e.Id);
        for(int i=0;i<incoming.Length;i++) {
            var e=incoming[i]; string id=S(e,"id");
            if(existing.TryGetValue(id,out var row)) {
                int old=activityRows.IndexOf(row); if(old!=i) activityRows.Move(old,i);
                continue;
            }
            bool firstTime=seenActivity.Add(id);
            if(firstTime) activityHistory.Enqueue(id);
            // Don't flash historical logs on startup. New arrivals fade for one
            // second from receipt, independently of the polling connection.
            bool fresh=firstTime && (activityLoaded || DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()/1000.0-D(e,"timestamp") is >=0 and <=1);
            activityRows.Insert(i,new ActivityEntry {Id=id,Account=S(e,"account"),Text=S(e,"text"),
                Timestamp=D(e,"timestamp"),AccountColor=AccountColor(S(e,"account")),
                HighlightUntil=now+ActivityEntry.HighlightDuration,Highlighted=fresh});
        }
        while(activityHistory.Count>4096) seenActivity.Remove(activityHistory.Dequeue());
        activityLoaded=true;
        ExpireActivityHighlights(now);
    }
    private void ExpireActivityHighlights(TimeSpan now) {
        foreach(var row in activityRows) row.UpdateHighlight(now);
    }

    private void BuildAccountRows()
    {
        for(int index=0;index<MaxAgents;index++) {
            var grid=new Grid(); grid.ColumnDefinitions.Add(new(){Width=new GridLength(90)}); grid.ColumnDefinitions.Add(new()); grid.ColumnDefinitions.Add(new()); grid.ColumnDefinitions.Add(new(){Width=new GridLength(140)});
            var label=new TextBlock {Text=$"Agent {index+1}",VerticalAlignment=VerticalAlignment.Center,FontSize=12}; slotLabels.Add(label); grid.Children.Add(label);
            var name=new TextBox {Margin=new Thickness(0,0,12,0),Height=40,ToolTip=$"Username for agent {index+1}"}; Grid.SetColumn(name,1); grid.Children.Add(name); usernames.Add(name);
            var password=new PasswordBox {Margin=new Thickness(0,0,12,0),Height=40,ToolTip="Enter or replace password; blank keeps the saved password"}; Grid.SetColumn(password,2); grid.Children.Add(password); passwords.Add(password);
            var saved=new TextBlock {Text="Not saved",Foreground=(Brush)FindResource("SubTextBrush"),VerticalAlignment=VerticalAlignment.Center,FontSize=11}; Grid.SetColumn(saved,3); grid.Children.Add(saved); credentialLabels.Add(saved);
            name.TextChanged+=(_,_)=>saved.Text=savedNames.Contains(name.Text.Trim()) ? "Saved securely" : "Not saved";
            password.PasswordChanged+=(_,_)=>saved.Text=password.Password.Length>0 ? "Ready to save" : savedNames.Contains(name.Text.Trim()) ? "Saved securely" : "Not saved";
            AccountRows.Children.Add(new Border {Style=(Style)FindResource("Card"),Padding=new Thickness(14,10,14,10),Margin=new Thickness(0,0,0,8),Child=grid});
        }
    }
    private void LoadSettings(JsonElement settings)
    {
        workerCount=N(settings,"workerCount",4);
        savedWorkerCount=workerCount;
        var accounts=settings.GetProperty("accounts").EnumerateArray().ToArray();
        savedNames.Clear(); foreach(var a in accounts) if(B(a,"hasPassword")) savedNames.Add(S(a,"username"));
        for(int i=0;i<MaxAgents;i++) {
            usernames[i].Text=i<accounts.Length ? S(accounts[i],"username") : ""; passwords[i].Clear();
            credentialLabels[i].Text=i<accounts.Length && B(accounts[i],"hasPassword") ? "Saved securely" : "Not saved";
        }
        UpdateCount();
    }
    private void UpdateCount() { AgentCount.Text=workerCount.ToString(); for(int i=0;i<MaxAgents;i++) {slotLabels[i].Text=$"Agent {i+1}\n"+(i<workerCount ? "Selected slot" : "Standby"); slotLabels[i].Foreground=(Brush)FindResource(i<workerCount ? "TextBrush" : "GrayBrush");} }
    private void ChangeWorkerCount(int delta) {
        int next=Math.Clamp(workerCount+delta,1,MaxAgents);
        if(next==workerCount) return;
        workerCount=next; UpdateCount();
        if(verifyUi) return; // UI verification never changes scanner settings.
        CountChangeStatus.Text=$"Applying {workerCount} agents using saved accounts…";
        CountChangeStatus.Foreground=(Brush)FindResource("SubTextBrush");
        countTimer.Stop(); countTimer.Start();
    }
    private void LessAgents(object s,RoutedEventArgs e) => ChangeWorkerCount(-1);
    private void MoreAgents(object s,RoutedEventArgs e) => ChangeWorkerCount(1);
    private async Task ApplyCountChange() {
        if(closed) return;
        if(busy || refreshing) { countTimer.Start(); return; }
        int desired=workerCount;
        busy=true; ApplyButton.IsEnabled=ResumeButton.IsEnabled=PauseButton.IsEnabled=false;
        try {
            var result=await Request(new {command="set_worker_count",workerCount=desired});
            savedWorkerCount=desired;
            if(workerCount==desired) CountChangeStatus.Text=S(result,"message");
        } catch(Exception ex) {
            CountChangeStatus.Text=ex.Message+" Save account details below, then try the count again.";
            CountChangeStatus.Foreground=(Brush)FindResource("RedBrush");
        } finally {
            busy=false;ApplyButton.IsEnabled=true;
            await RefreshSnapshot();
        }
    }
    private object AccountRequest() => new {command="apply",workerCount,accounts=usernames.Select((n,i)=>new {username=n.Text.Trim(),password=passwords[i].Password}).ToArray()};
    private async Task Execute(object request,bool reloadSettings=false)
    {
        if(busy) return; busy=true; ApplyButton.IsEnabled=ResumeButton.IsEnabled=PauseButton.IsEnabled=false;
        ShowMessage("Applying your request…");
        try { var result=await Request(request); ShowMessage(S(result,"message")); if(reloadSettings) LoadSettings(await Request(new {command="settings"})); }
        catch(Exception ex) { ShowMessage(ex.Message,true); }
        finally { busy=false; ApplyButton.IsEnabled=true; await RefreshSnapshot(); }
    }
    private async void Apply_Click(object s,RoutedEventArgs e) => await Execute(AccountRequest(),true);
    private async void Resume_Click(object s,RoutedEventArgs e) => await Execute(new {command="start"});
    private async void Pause_Click(object s,RoutedEventArgs e) => await Execute(new {command="stop"});
    private async void Restart_Click(object s,RoutedEventArgs e) { if(WorkerList.SelectedItem is WorkerEntry w) await Execute(new {command="restart_worker",index=w.Id}); }
    private void ShowMessage(string message,bool error=false) { StatusText.Text=message; StatusText.Foreground=(Brush)FindResource(error ? "RedBrush" : "SubTextBrush"); messageUntil=DateTime.Now.AddSeconds(10); }

    private void Navigate(object sender,RoutedEventArgs e) => ShowPage((Button)sender);
    private void ShowPage(Button selected)
    {
        LiveView.Visibility=selected==NavLive ? Visibility.Visible : Visibility.Collapsed;
        PlayersView.Visibility=selected==NavPlayers ? Visibility.Visible : Visibility.Collapsed;
        AccountsView.Visibility=selected==NavAccounts ? Visibility.Visible : Visibility.Collapsed;
        ActivityView.Visibility=selected==NavActivity ? Visibility.Visible : Visibility.Collapsed;
        foreach(var button in new[]{NavLive,NavPlayers,NavAccounts,NavActivity}) button.Style=(Style)FindResource(button==selected ? "NavButtonActive" : "NavButton");
    }
    private void FilterChanged(object s,TextChangedEventArgs e) { if(PlayerCards!=null) ApplyFilters(); }
    private void ApplyFilters()
    {
        string name=PlayerSearch.Text.Trim(),alliance=AllianceSearch.Text.Trim();
        filteredPlayers=allPlayers.Where(p=>p.Name.Contains(name,StringComparison.OrdinalIgnoreCase) && p.AllianceLabel.Contains(alliance,StringComparison.OrdinalIgnoreCase)).ToList();
        PlayerCards.ItemsSource=filteredPlayers;
        ResultsCount.Text=$"{filteredPlayers.Count:N0} players · {filteredPlayers.Sum(p=>p.Coordinates.Length):N0} coordinates";
        NoPlayers.Visibility=filteredPlayers.Count==0 ? Visibility.Visible : Visibility.Collapsed;
    }
    private void ClearFilters(object s,RoutedEventArgs e) { PlayerSearch.Clear(); AllianceSearch.Clear(); }
    private void CopyPlayer(object s,RoutedEventArgs e) { try {Clipboard.SetText(((Button)s).Tag?.ToString()??"");ShowMessage("Player coordinates copied.");} catch(Exception){ShowMessage("The clipboard is busy. Try again.",true);} }
    private void CopyMatching(object s,RoutedEventArgs e) { try {Clipboard.SetText(string.Join("\n\n",filteredPlayers.Select(p=>p.CopyText)));ShowMessage("Matching coordinates copied.");} catch(Exception){ShowMessage("The clipboard is busy. Try again.",true);} }
    private void WorkerSelected(object s,SelectionChangedEventArgs e) => UpdatePreview();
    private void UpdatePreview()
    {
        if(WorkerList.SelectedItem is not WorkerEntry w) return;
        PreviewTitle.Text=w.Account+" · Galaxy "+w.Galaxy;
        PreviewEmpty.Text=w.State=="starting"
            ? $"{w.Account} is starting.\n\n{w.Detail}\n\nThe first game preview appears once the map is ready."
            : w.State=="paused" ? $"{w.Account} is paused.\n\nResume the scan to load its game view."
            : $"{w.Account}\n\n{w.Detail}\n\nWaiting for this session’s first map capture.";
        string key=w.FramePath+"|"+w.FrameUpdated;
        if(key==frameKey) return;
        frameKey=key;
        try {
            if(!File.Exists(w.FramePath)) { PreviewImage.Source=null;PreviewEmpty.Visibility=Visibility.Visible;PreviewTime.Text="Waiting for the first verified-slot view";return; }
            using var stream=new FileStream(w.FramePath,FileMode.Open,FileAccess.Read,FileShare.ReadWrite|FileShare.Delete);
            var image=new BitmapImage(); image.BeginInit();image.CacheOption=BitmapCacheOption.OnLoad;image.StreamSource=stream;image.EndInit();image.Freeze();
            PreviewImage.Source=image;PreviewEmpty.Visibility=Visibility.Collapsed;PreviewTime.Text="Captured "+Age(w.FrameUpdated);
        } catch(IOException) { frameKey=""; }
    }
    private void DragWindow(object s,MouseButtonEventArgs e) { if(e.ClickCount==2) WindowState=WindowState==WindowState.Maximized?WindowState.Normal:WindowState.Maximized; else if(e.LeftButton==MouseButtonState.Pressed) DragMove(); }
    private void Minimize(object s,RoutedEventArgs e) => WindowState=WindowState.Minimized;
    private void Maximize(object s,RoutedEventArgs e) => WindowState=WindowState==WindowState.Maximized?WindowState.Normal:WindowState.Maximized;
    private void CloseApp(object s,RoutedEventArgs e) => Close();
    private void Window_Closed(object? s,EventArgs e) { closed=true;timer.Stop();highlightTimer.Stop();countTimer.Stop();try {bridge?.StandardInput.Close();}catch{} }

    private async Task VerifyAndCapture()
    {
        string output=Path.Combine(root,"DesktopApp","ui-review"); Directory.CreateDirectory(output);
        LoadSettings(JsonSerializer.SerializeToElement(new {workerCount=1,accounts=Array.Empty<object>()}));
        if(usernames.Count!=MaxAgents || passwords.Count!=MaxAgents || usernames.Any(x=>x.Text.Length!=0) || passwords.Any(x=>x.Password.Length!=0) || savedNames.Count!=0)
            throw new Exception("Fresh installation must have ten blank account slots");
        LoadSettings(await Request(new {command="settings"}));
        PlayerSearch.Text="nazim";
        if(!filteredPlayers.Any(p=>p.Coordinates.Contains("9:57:14"))) throw new InvalidOperationException("Known-player search regression failed.");
        AllianceSearch.Text="__NO_MATCH__";
        if(filteredPlayers.Count!=0) throw new InvalidOperationException("Combined alliance filter failed.");
        AllianceSearch.Clear();PlayerSearch.Clear();
        var allianceExample=allPlayers.FirstOrDefault(p=>!string.IsNullOrWhiteSpace(p.Alliance) && p.Alliance!="-");
        if(allianceExample!=null) {
            PlayerSearch.Text=allianceExample.Name; AllianceSearch.Text=allianceExample.Alliance;
            if(!filteredPlayers.Contains(allianceExample)) throw new InvalidOperationException("Recorded alliance search failed.");
            PlayerSearch.Clear(); AllianceSearch.Clear();
        }
        workerCount=1;LessAgents(this,new());if(workerCount!=1)throw new Exception("Agent minimum failed");
        workerCount=MaxAgents;MoreAgents(this,new());if(workerCount!=MaxAgents)throw new Exception("Agent maximum failed");
        if(countTimer.IsEnabled) throw new Exception("UI verification must not send count changes");
        LoadSettings(await Request(new {command="settings"}));
        var tenAccounts=Enumerable.Range(1,MaxAgents).Select(i=>new {username=$"Example account {i}",hasPassword=false}).ToArray();
        LoadSettings(JsonSerializer.SerializeToElement(new {workerCount=MaxAgents,accounts=tenAccounts}));
        var tenRequest=JsonSerializer.SerializeToElement(AccountRequest());
        if(tenRequest.GetProperty("accounts").GetArrayLength()!=MaxAgents || S(tenRequest.GetProperty("accounts")[9],"username")!="Example account 10") throw new Exception("Tenth account was not included in save request");
        accountColors.Clear();
        if(tenAccounts.Select(a=>AccountColor(a.username)).Distinct().Count()!=MaxAgents) throw new Exception("Ten distinct account colors required");
        accountColors.Clear();
        LoadSettings(await Request(new {command="settings"}));
        var realActivity=(await Request(new {command="snapshot"})).GetProperty("activity");
        double current=DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()/1000.0;
        var fixture=JsonSerializer.SerializeToElement(new[] {
            new {id="verify-older",account="Account A",timestamp=current-10,text="Verification event: older message"},
            new {id="verify-newest",account="Account B",timestamp=current,text="Verification event: newest message"},
            new {id="verify-middle",account="Account C",timestamp=current-5,text="Verification event: middle message"}
        });
        var received=activityClock.Elapsed;
        UpdateActivity(fixture,received);
        if(activityRows[0].Id!="verify-newest" || activityRows[^1].Id!="verify-older") throw new Exception("Activity chronology failed");
        if(activityRows.Select(r=>r.AccountColor).Distinct().Count()!=3 || activityRows.Any(r=>!r.Highlighted)) throw new Exception("Account highlighting failed");
        var firstRow=activityRows[0];
        string initialForeground=firstRow.HighlightForeground.ToString();
        UpdateActivity(fixture,received+TimeSpan.FromMilliseconds(400));
        if(!ReferenceEquals(firstRow,activityRows[0]) || firstRow.HighlightUntil!=received+ActivityEntry.HighlightDuration) throw new Exception("Polling reset the highlight lifetime");
        ExpireActivityHighlights(received+TimeSpan.FromMilliseconds(500));
        if(!firstRow.Highlighted || firstRow.HighlightForeground.ToString()==initialForeground || firstRow.HighlightForeground.ToString()=="#FF9B9B9B") throw new Exception("Highlight did not interpolate toward gray");
        ShowPage(NavActivity); await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle); UpdateLayout();
        var highlightBitmap=new RenderTargetBitmap((int)ActualWidth,(int)ActualHeight,96,96,PixelFormats.Pbgra32); highlightBitmap.Render(this);
        var highlightEncoder=new PngBitmapEncoder();highlightEncoder.Frames.Add(BitmapFrame.Create(highlightBitmap));
        using(var highlightFile=File.Create(Path.Combine(output,"activity-highlights.png"))) highlightEncoder.Save(highlightFile);
        // Exercise the real UI timer without any further polling response.
        await Task.Delay(1200);
        if(activityRows.Any(r=>r.Highlighted)) throw new Exception("Highlights did not fade after one second");
        if(activityRows.Any(r=>r.HighlightForeground.ToString()!="#FF9B9B9B" || r.HighlightBorder.ToString()!="#FF3B3B3B" || r.HighlightBackground.ToString()!="#FF202020")) throw new Exception("Expired highlights must remain gray");
        await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle); UpdateLayout();
        var fadedBitmap=new RenderTargetBitmap((int)ActualWidth,(int)ActualHeight,96,96,PixelFormats.Pbgra32);fadedBitmap.Render(this);
        var fadedEncoder=new PngBitmapEncoder();fadedEncoder.Frames.Add(BitmapFrame.Create(fadedBitmap));
        using(var fadedFile=File.Create(Path.Combine(output,"activity-faded.png"))) fadedEncoder.Save(fadedFile);
        UpdateActivity(fixture,activityClock.Elapsed);
        if(activityRows.Any(r=>r.Highlighted)) throw new Exception("Old messages flashed again on refresh");
        UpdateActivity(realActivity,activityClock.Elapsed);
        if(!allPlayers.Select(p=>p.Observed).SequenceEqual(allPlayers.OrderByDescending(p=>p.Observed).Select(p=>p.Observed))) throw new Exception("Player recency order failed");
        foreach(var item in new[]{(NavLive,"overview"),(NavPlayers,"players"),(NavAccounts,"accounts"),(NavActivity,"activity")}) {
            ShowPage(item.Item1); await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle); UpdateLayout();
            var bitmap=new RenderTargetBitmap((int)ActualWidth,(int)ActualHeight,96,96,PixelFormats.Pbgra32);bitmap.Render(this);
            var encoder=new PngBitmapEncoder();encoder.Frames.Add(BitmapFrame.Create(bitmap));using var file=File.Create(Path.Combine(output,item.Item2+".png"));encoder.Save(file);
        }
        ShowPage(NavAccounts); AccountsView.ScrollToEnd();
        await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle); UpdateLayout();
        var lastFieldPosition=usernames[^1].TransformToAncestor(this).Transform(new Point(0,0));
        if(lastFieldPosition.Y<0 || lastFieldPosition.Y+usernames[^1].ActualHeight>ActualHeight) throw new Exception("Tenth account field cannot be reached");
        var bottomBitmap=new RenderTargetBitmap((int)ActualWidth,(int)ActualHeight,96,96,PixelFormats.Pbgra32);bottomBitmap.Render(this);
        var bottomEncoder=new PngBitmapEncoder();bottomEncoder.Frames.Add(BitmapFrame.Create(bottomBitmap));
        using(var bottomFile=File.Create(Path.Combine(output,"accounts-bottom.png"))) bottomEncoder.Save(bottomFile);
        await File.WriteAllTextAsync(Path.Combine(output,"verification.json"),JsonSerializer.Serialize(new {passed=true,blankAccountSlots=true,accountSlots=MaxAgents,tenAccountRequest=true,tenAccountColors=true,search=true,allianceFilter=true,agentBounds=true,activityChronology=true,accountColors=true,oneSecondFade=true,grayAfterFade=true,noRepeatFlash=true,playerRecency=true,players=allPlayers.Count,workers=workers.Count}));
    }
}

public sealed class WorkerEntry {
 public int Id {get;set;} public string Account {get;set;}="";public string State {get;set;}="";public string Detail {get;set;}="";public string Galaxy {get;set;}="";public string LastCompleted {get;set;}="";public int Restarts {get;set;}public string FramePath {get;set;}="";public double FrameUpdated {get;set;}
 public string Label=>$"{Id:00}  {Account}";public string StateLabel=>State.ToUpperInvariant();public string StateColor=>State=="active"?"#55D6A0":State=="retrying"?"#E6B450":"#9B9B9B";
 public string Summary=>$"Galaxy {Galaxy}   ·   Last complete {LastCompleted}   ·   {Restarts} restarts";
}
public sealed class PlayerEntry {
 public string Name {get;set;}="";public string? Alliance {get;set;}public string[] Coordinates {get;set;}=[];public double Observed {get;set;}
 public string AllianceLabel=>Alliance==null?"Not recorded":Alliance.Length==0 || Alliance=="-"?"No alliance":Alliance;
 public string CoordinatesText=>string.Join("   ·   ",Coordinates);
 public string CountLabel=>$"{Coordinates.Length} coordinates  ·  Last seen {DateTimeOffset.FromUnixTimeSeconds((long)Observed).LocalDateTime:MMM d, h:mm tt}";
 public string CopyText=>$"{Name}  [{AllianceLabel}]\n"+string.Join("\n",Coordinates.Select(c=>"  "+c));
}
