using System.Windows;
using System.Windows.Controls;

namespace EternalVoidPanel;
public partial class HiveView : UserControl
{
    private IReadOnlyList<PlayerEntry> players=Array.Empty<PlayerEntry>();
    private List<HiveEntry> detected=[], shown=[];
    private string name="", alliance="";
    private bool ready;
    public HiveView()
    {
        InitializeComponent();Minimum.ItemsSource=Enumerable.Range(2,159);Span.ItemsSource=Enumerable.Range(1,10);
        Minimum.SelectedItem=8;Span.SelectedItem=3;ready=true;Rebuild();
    }
    public void Update(IReadOnlyList<PlayerEntry> current, string playerName, string allianceName)
    {
        bool changed=!ReferenceEquals(players,current);players=current;name=playerName;alliance=allianceName;
        if(changed)Rebuild();else Filter();
    }
    private void SettingsChanged(object sender,SelectionChangedEventArgs e){if(ready)Rebuild();}
    private void Rebuild()
    {
        detected=HiveDetector.Detect(players,(int)Minimum.SelectedItem,(int)Span.SelectedItem);Filter();
    }
    private void Filter()
    {
        shown=detected.Where(h=>h.Matches(name,alliance)).ToList();Cards.ItemsSource=shown;
        Summary.Text=$"{shown.Count:N0} hives · {shown.Sum(h=>h.PlanetCount):N0} planets · {shown.SelectMany(h=>h.Members).Select(m=>m.Name).Distinct(StringComparer.OrdinalIgnoreCase).Count():N0} players";
        Empty.Visibility=shown.Count==0?Visibility.Visible:Visibility.Collapsed;CopyShown.IsEnabled=shown.Count>0;
    }
    private void Copy(string value)
    {
        try{Clipboard.SetText(value);Feedback.Text="Copied in Discord format.";}
        catch(Exception){Feedback.Text="The clipboard is busy. Try again.";}
    }
    private void CopyHive(object sender,RoutedEventArgs e)=>Copy(((Button)sender).Tag?.ToString()??"");
    private void CopyAll(object sender,RoutedEventArgs e){if(shown.Count>0)Copy(string.Join("\n\n",shown.Select(h=>h.CopyText)));}
    public void Verify()
    {
        if((int)Minimum.SelectedItem!=8 || (int)Span.SelectedItem!=3)throw new Exception("Hive defaults changed");
        if(shown.Sum(h=>h.PlanetCount)!=shown.SelectMany(h=>h.Members).SelectMany(m=>m.Coordinates).Distinct().Count())throw new Exception("Hive coordinates counted more than once");
        if(shown.Any(h=>!h.Matches(name,alliance)))throw new Exception("Hive filtering failed");
    }
}
