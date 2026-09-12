using System.Windows;
using System.Windows.Controls;

namespace EternalVoidPanel.Browsing;

public sealed class BrowserAssistantDialog : Window
{
    public BrowserAssistantDialog(BrowserWorkspace workspace,BrowserPane[] panes,BrowserPane? selected)
    {
        Title="Browser assistant";Width=560;Height=570;MinWidth=480;MinHeight=500;
        WindowStartupLocation=WindowStartupLocation.CenterOwner;Background=BrowserPane.Brush("#111111");Foreground=BrowserPane.Brush("#EEEEEE");
        Resources.MergedDictionaries.Add(new ResourceDictionary {Source=new Uri("/EOG;component/Browsing/BrowserTheme.xaml",UriKind.Relative)});
        var body=new StackPanel {Margin=new Thickness(24)};Content=new ScrollViewer {Content=body,VerticalScrollBarVisibility=ScrollBarVisibility.Auto};
        void Text(string value,int size=12) {body.Children.Add(new TextBlock {Text=value,FontSize=size,TextWrapping=TextWrapping.Wrap,Margin=new Thickness(0,0,0,12)});}
        Text("You choose when it takes control",23);
        Text("Browsers start in manual mode. Select a browser and its permissions, then enable control for this session.");
        var pick=new ComboBox {Margin=new Thickness(0,0,0,14),IsEditable=true,IsReadOnly=true,
            ItemsSource=panes.Select(p=>$"Browser {p.Index+1:00} · {(string.IsNullOrEmpty(p.State.Account)?"No account assigned":p.State.Account)}").ToArray()};
        pick.SelectedIndex=Array.IndexOf(panes,selected ?? panes.FirstOrDefault());body.Children.Add(pick);
        var identity=new CheckBox {Content=new TextBlock {Text="I confirm this browser is signed in as the assigned account (EV-T ORION 1)",TextWrapping=TextWrapping.Wrap,MaxWidth=460},Margin=new Thickness(0,0,0,14)};
        body.Children.Add(identity);
        var scan=new CheckBox {Content="Galaxy scanning · navigate and read coordinates",Margin=new Thickness(0,4,0,10)};
        var upgrades=new CheckBox {Content="Upgrade profiles · allow approved building/research actions",Margin=new Thickness(0,0,0,14)};
        body.Children.Add(scan);body.Children.Add(upgrades);
        Text("Upgrade permission does not start a plan. Use Start in Upgrade bot after enabling this browser.");
        Text("Fleet saving, Nebula/Gamma runs and purchases are unavailable until their game screens are calibrated.");
        Text("Use your existing signed-in game page. The assistant uses only this pane and does not sign in to another browser.");
        var actions=new WrapPanel();body.Children.Add(actions);
        var enable=new Button {Content="Enable selected browser",Margin=new Thickness(0,0,8,8)};
        var manual=new Button {Content="Take control / turn off",Margin=new Thickness(0,0,0,8)};
        actions.Children.Add(enable);actions.Children.Add(manual);
        var message=new TextBlock {Text="Assistant is off until you enable it.",TextWrapping=TextWrapping.Wrap,Margin=new Thickness(0,10,0,0)};body.Children.Add(message);
        BrowserPane? Pane()=>pick.SelectedIndex>=0&&pick.SelectedIndex<panes.Length?panes[pick.SelectedIndex]:null;
        void Refresh() {bool controlled=Pane()?.AssistantControlled==true;enable.IsEnabled=Pane() is not null&&!controlled;manual.IsEnabled=controlled;identity.IsEnabled=scan.IsEnabled=upgrades.IsEnabled=!controlled;if(controlled){identity.IsChecked=true;var permissions=workspace.AssistantPermissions(Pane());scan.IsChecked=permissions.Scan;upgrades.IsChecked=permissions.Upgrades;}message.Text=controlled?"Assistant owns this pane. Take control to interact manually.":"Manual control · Assistant off";}
        pick.SelectionChanged+=(_,_)=>{identity.IsChecked=false;scan.IsChecked=false;upgrades.IsChecked=false;Refresh();};Refresh();
        enable.Click+=async(_,_)=>{try {enable.IsEnabled=false;message.Text=await workspace.EnableAssistantAsync(Pane()!,scan.IsChecked==true,upgrades.IsChecked==true,identity.IsChecked==true);}catch(Exception ex){message.Text=ex.Message;}finally{string note=message.Text;Refresh();message.Text=note;}};
        manual.Click+=async(_,_)=>{try {manual.IsEnabled=false;message.Text=await workspace.DisableAssistantAsync(Pane()!);}catch(Exception ex){message.Text=ex.Message;}finally{string note=message.Text;Refresh();message.Text=note;}};
        WindowAppearance.UseDarkTitleBar(this);
    }
}
