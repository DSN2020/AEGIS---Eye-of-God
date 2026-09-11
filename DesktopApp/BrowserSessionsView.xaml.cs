using System.Collections.ObjectModel;
using System.ComponentModel;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace EternalVoidPanel;

public partial class BrowserSessionsView : UserControl
{
    private readonly ObservableCollection<BrowserSession> rows=[];
    private bool updating,running;
    private string frameKey="";
    public Action? ManageAccounts {get;set;}
    public Func<int,Task>? RestartSession {get;set;}

    public BrowserSessionsView() {InitializeComponent();Sessions.ItemsSource=rows;}

    public void Update(IReadOnlyList<string> accounts,IReadOnlyList<WorkerEntry> workers,string mode,bool scanning)
    {
        running=scanning;
        string? selected=(Sessions.SelectedItem as BrowserSession)?.Account;
        updating=true;
        try {
            for(int i=rows.Count-1;i>=0;i--) if(!accounts.Contains(rows[i].Account,StringComparer.OrdinalIgnoreCase)) rows.RemoveAt(i);
            for(int i=0;i<accounts.Count;i++) {
                string account=accounts[i];
                var row=rows.FirstOrDefault(r=>r.Account.Equals(account,StringComparison.OrdinalIgnoreCase));
                if(row==null) {row=new BrowserSession(account);rows.Insert(Math.Min(i,rows.Count),row);}
                else if(rows.IndexOf(row)!=i) rows.Move(rows.IndexOf(row),i);
                // A previous account may still have status in this slot after an edit.
                // Never display that old account's frame under its replacement's name.
                var worker=workers.FirstOrDefault(w=>w.Id==i+1 && w.Account.Equals(account,StringComparison.OrdinalIgnoreCase));
                row.Update(i+1,worker,scanning);
            }
            Sessions.SelectedItem=rows.FirstOrDefault(r=>r.Account.Equals(selected,StringComparison.OrdinalIgnoreCase))??rows.FirstOrDefault();
        } finally {updating=false;}
        ModeText.Text=mode=="shared" ? "Shared browser · each account has its own isolated session" : "Separate browser session for each agent";
        SessionCount.Text=rows.Count==0 ? "No accounts configured" : $"{rows.Count} account sessions · {rows.Count(r=>r.State=="active")} scanning";
        ShowSelected();
    }

    private void SessionSelected(object sender,SelectionChangedEventArgs e) {if(!updating)ShowSelected();}
    private void ShowSelected()
    {
        var row=Sessions.SelectedItem as BrowserSession;
        SessionTitle.Text=row?.Account??"Browser preview";
        SessionDetail.Text=row?.Detail??"Add an account to see its browser session here.";
        RestartButton.IsEnabled=running && row?.Worker!=null && row.State!="managing";
        string nextKey=row==null?"":$"{row.Account}|{row.FramePath}|{row.FrameUpdated}";
        if(nextKey!=frameKey || string.IsNullOrEmpty(row?.FramePath)) {
            SessionImage.Source=null;frameKey="";
            if(!string.IsNullOrEmpty(row?.FramePath)) {
                try {
                    using var stream=new FileStream(row.FramePath,FileMode.Open,FileAccess.Read,FileShare.ReadWrite|FileShare.Delete);
                    var bitmap=new BitmapImage();bitmap.BeginInit();bitmap.CacheOption=BitmapCacheOption.OnLoad;bitmap.StreamSource=stream;bitmap.EndInit();bitmap.Freeze();
                    SessionImage.Source=bitmap;frameKey=nextKey;
                } catch(Exception error) when(error is IOException or NotSupportedException or FileFormatException) { }
            }
        }
        EmptyPreview.Visibility=SessionImage.Source==null?Visibility.Visible:Visibility.Collapsed;
        EmptyPreview.Text=row==null?"No browser sessions yet\nAdd your account to get started.":row.State=="paused"?"Session paused\nResume scanning to load its browser preview.":"Waiting for the first verified-slot preview\n"+row.Detail;
        FrameTime.Text=SessionImage.Source!=null && row!=null ? "Last captured "+DateTimeOffset.FromUnixTimeSeconds((long)row.FrameUpdated).LocalDateTime.ToString("MMM d, h:mm:ss tt")+(row.State=="paused"?" · saved frame":"") : "Previews appear once an agent starts verifying slots.";
    }
    private void ManageAccounts_Click(object sender,RoutedEventArgs e)=>ManageAccounts?.Invoke();
    private async void Restart_Click(object sender,RoutedEventArgs e) {if(Sessions.SelectedItem is BrowserSession row && RestartButton.IsEnabled && RestartSession!=null)await RestartSession(row.Id);}

