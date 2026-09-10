namespace EternalVoidPanel;

public sealed record HiveMember(string Name, string Alliance, string[] Coordinates)
{
    public string Label => $"{Name}  ·  {Coordinates.Length} planets  ·  {Alliance}";
    public string CoordinatesText => string.Join(" · ", Coordinates);
    public string CopyText => $"{Name} [{Alliance}] · {Coordinates.Length} planets\n```\n{CoordinatesText}\n```";
}

public sealed record HiveEntry(int Galaxy, int FirstSystem, int LastSystem, HiveMember[] Members, string SystemsText)
{
    public int PlanetCount => Members.Sum(m => m.Coordinates.Length);
    public string Location => $"Galaxy {Galaxy} · " + (FirstSystem == LastSystem ? $"System {FirstSystem}" : $"Systems {FirstSystem}–{LastSystem}");
    public string Summary => $"{PlanetCount} planets · {Members.Length} players · {LastSystem-FirstSystem+1} systems wide";
    public string CopyText => $"{Location} · {Summary}\n{SystemsText}\n\n" + string.Join("\n\n",Members.Select(m=>m.CopyText));
    public bool Matches(string name, string alliance) => Members.Any(m=>m.Name.Contains(name,StringComparison.OrdinalIgnoreCase) && m.Alliance.Contains(alliance,StringComparison.OrdinalIgnoreCase));
}

public static class HiveDetector
{
    private sealed record Planet(PlayerEntry Owner, int Galaxy, int System, int Position)
    {
        public string Coordinate => $"{Galaxy}:{System}:{Position}";
    }
    private sealed record Candidate(int Galaxy, int First, int Last, Planet[] Planets);

    // Build every bounded window, choose the most populated first, then discard
    // overlapping windows. Never chain adjacent candidates into an unlimited hive.
    public static List<HiveEntry> Detect(IEnumerable<PlayerEntry> players, int minimumPlanets=8, int maximumSystems=3)
    {
        if(minimumPlanets<2 || minimumPlanets>160 || maximumSystems<1 || maximumSystems>10)throw new ArgumentOutOfRangeException();
        var coordinates=new Dictionary<string,Planet>();
        foreach(var owner in players.OrderByDescending(p=>p.Observed).ThenBy(p=>p.Name,StringComparer.OrdinalIgnoreCase))
        {
            if(string.IsNullOrWhiteSpace(owner.Name) || owner.Name.StartsWith("bot_",StringComparison.OrdinalIgnoreCase))continue;
            foreach(string raw in owner.Coordinates)
            {
                var parts=raw.Split(':');
                if(parts.Length!=3 || !int.TryParse(parts[0],out int galaxy) || !int.TryParse(parts[1],out int system) || !int.TryParse(parts[2],out int position))continue;
                if(galaxy<1 || galaxy>9 || system<1 || system>499 || position<5 || position>20)continue;
                var planet=new Planet(owner,galaxy,system,position);coordinates.TryAdd(planet.Coordinate,planet);
            }
        }
        var candidates=new List<Candidate>();
        foreach(var galaxy in coordinates.Values.GroupBy(p=>p.Galaxy))
        {
            var systems=galaxy.GroupBy(p=>p.System).OrderBy(g=>g.Key).ToArray();
            for(int i=0;i<systems.Length;i++)
            {
                var included=new List<Planet>();
                for(int j=i;j<systems.Length && systems[j].Key-systems[i].Key<maximumSystems;j++)
                {
                    included.AddRange(systems[j]);
                    if(included.Count>=minimumPlanets)candidates.Add(new(galaxy.Key,systems[i].Key,systems[j].Key,included.ToArray()));
                }
            }
        }
        var selected=new List<Candidate>();
        foreach(var candidate in candidates.OrderByDescending(c=>c.Planets.Length).ThenBy(c=>c.Last-c.First).ThenBy(c=>c.Galaxy).ThenBy(c=>c.First))
        {
            if(selected.Any(c=>c.Galaxy==candidate.Galaxy && c.First<=candidate.Last && candidate.First<=c.Last))continue;
            selected.Add(candidate);
        }
        return selected.Select(c=>new HiveEntry(c.Galaxy,c.First,c.Last,
            c.Planets.GroupBy(p=>p.Owner.Name,StringComparer.OrdinalIgnoreCase).Select(group=>new HiveMember(group.First().Owner.Name,group.First().Owner.AllianceLabel,
                group.OrderBy(p=>p.System).ThenBy(p=>p.Position).Select(p=>p.Coordinate).ToArray()))
                .OrderByDescending(m=>m.Coordinates.Length).ThenBy(m=>m.Name,StringComparer.OrdinalIgnoreCase).ToArray(),
            string.Join(" · ",c.Planets.GroupBy(p=>p.System).OrderBy(g=>g.Key).Select(g=>$"{c.Galaxy}:{g.Key} — {g.Count()} planets")))).ToList();
    }
}
