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

## Install Unit Test Dependencies

`pip install parameterized`

## Run Unit Tests

`python -m unittest`

# TODO - sxq_to_midi.py

- Horns in latest-broken.sxq are converted at too short a note length - investigate and fix. Is it because they were half/dotted halfs/whole notes?
    - Handle dotted 16ths, dotted halfs, whole, dotted whole
- Handle track volume curve
- Handle tempo (not in a special track 0 conductor track if possible)
- Handle time signature (not in a special track 0 conductor track if possible)
- Handle triplets
- Unit tests

# Done

- Handle dotted quarters, halfs
- Handle parallel notes with different pitches
- Ensure variable velocity is being converted
- Acceptance tests - examples of SXQ to MIDI file conversion
