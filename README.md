# Dotnet Console App

A dotnet console app to analyse an SXQ file, output event information and attempt a basic split into individual single track SXQ files.

## Created By

`dotnet new console`
`dotnet package add Melanchall.DryWetMidi`

## Run With

`dotnet run .\Programs.cs <sxq file>`

# Python Script

A python script generated with AI to convert SXQ files to MIDI.

## Run With

`python .\sxq_to_midi.py .\input.sxq output.mid`

# TODO - sxq_to_midi.py

- Ensure variable velocity is being converted
- Handle parallel notes with different pitches
- Handle tempo (not in a special track 0 conductor track if possible)
- Handle time signature (not in a special track 0 conductor track if possible)
- Handle triplets
