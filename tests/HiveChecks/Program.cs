using EternalVoidPanel;

int checks=0;
void Check(bool value,string message){if(!value)throw new Exception(message);checks++;}
PlayerEntry P(string name,string alliance,params string[] coordinates)=>new(){Name=name,Alliance=alliance,Coordinates=coordinates,Observed=100};
string[] At(int galaxy,int system,int count)=>Enumerable.Range(5,count).Select(p=>$"{galaxy}:{system}:{p}").ToArray();
var mixed=new[]{P("Alpha","RED",At(1,20,4)),P("Beta","BLUE",At(1,22,4))};
var hive=HiveDetector.Detect(mixed).Single();
Check(hive.FirstSystem==20 && hive.LastSystem==22 && hive.PlanetCount==8 && hive.Members.Length==2,"Three-system mixed-owner hive");
Check(hive.Members.All(m=>m.Coordinates.Length==4),"Per-player local planet counts");
Check(hive.Matches("alpha","red") && !hive.Matches("alpha","blue"),"Both filters must match the same member");
Check(hive.Members.Length==2 && hive.Matches("alpha",""),"Filtering retains the full hive");
Check(hive.CopyText.Contains("```\n1:20:5 · 1:20:6") && hive.CopyText.Contains("Beta"),"Compact Discord copy");
Check(HiveDetector.Detect(mixed,9).Count==0 && HiveDetector.Detect(mixed,8,1).Count==0,"Threshold and width controls");
Check(HiveDetector.Detect(new[]{P("Solo","",At(9,499,8))}).Single().Members.Length==1,"Single-player hive and last system");
Check(HiveDetector.Detect(new[]{P("A","",At(1,499,4)),P("B","",At(2,1,4))}).Count==0,"No galaxy boundary wrapping");
Check(HiveDetector.Detect(new[]{P("A","",At(1,1,4)),P("A","",At(1,4,4))}).Count==0,"No fourth-system bridge");
var chain=HiveDetector.Detect(new[]{P("Chain","",Enumerable.Range(1,7).SelectMany(s=>At(1,s,8)).ToArray())});
Check(chain.Count==3 && chain.Sum(h=>h.PlanetCount)==56 && chain.All(h=>h.LastSystem-h.FirstSystem<3),"Dense chains split into bounded non-overlapping hives");
Check(chain.SelectMany(h=>h.Members).SelectMany(m=>m.Coordinates).Distinct().Count()==56,"No double counting overlapping windows");
var dirty=P("Human","",At(1,10,7).Concat(new[]{"1:10:5","1:10:1","1:10:21","bad","10:10:5","1:500:5"}).ToArray());
Check(HiveDetector.Detect(new[]{dirty,P("bot_1_10_12","", "1:10:12")}).Count==0,"Duplicates, NPCs, bots and malformed coordinates excluded");
Check(HiveDetector.Detect(mixed.Reverse()).Single().CopyText==hive.CopyText,"Stable ordering independent of source order");
Console.WriteLine($"{checks} hive checks passed");
