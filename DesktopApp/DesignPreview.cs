using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;

namespace EternalVoidPanel;

public partial class MainWindow
{
    // Explicit visual review mode: synthetic content only, no bridge or game sessions.
    private async Task CaptureDesignPreview()
    {
        string output=Environment.GetEnvironmentVariable("EOG_TEST_OUTPUT")
            ?? throw new InvalidOperationException("Set EOG_TEST_OUTPUT for visual review.");
        Directory.CreateDirectory(output);
        ResumeButton.IsEnabled=PauseButton.IsEnabled=ApplyButton.IsEnabled=false;
        RunBadge.Text="PREVIEW";RunBadge.Foreground=(Brush)FindResource("SubTextBrush");
        StatusText.Text="Design preview · sample accounts and coordinates";
        UpdatedText.Text="Nothing is running";
        LoadSettings(JsonSerializer.SerializeToElement(new {workerCount=1,accounts=Array.Empty<object>()}));
        ShowPage(NavAccounts);
        await SavePreview(output,"welcome");
        var sampleNames=new[]{"Orion","Cassiopeia","Andromeda"};
        LoadSettings(JsonSerializer.SerializeToElement(new {workerCount=3,accounts=sampleNames.Select(name=>new {username=name,hasPassword=true})}));
        workers=sampleNames.Select((name,i)=>new WorkerEntry {Id=i+1,Account=name,State=i==1?"paused":"active",Detail=i==1?"Paused · confirmed coordinates are saved":"Checking planet ownership · System "+(57+i*24),Galaxy=(i+1).ToString(),LastCompleted="Just now"}).ToList();
        WorkerList.ItemsSource=workers;WorkerList.SelectedIndex=0;
        AgentStat.Text="2 / 3";AgentNote.Text="One agent paused";
        SlotStat.Text="12,846";SlotNote.Text="of 94,311 across 9 galaxies";
        PlayerStat.Text="186";CoordinateNote.Text="1,284 confirmed coordinates";
        SystemStat.Text="803";SystemNote.Text="All required positions checked";
        BrowserNote.Text="Separate browser sessions · progress saved automatically";
        PreviewTitle.Text="Orion · Galaxy 1";PreviewEmpty.Text="Game preview appears here\nwhen an agent is scanning.";
        double now=DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        allPlayers=[
            new(){Name="Orion",Alliance="NOVA",Coordinates=["1:57:8","1:57:12","1:58:6"],Observed=now},
            new(){Name="Cassiopeia",Alliance="NOVA",Coordinates=["1:58:9","1:59:14","1:60:7"],Observed=now-60},
            new(){Name="Andromeda",Alliance="ATLAS",Coordinates=["3:114:5","3:118:9"],Observed=now-120},
            new(){Name="Vega",Alliance="",Coordinates=["7:26:11"],Observed=now-240}];
        ApplyFilters();
        UpdateActivity(JsonSerializer.SerializeToElement(new[]{
            new {id="preview1",account="Orion",timestamp=now,text="Confirmed 1:57:12 · planet owner recorded."},
            new {id="preview2",account="Andromeda",timestamp=now-15,text="System 3:114 complete · all required positions verified."},
            new {id="preview3",account="Cassiopeia",timestamp=now-30,text="Scan paused. Confirmed slots and coordinates are saved."},
            new {id="preview4",account="Orion",timestamp=now-45,text="Session ready · continuing from the last saved checkpoint."}
        }),activityClock.Elapsed);
        ShowPage(NavBrowsers);
        await Browsers.EnsureStartedAsync();
        foreach(var page in new[]{(NavLive,"overview"),(NavBrowsers,"browsers"),(NavAccounts,"accounts"),(NavPlayers,"players"),(NavActivity,"activity"),(NavAutomation,"automation")}) {
            ShowPage(page.Item1);await SavePreview(output,page.Item2);
        }
        ShowPage(NavPlayers);SetCoordinateView(true);await SavePreview(output,"hives");SetCoordinateView(false);
        ShowPage(NavAutomation);Automation.VerifyEditor();await SavePreview(output,"automation-plan");Automation.FinishVerification();
        Width=MinWidth;Height=MinHeight;
        foreach(var page in new[]{(NavLive,"overview"),(NavBrowsers,"browsers"),(NavAccounts,"accounts"),(NavAutomation,"automation")}) {
            ShowPage(page.Item1);await SavePreview(output,page.Item2+"-compact");
            if(page.Item1==NavAccounts) {
                var position=ApplyButton.TransformToAncestor(this).Transform(new Point());
                if(position.Y<0 || position.Y+ApplyButton.ActualHeight>ActualHeight)
                    throw new InvalidOperationException("The Save button is outside the compact window.");
                AccountsScroll.ScrollToEnd();await SavePreview(output,"accounts-bottom-compact");
                var last=usernames[^1].TransformToAncestor(this).Transform(new Point());
                if(last.Y<0 || last.Y+usernames[^1].ActualHeight>ActualHeight)
                    throw new InvalidOperationException("The final account cannot be reached.");
                AccountsScroll.ScrollToTop();
            }
        }
        Width=1360;Height=900;ShowPage(NavLive);
        ToggleSidebar(this,new RoutedEventArgs());await SavePreview(output,"overview-sidebar-hidden");
        ToggleSidebar(this,new RoutedEventArgs());
        WindowState=WindowState.Maximized;await SavePreview(output,"overview-maximized");
        WindowState=WindowState.Normal;await SavePreview(output,"overview-restored");
        await File.WriteAllTextAsync(Path.Combine(output,"design-review.json"),JsonSerializer.Serialize(new {passed=true,syntheticData=true,compactSaveVisible=true,tenthAccountReachable=true,pages=8,maximizeRestore=true,frame=nativeFrame?.VerifyAppearance()}));
    }

    private async Task SavePreview(string output,string name)
    {
        await Dispatcher.InvokeAsync(()=>{},DispatcherPriority.ApplicationIdle);UpdateLayout();
        var bitmap=new RenderTargetBitmap((int)ActualWidth,(int)ActualHeight,96,96,PixelFormats.Pbgra32);
        bitmap.Render(this);
        foreach(var corner in new[]{new Int32Rect(0,0,1,1),new Int32Rect(bitmap.PixelWidth-1,0,1,1),new Int32Rect(0,bitmap.PixelHeight-1,1,1),new Int32Rect(bitmap.PixelWidth-1,bitmap.PixelHeight-1,1,1)}) {
            byte[] pixel=new byte[4];bitmap.CopyPixels(corner,pixel,4,0);
            if(pixel.Take(3).Any(channel=>channel>110))
                throw new InvalidOperationException($"A light backing surface is visible at a window corner in {name}.");
        }
        var encoder=new PngBitmapEncoder();encoder.Frames.Add(BitmapFrame.Create(bitmap));
        using var file=File.Create(Path.Combine(output,name+".png"));encoder.Save(file);
    }
}
