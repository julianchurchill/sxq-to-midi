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

- ... Do tied notes - half tied dotted 8th (11x16ths), half tied quarter tied 16th (13x16ths), half tied dotted quarter (14x16ths), half tied quarter tied dotted 8th (15x16ths)
- Horns in latest-broken.sxq are converted at too short a note length - investigate and fix. Is it because they were half/dotted halfs/whole notes?
    - First note in latest-broken.sxq horns is 79, 20 (4F, 14), possibly a half note tied to an 8th?
    - Third note in latest-broken.sxq horns is 49, 12 (31, 0C), possibly a double dotted quarter?
- Handle dotted 16ths
- 16th notes on a 32nd note resolution grid (should set Pules Per Quarter Note to 960*2=1920)
- Handle 32nd notes
- Not all SXQ tracks are midi - don't export them as we run out of real midi track space in MPC Beats. What are they?
- Handle track volume curve
- Handle tempo (not in a special track 0 conductor track if possible)
- Handle time signature (not in a special track 0 conductor track if possible)
- Handle triplets
- Unit tests

# Done

- Handle tied notes - quarter tied 16th (5x16ths), quarter tied dotted 8th (7x16ths), half tied 16th (9x16ths), half tied 8th (10x16ths)
- Handle dotted quarters, halfs, whole, dotted halfs, dotted whole
- Handle parallel notes with different pitches
- Ensure variable velocity is being converted
- Acceptance tests - examples of SXQ to MIDI file conversion
