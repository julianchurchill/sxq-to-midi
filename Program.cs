// See https://aka.ms/new-console-template for more information
using Melanchall.DryWetMidi.Core;
using Melanchall.DryWetMidi.Interaction;

var midiFile = MidiFile.Read(args[1]);
var tempoMap = midiFile.GetTempoMap();

var count = 0;
Console.WriteLine($"File {args[1]}");
Console.WriteLine("TrackChunks:");
foreach (var chunk in midiFile.GetTrackChunks())
{
    var timedEvents = chunk.GetTimedEvents();
    var midiEvent = (timedEvents.SingleOrDefault(
        t => t.Event.EventType == MidiEventType.SequenceTrackName)?.Event) as SequenceTrackNameEvent;
    var sequenceTrackName = midiEvent?.Text.Replace("\0", "") ?? "unknown";
    Console.WriteLine($"  Sequence/Track Name: {sequenceTrackName}");
    foreach (var timedEvent in timedEvents)
    {
        Console.WriteLine($"    eventType {timedEvent.Event.EventType} event content '{timedEvent.Event}'");
    }

    var filename = $"./{count}-{sequenceTrackName}.sxq";
    Console.WriteLine($"* Writing '{filename}'");
    new MidiFile(chunk).Write(
        filename,
        overwriteFile: false,
        format: MidiFileFormat.SingleTrack);
    count++;
}

Console.WriteLine("TempoMap:");
Console.WriteLine($"  {midiFile.GetTempoMap()}");

Console.WriteLine("Notes:");
foreach (var note in midiFile.GetNotes())
{
    var time = note.TimeAs<MetricTimeSpan>(tempoMap);
    var length = note.LengthAs<MetricTimeSpan>(tempoMap);
    Console.WriteLine($"  {note} at {time} with length of {length}");
}