using System.Collections.ObjectModel;
using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace EternalVoidPanel;

public sealed class AutomationView : UserControl
{
    public Func<object,Task<JsonElement>>? Request { get; set; }
    readonly ListBox profiles=new(), stepsList=new(), rulesList=new();
    readonly ComboBox account=new(), mode=new(), kind=new(), target=new(), metric=new(), comparison=new(), ruleAction=new(), presets=new();
    readonly TextBox name=new(), coordinate=new(), interval=new(), start=new(), end=new(), metal=new(), crystal=new(), gas=new(), cost=new(), energy=new(), ceiling=new(), stepValue=new(), ruleValue=new(), cooldown=new(), gammaLimit=new(), presetName=new();
    readonly TextBlock message=new(), live=new(), activity=new();
    readonly Image preview=new() { MaxHeight=360,Stretch=Stretch.Uniform,HorizontalAlignment=HorizontalAlignment.Left };
    readonly ObservableCollection<PlanStep> steps=[];
    readonly ObservableCollection<WatchRule> rules=[];
    readonly StackPanel settings=new(), plan=new(), monitor=new();
    readonly Button save=new(), run=new(), pause=new();
    List<JsonNode> entries=[], savedPresets=[];
    string id="", imageKey="";
    bool polling, filling, operation;
    public AutomationView()
    {
        var grid=new Grid();grid.ColumnDefinitions.Add(new(){Width=new GridLength(235)});grid.ColumnDefinitions.Add(new(){Width=new GridLength(1,GridUnitType.Star)});Content=grid;
        var left=new DockPanel { Margin=new Thickness(0,0,18,0) };grid.Children.Add(left);
        var title=Text("Upgrade profiles",22,"BrandBrush");DockPanel.SetDock(title,Dock.Top);left.Children.Add(title);
        var create=Button("+ New profile",(_,_)=>New());DockPanel.SetDock(create,Dock.Top);left.Children.Add(create);
        var presetPanel=new StackPanel { Margin=new Thickness(0,15,0,0) };DockPanel.SetDock(presetPanel,Dock.Bottom);left.Children.Add(presetPanel);
        presetPanel.Children.Add(Text("SAVED PRESETS",11));presetPanel.Children.Add(presets);presetPanel.Children.Add(Button("Load into profile",(_,_)=>LoadPreset()));
        Field(presetPanel,"Preset name",presetName);presetPanel.Children.Add(Button("Save preset",async(_,_)=>await Do(async()=> {await Save();await Send(new {command="automation_preset",id,name=presetName.Text});await Poll();message.Text="Preset saved without account details.";})));
        StyleList(profiles);left.Children.Add(profiles);profiles.SelectionChanged+=(_,_)=> {if(!filling && profiles.SelectedIndex>=0)Load(entries[profiles.SelectedIndex]["profile"]!.DeepClone());};
        var right=new DockPanel();Grid.SetColumn(right,1);grid.Children.Add(right);
        var header=new StackPanel();DockPanel.SetDock(header,Dock.Top);right.Children.Add(header);
        header.Children.Add(Text("Account automation",26,"BrandBrush"));header.Children.Add(Text("Saved plans, scheduled checks and local watch alerts. Profiles start paused.",12));
        var actions=new WrapPanel {Margin=new Thickness(0,12,0,0)};header.Children.Add(actions);
        SetupButton(save,"Save profile",async(_,_)=>await Do(Save));SetupButton(run,"▶ Start",async(_,_)=>await Do(async()=>{await Save();var r=await Send(new {command="automation_start",id});message.Text=r["message"]!.ToString();await Poll();}));
        SetupButton(pause,"Ⅱ Pause",async(_,_)=>await Do(async()=>{var r=await Send(new {command="automation_pause",id});message.Text=r["message"]!.ToString();await Poll();}));
        actions.Children.Add(save);actions.Children.Add(run);actions.Children.Add(pause);actions.Children.Add(Button("Delete",async(_,_)=>await Do(async()=>{await Send(new {command="automation_delete",id});New();await Poll();})));
        message.TextWrapping=TextWrapping.Wrap;message.Foreground=Brush("SubTextBrush");message.Margin=new Thickness(0,2,0,10);header.Children.Add(message);
        var nav=new WrapPanel();header.Children.Add(nav);
        foreach(var item in new[]{("Profile settings",settings),("Plan & watch rules",plan),("Live status",monitor)})nav.Children.Add(Button(item.Item1,(_,_)=>Show(item.Item2)));
        var body=new Grid();body.Children.Add(settings);body.Children.Add(plan);body.Children.Add(monitor);right.Children.Add(new ScrollViewer {Content=body,VerticalScrollBarVisibility=ScrollBarVisibility.Auto});
        Field(settings,"Profile name",name);Field(settings,"Account · credentials come from Agents & accounts",account);Field(settings,"Colony coordinate · this colony must be selected in the account",coordinate);
        mode.ItemsSource=new[]{"watch","plan","auto"};Field(settings,"Mode",mode);settings.Children.Add(Text("Watch reads only. Plan follows your steps. Auto restores power before following the plan; it does not yet optimize the full economy.",12));
        var timing=new UniformGridProxy();settings.Children.Add(timing);Field(timing,"Check every (seconds, minimum 10)",interval);Field(timing,"Start at (local date/time, optional)",start);Field(timing,"Stop at (local date/time, optional)",end);
        settings.Children.Add(Text("Keep these resources in reserve",16));var reserves=new UniformGridProxy();settings.Children.Add(reserves);Field(reserves,"Metal",metal);Field(reserves,"Crystal",crystal);Field(reserves,"Gas",gas);
        Field(settings,"Maximum cost per resource, per upgrade",cost);var power=new UniformGridProxy();settings.Children.Add(power);Field(power,"Auto energy target",energy);Field(power,"Auto Solar Plant level ceiling",ceiling);
        settings.Children.Add(Text("Starting a profile borrows only its account from the scanner. Closing EOG keeps profiles running. Use Pause or a stop time to end a session.",12));
        plan.Children.Add(Text("Ordered plan",19));plan.Children.Add(Text("A step completes when the target level is observed. Resource shortages wait for the next check. Only calibrated buildings and research appear here.",12));
        kind.ItemsSource=new[]{"building","research","wait","resource"};kind.SelectionChanged+=(_,_)=>Targets();kind.SelectedIndex=0;
        var add=new UniformGridProxy();plan.Children.Add(add);Field(add,"Task",kind);Field(add,"Building / research / resource",target);Field(add,"Target level / amount / wait seconds",stepValue);
        plan.Children.Add(Button("+ Add step",(_,_)=> {try {steps.Add(new(){Kind=kind.Text,Name=target.Text,Value=Number(stepValue,"Step target")});}catch(Exception ex){message.Text=ex.Message;}}));
        StyleList(stepsList);stepsList.ItemsSource=steps;stepsList.MinHeight=90;stepsList.MaxHeight=235;plan.Children.Add(stepsList);
        var moves=new WrapPanel();plan.Children.Add(moves);moves.Children.Add(Button("Move up",(_,_)=>Move(-1)));moves.Children.Add(Button("Move down",(_,_)=>Move(1)));moves.Children.Add(Button("Remove step",(_,_)=> {if(stepsList.SelectedItem is PlanStep s)steps.Remove(s);}));
        plan.Children.Add(Text("Watch rules",19));plan.Children.Add(Text("Thresholds create local alerts, with a cooldown between repeats. They run in every mode. Owned Gamma rules act only in Plan or Auto mode.",12));
        metric.ItemsSource=new[]{"Metal","Crystal","Gas","Energy","Safe nebula runs"};metric.SelectedIndex=0;comparison.ItemsSource=new[]{"<=",">="};comparison.SelectedIndex=0;
        ruleAction.ItemsSource=new[]{"Local alert","Use owned Gamma"};ruleAction.SelectedIndex=0;
        var watch=new UniformGridProxy();plan.Children.Add(watch);Field(watch,"Metric",metric);Field(watch,"Condition",comparison);Field(watch,"Threshold",ruleValue);Field(watch,"Cooldown (seconds)",cooldown);
        var ruleSettings=new UniformGridProxy();plan.Children.Add(ruleSettings);Field(ruleSettings,"Rule action",ruleAction);Field(ruleSettings,"Owned Gamma limit per account / 24 hours",gammaLimit);
        plan.Children.Add(Button("+ Add watch rule",(_,_)=> {try{rules.Add(new(){Metric=metric.Text=="Safe nebula runs"?"safe_runs":metric.Text.ToLowerInvariant(),Op=comparison.Text,Value=Number(ruleValue,"Threshold"),Cooldown=Number(cooldown,"Cooldown"),Action=ruleAction.Text=="Use owned Gamma"?"use_gamma":"alert"});}catch(Exception ex){message.Text=ex.Message;}}));
        StyleList(rulesList);rulesList.ItemsSource=rules;rulesList.MaxHeight=180;plan.Children.Add(rulesList);plan.Children.Add(Button("Remove rule",(_,_)=> {if(rulesList.SelectedItem is WatchRule r)rules.Remove(r);}));
        plan.Children.Add(Text("For owned Gamma use: choose Safe nebula runs <= 0 and Use owned Gamma. Uses one item at a time within the limit. Watch mode only alerts. Store purchases are disabled.",12,"YellowBrush"));
        live.TextWrapping=TextWrapping.Wrap;live.FontSize=15;live.Margin=new Thickness(0,12,0,15);monitor.Children.Add(live);monitor.Children.Add(preview);
        monitor.Children.Add(Text("Recent actions & alerts",19));activity.TextWrapping=TextWrapping.Wrap;activity.FontFamily=new FontFamily("Consolas");activity.FontSize=12;monitor.Children.Add(activity);
        New();Show(settings);
    }
    static Brush Brush(string key)=>(Brush)Application.Current.FindResource(key);
    static TextBlock Text(string text,int size=13,string brush="SubTextBrush")=>new(){Text=text,FontSize=size,Foreground=Brush(brush),TextWrapping=TextWrapping.Wrap,Margin=new Thickness(0,5,0,10)};
    static Button Button(string text,RoutedEventHandler action){var b=new Button();SetupButton(b,text,action);return b;}
    static void SetupButton(Button b,string text,RoutedEventHandler action){b.Content=text;b.Margin=new Thickness(0,0,8,8);b.Click+=action;}
    static void Field(Panel panel,string label,Control c){var p=new StackPanel {Margin=new Thickness(0,0,12,10)};p.Children.Add(Text(label,11));c.MinHeight=34;p.Children.Add(c);panel.Children.Add(p);}
    static void StyleList(ListBox list){list.Background=Brush("BgBrush");list.Foreground=Brush("TextBrush");list.BorderBrush=Brush("BorderBrush");list.SetValue(ScrollViewer.HorizontalScrollBarVisibilityProperty,ScrollBarVisibility.Disabled);}
    sealed class UniformGridProxy : System.Windows.Controls.Primitives.UniformGrid { public UniformGridProxy(){Rows=1;} }
    void Show(StackPanel selected){foreach(var panel in new[]{settings,plan,monitor})panel.Visibility=panel==selected?Visibility.Visible:Visibility.Collapsed;}
    void Targets(){target.ItemsSource=(kind.SelectedItem?.ToString()??"building") switch {"building"=>new[]{"Solar Plant","Gas Storage","Research Lab"},"research"=>new[]{"Energy Tech","Laser Tech","Ion Tech","Hyperspace Tech","Computer Tech","Espionage Tech","Astrophysics Tech","Combustion Drive"},"resource"=>new[]{"metal","crystal","gas"},_=>new[]{"Wait"}};target.SelectedIndex=0;}
    void Move(int offset){int i=stepsList.SelectedIndex;if(i>=0 && i+offset>=0 && i+offset<steps.Count){steps.Move(i,i+offset);stepsList.SelectedIndex=i+offset;}}
    static double Number(TextBox box,string label)=>double.TryParse(box.Text,NumberStyles.Float,CultureInfo.InvariantCulture,out double n)&&double.IsFinite(n)?n:throw new InvalidOperationException(label+" must be a number.");
    static string? TimeValue(TextBox box)=>string.IsNullOrWhiteSpace(box.Text)?null:DateTimeOffset.TryParse(box.Text,out var t)?t.ToString("o"):throw new InvalidOperationException("Use a local date and time, for example 2026-09-10 18:30.");
    JsonObject Form()=>new(){["id"]=id,["name"]=name.Text,["account"]=account.Text,["coordinate"]=coordinate.Text,["mode"]=mode.Text,["interval"]=Number(interval,"Check interval"),["startAt"]=TimeValue(start),["endAt"]=TimeValue(end),["reserves"]=new JsonObject{["metal"]=Number(metal,"Metal reserve"),["crystal"]=Number(crystal,"Crystal reserve"),["gas"]=Number(gas,"Gas reserve")},["max_upgrade_cost"]=Number(cost,"Cost limit"),["energy_margin"]=Number(energy,"Energy target"),["solar_level_limit"]=Number(ceiling,"Solar ceiling"),["gamma_limit"]=Number(gammaLimit,"Gamma limit"),["steps"]=JsonSerializer.SerializeToNode(steps.Select(s=>new{kind=s.Kind,name=s.Name,value=s.Value})),["rules"]=JsonSerializer.SerializeToNode(rules.Select(r=>new{metric=r.Metric,op=r.Op,value=r.Value,cooldown=r.Cooldown,action=r.Action}))};
    void New(){Load(new JsonObject{["id"]="",["name"]="",["account"]="",["coordinate"]="",["mode"]="watch",["interval"]=30,["max_upgrade_cost"]=10000000,["energy_margin"]=100,["solar_level_limit"]=20});message.Text="New profile · choose an account and colony, then save.";}
    static string S(JsonNode? p,string key,string fallback="")=>p?[key]?.ToString()??fallback;
    void Load(JsonNode p){id=S(p,"id");name.Text=S(p,"name");account.SelectedItem=S(p,"account");coordinate.Text=S(p,"coordinate");mode.SelectedItem=S(p,"mode","watch");interval.Text=S(p,"interval","30");cost.Text=S(p,"max_upgrade_cost","10000000");energy.Text=S(p,"energy_margin","100");ceiling.Text=S(p,"solar_level_limit","20");gammaLimit.Text=S(p,"gamma_limit","1");metal.Text=S(p["reserves"],"metal","0");crystal.Text=S(p["reserves"],"crystal","0");gas.Text=S(p["reserves"],"gas","0");start.Text=Local(S(p,"startAt"));end.Text=Local(S(p,"endAt"));steps.Clear();rules.Clear();foreach(var s in p["steps"]?.AsArray()??[])steps.Add(new(){Kind=S(s,"kind"),Name=S(s,"name"),Value=double.Parse(S(s,"value"),CultureInfo.InvariantCulture)});foreach(var r in p["rules"]?.AsArray()??[])rules.Add(new(){Metric=S(r,"metric"),Op=S(r,"op"),Value=double.Parse(S(r,"value"),CultureInfo.InvariantCulture),Cooldown=double.Parse(S(r,"cooldown"),CultureInfo.InvariantCulture),Action=S(r,"action","alert")});stepValue.Text="1";ruleValue.Text="0";cooldown.Text="300";RenderStatus();}
    static string Local(string text)=>DateTimeOffset.TryParse(text,out var t)?t.LocalDateTime.ToString("yyyy-MM-dd HH:mm:ss"):"";
    async Task<JsonNode> Send(object r){if(Request is null)throw new InvalidOperationException("Connecting…");return JsonNode.Parse((await Request(r)).GetRawText())!;}
    async Task Save(){var p=await Send(new{command="automation_save",profile=Form()});id=S(p,"id");message.Text="Profile saved. Start when ready.";await Poll();}
    async Task Do(Func<Task> action){if(operation)return;operation=true;try{await action();}catch(Exception ex){message.Text=ex.Message;}finally{operation=false;}}
    void LoadPreset(){if(presets.SelectedIndex<0)return;if(entries.Any(e=>S(e["profile"],"id")==id && (e["reserved"]?.GetValue<bool>()??false))){message.Text="Pause this profile before loading a preset.";return;}try{var p=Form();foreach(var v in savedPresets[presets.SelectedIndex]["settings"]!.AsObject())p[v.Key]=v.Value?.DeepClone();Load(p);message.Text="Preset loaded. Save to apply it to this profile.";}catch(Exception ex){message.Text=ex.Message;}}
    public async Task Poll(){if(polling||Request is null)return;polling=true;try{var snapshot=await Send(new{command="automation_snapshot"});entries=snapshot["profiles"]!.AsArray().Select(x=>x!).ToList();savedPresets=snapshot["presets"]!.AsArray().Select(x=>x!).ToList();filling=true;profiles.ItemsSource=entries.Select(e=>S(e["profile"],"name")+"\n"+S(e["profile"],"account")+" · "+S(e["status"],"state")).ToArray();profiles.SelectedIndex=entries.FindIndex(e=>S(e["profile"],"id")==id);string chosen=account.Text;account.ItemsSource=snapshot["accounts"]!.AsArray().Select(x=>x!.ToString()).ToArray();account.SelectedItem=chosen;string preset=presets.Text;presets.ItemsSource=savedPresets.Select(x=>S(x,"name")).ToArray();presets.SelectedItem=preset;filling=false;RenderStatus();}catch(Exception ex){message.Text=ex.Message;}finally{filling=false;polling=false;}}
    void RenderStatus(){var entry=entries.FirstOrDefault(e=>S(e["profile"],"id")==id);bool reserved=entry?["reserved"]?.GetValue<bool>()??false;save.IsEnabled=run.IsEnabled=!reserved;pause.IsEnabled=reserved;settings.IsEnabled=plan.IsEnabled=!reserved;
        if(entry is null){live.Text="Save a profile to see its status.";activity.Text="";preview.Source=null;return;}
        var status=entry["status"];int index=entry["progress"]?["index"]?.GetValue<int>()??0;int count=entry["profile"]?["steps"]?.AsArray().Count??0;string next=double.TryParse(S(status,"nextCheck"),out var stamp)?DateTimeOffset.FromUnixTimeSeconds((long)stamp).LocalDateTime.ToString():"—";
        live.Text=$"{S(status,"state").ToUpperInvariant()} · {S(entry["profile"],"account")} · {S(entry["profile"],"coordinate")}\n{S(status,"message")}\nPlan: {index} / {count} steps complete · Next check: {next}";
        activity.Text=string.Join("\n\n",entry["activity"]!.AsArray().Select(a=>DateTimeOffset.FromUnixTimeSeconds((long)(a?["time"]?.GetValue<double>()??0)).LocalDateTime.ToString("HH:mm:ss")+"  "+S(a,"message")));
        string path=S(status,"screenshot");if(System.IO.File.Exists(path)){string key=path+System.IO.File.GetLastWriteTimeUtc(path).Ticks;if(key!=imageKey){try{var bitmap=new System.Windows.Media.Imaging.BitmapImage();bitmap.BeginInit();bitmap.CacheOption=System.Windows.Media.Imaging.BitmapCacheOption.OnLoad;bitmap.UriSource=new Uri(path);bitmap.EndInit();bitmap.Freeze();preview.Source=bitmap;imageKey=key;}catch(System.IO.IOException){}}}else preview.Source=null;
    }
    public void VerifyEditor()
    {
        New();
        if(!string.IsNullOrEmpty(account.Text)||!string.IsNullOrEmpty(name.Text)||mode.Text!="watch")throw new Exception("New automation profile must be blank and read-only");
        kind.SelectedItem="research";Targets();if(target.Items.Count!=8)throw new Exception("Research choices missing");
        kind.SelectedItem="building";Targets();if(target.Items.Count!=3)throw new Exception("Building choices missing");
        steps.Add(new(){Kind="building",Name="Solar Plant",Value=5});steps.Add(new(){Kind="research",Name="Computer Tech",Value=10});
        stepsList.SelectedIndex=1;Move(-1);if(steps[0].Name!="Computer Tech")throw new Exception("Step reordering failed");
        rules.Add(new(){Metric="safe_runs",Op="<=",Value=0,Cooldown=300,Action="use_gamma"});
        var p=Form();if(p["steps"]!.AsArray().Count!=2 || p["rules"]!.AsArray().Count!=1)throw new Exception("Plan form roundtrip failed");
        Load(p);if(steps.Count!=2||rules.Count!=1||rules[0].Action!="use_gamma"||Form()["gamma_limit"]!.GetValue<double>()!=1)throw new Exception("Plan loading failed");
        Show(plan);
    }
    public void FinishVerification(){New();Show(settings);}
    sealed class PlanStep {public string Kind{get;set;}="";public string Name{get;set;}="";public double Value{get;set;}public override string ToString()=>Kind=="wait"?$"Wait {Value:g} seconds":Kind=="resource"?$"Wait for {Value:g} {Name}":$"{Name} → level {Value:g}";}
    sealed class WatchRule {public string Metric{get;set;}="";public string Op{get;set;}="";public double Value{get;set;}public double Cooldown{get;set;}public string Action{get;set;}="alert";public override string ToString()=>$"{(Action=="use_gamma"?"Use owned Gamma":"Alert")} when {(Metric=="safe_runs"?"Safe nebula runs":Metric)} {Op} {Value:g} · every {Cooldown:g}s while true";}
}
