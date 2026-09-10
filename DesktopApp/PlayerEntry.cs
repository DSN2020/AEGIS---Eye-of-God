namespace EternalVoidPanel;

public sealed class PlayerEntry {
 public string Name {get;set;}="";public string? Alliance {get;set;}public string[] Coordinates {get;set;}=[];public double Observed {get;set;}
 public string AllianceLabel=>Alliance==null?"Not recorded":Alliance.Length==0 || Alliance=="-"?"No alliance":Alliance;
 public string CoordinatesText=>string.Join("   ·   ",Coordinates);
 public string CountLabel=>$"{Coordinates.Length} coordinates  ·  Last seen {DateTimeOffset.FromUnixTimeSeconds((long)Observed).LocalDateTime:MMM d, h:mm tt}";
 public string CopyText=>$"{Name}  [{AllianceLabel}]\n```\n{string.Join(" · ",Coordinates)}\n```";
}
