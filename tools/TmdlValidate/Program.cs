// Parses a TMDL folder with Microsoft's Tabular Object Model serializer (the reference TMDL
// parser used by Power BI) and checks the semantic model structure.
// Usage: dotnet run --project tools/TmdlValidate -- powerbi/EloScope.SemanticModel/definition
using Microsoft.AnalysisServices.Tabular;

var folder = args.Length > 0 ? args[0] : "powerbi/EloScope.SemanticModel/definition";
Database database;
try
{
    database = TmdlSerializer.DeserializeDatabaseFromFolder(folder);
}
catch (Exception ex)
{
    Console.Error.WriteLine($"TMDL parsing failed: {ex.Message}");
    return 1;
}

var model = database.Model;
var errors = new List<string>();
Console.WriteLine($"Database '{database.Name}' (compatibility level {database.CompatibilityLevel}), culture {model.Culture}");

foreach (var table in model.Tables)
{
    Console.WriteLine($"  table {table.Name,-24} columns={table.Columns.Count(c => c.Type != ColumnType.RowNumber),2} measures={table.Measures.Count,2} partitions={table.Partitions.Count}");
    if (table.Partitions.Count == 0) errors.Add($"table {table.Name} has no partition");
    foreach (var measure in table.Measures)
    {
        if (string.IsNullOrWhiteSpace(measure.Description)) errors.Add($"measure {measure.Name} has no description");
        if (string.IsNullOrWhiteSpace(measure.DisplayFolder)) errors.Add($"measure {measure.Name} has no display folder");
        if (string.IsNullOrWhiteSpace(measure.FormatString)) errors.Add($"measure {measure.Name} has no format string");
    }
}

foreach (var rel in model.Relationships.OfType<SingleColumnRelationship>())
{
    var manyToOne = rel.FromCardinality == RelationshipEndCardinality.Many && rel.ToCardinality == RelationshipEndCardinality.One;
    var single = rel.CrossFilteringBehavior == CrossFilteringBehavior.OneDirection;
    Console.WriteLine($"  relationship {rel.FromTable.Name}[{rel.FromColumn.Name}] -> {rel.ToTable.Name}[{rel.ToColumn.Name}] many-to-one={manyToOne} single-direction={single}");
    if (!manyToOne || !single) errors.Add($"relationship {rel.Name} is not many-to-one single direction");
}

var dateTable = model.Tables.Find("dim_date");
if (dateTable is null || dateTable.DataCategory != "Time" || !dateTable.Columns.Any(c => c.IsKey))
    errors.Add("dim_date is not marked as a date table (dataCategory Time + key column)");

var measures = model.Tables.SelectMany(t => t.Measures).ToList();
Console.WriteLine($"  {measures.Count} measures, {model.Relationships.Count} relationships, {model.Expressions.Count} expression(s)");
foreach (var e in errors) Console.Error.WriteLine($"ERROR: {e}");
Console.WriteLine(errors.Count == 0 ? "TMDL OK" : $"{errors.Count} error(s)");
return errors.Count == 0 ? 0 : 1;
