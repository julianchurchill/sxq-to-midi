import unittest
from parameterized import parameterized
from sxq_to_midi import sxq_bytes_to_midi_bytes

class AcceptanceTests(unittest.TestCase):

    def print_midi_and_midi_diff(self, midi1_bytes, midi2_bytes, index):
        hex_width = 16
        clampedStartMIDI1 = max(index - 10, 0)
        clampedEndMIDI1 = min(index + 10, len(midi1_bytes))
        clampedStartMIDI2 = max(index - 10, 0)
        clampedEndMIDI2 = min(index + 10, len(midi2_bytes))
        midi1_bytes_selection = midi1_bytes[clampedStartMIDI1:clampedEndMIDI1]
        midi2_bytes_selection = midi2_bytes[clampedStartMIDI2:clampedEndMIDI2]
        midi1_bytes_printable = " ".join(f"{x:02x}" for x in midi1_bytes_selection).ljust(hex_width*3-1)
        midi2_bytes_printable = " ".join(f"{x:02x}" for x in midi2_bytes_selection).ljust(hex_width*3-1)
        print(f"  Raw MIDI1: {midi1_bytes_selection}")
        print(f"  Raw MIDI2: {midi2_bytes_selection}")
        print(f"  Hex MIDI1: {midi1_bytes_printable}")
        print(f"  Hex MIDI2: {midi2_bytes_printable}")
        print(f"             " + "   " * (index - clampedStartMIDI1) + "^^")

    @parameterized.expand([
        ('2BarNotes4bars120bpm127velocity-ASharp'),
        ('3BarNotes4bars120bpm127velocity-ASharp'),
        ('4BarNotes4bars120bpm127velocity-ASharp'),
        ('8thAnd16thNotesAlternatingOn8thNote1bar120bpm127velocity-ASharp'),
        ('8thnotes1bar120bpm127velocity-A3AndASharp3'),
        ('8thnotes1bar120bpm127velocity-ASharp'),
        ('8thnotes4bars120bpm127velocity-ASharp'),
        ('8thnotes8bars120bpm127velocity-ASharp'),
        ('8thTied32ndnotes1bar120bpm127velocity-ASharp'),
        ('8thTiedDotted16thnotes1bar120bpm127velocity-ASharp'),
        ('16thnotes4bars120bpm101velocity-ASharp'),
        ('16thnotes4bars120bpm127velocity-A3'),
        ('16thnotes4bars120bpm127velocity-ASharp'),
        ('16thnotes4bars120bpm127velocity-D5'),
        ('16thnotes4bars120bpmVaryingVelocity-ASharp'),
        ('32ndnotes1bar120bpm127velocity-ASharp-32ndGrid'),
        ('64thnotes1bar120bpm127velocity-ASharp'),
        ('dotted8thNotes1bar120bpm127velocity-ASharp'),
        ('dotted16thnotes1bar120bpm127velocity-ASharp'),
        ('dotted32ndnotes1bar120bpm127velocity-ASharp'),
        ('dottedHalfNotes4bars120bpm127velocity-ASharp'),
        ('dottedHalfTied8thTied32ndNotes4bars120bpm127velocity-ASharp'),
        ('dottedHalfTied32ndNotes4bars120bpm127velocity-ASharp'),
        ('dottedHalfTiedDotted8thTied32ndNotes4bars120bpm127velocity-ASharp'),
        ('dottedHalfTiedDotted16thNotes4bars120bpm127velocity-ASharp'),
        ('dottedQuarterNotes1bar120bpm127velocity-ASharp'),
        ('dottedQuarterNotes4bars120bpm127velocity-ASharp'),
        ('dottedQuarterTied32ndNotes1bar120bpm127velocity-ASharp'),
        ('dottedQuarterTiedDotted16thNotes1bar120bpm127velocity-ASharp'),
        ('dottedWholeNotes4bars120bpm127velocity-ASharp'),
        ('halfNotes4bars120bpm127velocity-ASharp'),
        ('halfTied8thNotes4bars120bpm127velocity-ASharp'),
        ('halfTied8thTied32ndNotes4bars120bpm127velocity-ASharp'),
        ('halfTied16thNotes4bars120bpm127velocity-ASharp'),
        ('halfTied32ndNotes4bars120bpm127velocity-ASharp'),
        ('halfTiedDotted8thNotes4bars120bpm127velocity-ASharp'),
        ('halfTiedDotted8thTied32ndNotes4bars120bpm127velocity-ASharp'),
        ('halfTiedDotted16thNotes4bars120bpm127velocity-ASharp'),
        ('halfTiedDottedQuarterNotes4bars120bpm127velocity-ASharp'),
        ('halfTiedQuarterTied16thNotes4bars120bpm127velocity-ASharp'),
        ('halfTiedQuarterTiedDotted8thNotes4bars120bpm127velocity-ASharp'),
        ('quarterNotes1bar120bpm127velocity-ASharp'),
        ('quarterNotes4bars120bpm127velocity-ASharp'),
        ('quarterTied16thNotes1bar120bpm127velocity-ASharp'),
        ('quarterTied32ndNotes1bar120bpm127velocity-ASharp'),
        ('quarterTiedDotted8thNotes1bar120bpm127velocity-ASharp'),
        ('quarterTiedDotted16thNotes1bar120bpm127velocity-ASharp'),
        ('wholeNotes4bars120bpm127velocity-ASharp'),
        ('wholeTied8thTied32ndNotes4bars120bpm127velocity-ASharp'),
        ('wholeTied32ndNotes4bars120bpm127velocity-ASharp'),
        ('wholeTiedDotted16thNotes4bars120bpm127velocity-ASharp')
    ])
    def test_sxq_converts_to_midi(self, filename):
        sxq_filename = f'test-sxq-files/{filename}.sxq'
        midi_filename = f'test-midi-files/{filename}.mid'
        with open(sxq_filename, "rb") as sxq_file, open(midi_filename, "rb") as expected_midi_file:
            sxq_bytes = sxq_file.read()
            expected_midi_bytes = expected_midi_file.read()
            converted_midi_bytes = sxq_bytes_to_midi_bytes(sxq_bytes, verbose=False)
            maxLength = max(len(sxq_bytes), len(expected_midi_bytes))
            for index in range(maxLength):
                b1 = expected_midi_bytes[index] if index < len(expected_midi_bytes) else None
                b2 = converted_midi_bytes[index] if index < len(converted_midi_bytes) else None
                if b1 != b2:
                    print(f"Expected MIDI file '{midi_filename}' and converted SXQ bytes from '{sxq_filename}' first differ at byte {index}")
                    self.print_midi_and_midi_diff(expected_midi_bytes, converted_midi_bytes, index)
                    print("> Rerunning conversion with verbose logging:")
                    sxq_bytes_to_midi_bytes(sxq_bytes, verbose=True)
                    self.fail('Expected MIDI file and converted SXQ bytes differ')

if __name__ == '__main__':
    unittest.main()