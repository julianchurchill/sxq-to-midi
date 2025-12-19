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

- Handle notes tied with 32nds
- Is there a pattern to the note length bytes that means we can avoid a lookup table and use a formula instead?
- Horns in broken.sxq are converted at too short a note length - investigate and fix. Is it because they were half/dotted halfs/whole notes?
    - Third note in broken.sxq horns is 49, 12 (31, 0C), possibly a tied 32nd?
    - Other unknown notes are (15, 58), (35, 23), (46, 23), (70, 23), (71, 7), (73, 10), (84, 11), (100, 10)
- Not all SXQ tracks are midi - don't export them as we run out of real midi track space in MPC Beats. What are they?
- Handle track volume curve
- Handle tempo (not in a special track 0 conductor track if possible)
- Handle time signature (not in a special track 0 conductor track if possible)
- Handle triplets
- Unit tests

# Done

- Handle 2 bar, 3 bar and 4 bar notes
- Handle dotted 16ths
- Preserve 32nd note resolution grid from SXQ file to MIDI - looks like this is in a different file, perhaps xpj, xal or project settings
- Handle 32nd notes
- Handle tied notes - quarter tied 16th (5x16ths), quarter tied dotted 8th (7x16ths), half tied 16th (9x16ths), half tied 8th (10x16ths), half tied dotted 8th (11x16ths), half tied quarter tied 16th (13x16ths), half tied dotted quarter (14x16ths), half tied quarter tied dotted 8th (15x16ths)
- Handle dotted quarters, halfs, whole, dotted halfs, dotted whole
- Handle parallel notes with different pitches
- Ensure variable velocity is being converted
- Acceptance tests - examples of SXQ to MIDI file conversion