    internal void VerifySessions(string sampleFrame)
    {
        Update([],[],"isolated",false);
        if(rows.Count!=0 || SessionImage.Source!=null || RestartButton.IsEnabled)throw new InvalidOperationException("Empty browser view is not empty.");
        string[] accounts=Enumerable.Range(1,10).Select(i=>"Preview account "+i).ToArray();
        Update(accounts,[],"shared",false);
        if(rows.Count!=10 || rows.Any(r=>r.State!="paused"))throw new InvalidOperationException("Saved browser accounts are missing.");
        Update(["Replacement"],[new WorkerEntry{Id=1,Account="Previous",FramePath=sampleFrame,FrameUpdated=1,State="active"}],"isolated",true);
        if(SessionImage.Source!=null || RestartButton.IsEnabled)throw new InvalidOperationException("A previous account's session leaked into its replacement.");
        var current=new WorkerEntry{Id=1,Account="Replacement",FramePath=sampleFrame,FrameUpdated=1,State="active"};
        Update(["Replacement"],[current],"isolated",true);
        if(SessionImage.Source==null || !RestartButton.IsEnabled)throw new InvalidOperationException("The current browser preview did not load.");
        current.FramePath="";Update(["Replacement"],[current],"isolated",true);
        if(SessionImage.Source!=null)throw new InvalidOperationException("An expired browser preview remained visible.");
        current.State="managing";Update(["Replacement"],[current],"isolated",true);
        if(RestartButton.IsEnabled)throw new InvalidOperationException("A reserved browser session can be restarted.");
        Update(accounts,[],"shared",false);Sessions.SelectedItem=rows[4];Update(accounts,[],"shared",false);
        if((Sessions.SelectedItem as BrowserSession)?.Account!=accounts[4])throw new InvalidOperationException("Refreshing changed the selected browser.");
    }

    private sealed class BrowserSession(string account) : INotifyPropertyChanged
    {
        public string Account {get;}=account;
        public int Id {get;private set;}
        public WorkerEntry? Worker {get;private set;}
        public string State {get;private set;}="paused";
        public string Detail {get;private set;}="";
        public string Label=>$"{Id:00}  {Account}";
        public string StatusLabel=>State.ToUpperInvariant();
        public Brush StatusBrush=>(Brush)Application.Current.FindResource(State=="active"?"GreenBrush":State=="error"?"RedBrush":State=="starting"||State=="retrying"?"YellowBrush":"SubTextBrush");
        public string Location=>Worker==null || string.IsNullOrEmpty(Worker.Galaxy)?"Awaiting assignment":"Galaxy "+Worker.Galaxy;
        public string FramePath=>Worker?.FramePath??"";
        public double FrameUpdated=>Worker?.FrameUpdated??0;
        public void Update(int id,WorkerEntry? worker,bool running) {
            Id=id;Worker=worker;State=running?worker?.State??"waiting":"paused";
            Detail=worker?.Detail??(running?"Waiting for this account's browser session to start.":"Ready to start from its saved progress when you resume scanning.");
            PropertyChanged?.Invoke(this,new PropertyChangedEventArgs(null));
        }
        public event PropertyChangedEventHandler? PropertyChanged;
    }
}
