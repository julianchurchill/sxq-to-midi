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

- ... Handle swing. Is it implemented by a tiny change in note length? No - it's about note positioning.
    - Swing looks like rc1 is always 0
- Not all SXQ tracks are midi - don't export them as we run out of real midi track space in MPC Beats. What are they?
- Handle track volume curve
- Handle tempo (not in a special track 0 conductor track if possible)
- Handle time signature (not in a special track 0 conductor track if possible)
- Handle triplets
- Handle 2 bars + half/dotted whole tied notes
- Handle 2 bars + quarter/dotted half tied notes
- Handle 2 bars + 8th/dotted quarter tied notes
- Handle 2 bars + 16th/dotted 8th tied notes
- Handle 2 bars + 64th/dotted 32nd tied notes

# Done

- Handle note lengths as a formula and not a look up table
- Handle whole + 16th/dotted 8th tied notes
- Handle whole + 8th/dotted quarter tied notes
- Handle whole + quarter/dotted half tied notes
- Handle whole + 64th/dotted 32nd tied notes
- Print out table of (rc1, rc2, subdivision) bytes and values
- Handle tied 64th and dotted 32nd notes
- Handle whole + 32nd/dotted 16th tied notes
- Handle dotted 32nd notes
- Handle 64th notes
- Handle notes tied with 32nds (including dotted 16ths)
- Handle 2 bar, 3 bar and 4 bar notes
- Handle dotted 16ths
- Preserve 32nd note resolution grid from SXQ file to MIDI - looks like this is in a different file, perhaps xpj, xal or project settings
- Handle 32nd notes
- Handle tied notes - quarter tied 16th (5x16ths), quarter tied dotted 8th (7x16ths), half tied 16th (9x16ths), half tied 8th (10x16ths), half tied dotted 8th (11x16ths), half tied quarter tied 16th (13x16ths), half tied dotted quarter (14x16ths), half tied quarter tied dotted 8th (15x16ths)
- Handle dotted quarters, halfs, whole, dotted halfs, dotted whole
- Handle parallel notes with different pitches
- Ensure variable velocity is being converted
- Acceptance tests - examples of SXQ to MIDI file conversion
