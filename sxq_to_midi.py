import struct
import sys
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

###############################################################################
# Basic helpers
###############################################################################

def read_uint32_be(data, offset):
    value = struct.unpack(">I", data[offset:offset+4])[0]
    return value, offset + 4

def read_uint16_be(data, offset):
    value = struct.unpack(">H", data[offset:offset+2])[0]
    return value, offset + 2

def read_vlq(data, offset):
    """
    Read a MIDI-style VLQ from data[offset:].
    Return (value, new_offset).
    """
    value = 0
    while True:
        b = data[offset]
        offset += 1
        value = (value << 7) | (b & 0x7F)
        if (b & 0x80) == 0:
            break
    return value, offset

def write_vlq(value):
    """
    Encode an integer as a MIDI-style VLQ.
    """
    bytes_ = [value & 0x7F]
    value >>= 7
    while value > 0:
        bytes_.insert(0, 0x80 | (value & 0x7F))
        value >>= 7
    return bytes(bytes_)


###############################################################################
# Data classes
###############################################################################

@dataclass
class GaEvent:
    subtype: int
    payload: bytes


@dataclass
class Ga11Note:
    pitch: int
    velocity: int
    rhythmic_class: Tuple[int, int, int]
    event_delta: int


@dataclass
class SXQTrack:
    index: int
    name: Optional[str] = None
    ga_events: List[GaEvent] = field(default_factory=list)
    ga11_notes: List[Ga11Note] = field(default_factory=list)


@dataclass
class SXQSequenceMeta:
    name: Optional[str] = None
    tempo_bpm: Optional[float] = None
    mpq: Optional[int] = None
    time_signature: Optional[Tuple[int, int]] = None
    ticks_per_bar: Optional[int] = None
    sequence_ticks: Optional[int] = None
    bars: Optional[float] = None
    bar_count_from_ga00: Optional[int] = None


@dataclass
class SXQMetadata:
    ppqn: int
    format_type: int
    num_tracks: int
    sequence: SXQSequenceMeta
    tracks: List[SXQTrack]


###############################################################################
# Ga-10 / Ga-00 decoding
###############################################################################

def extract_sequence_ticks_from_ga10(ga_events: List[GaEvent],
                                     ppqn: int,
                                     ticks_per_bar: Optional[int]) -> Optional[int]:
    """
    Extract sequence length in ticks from Ga-10 metadata block(s).
    We scan only Ga-10 events and look for the largest 4-byte integer
    that satisfies:
        - > 0
        - < 10 million
        - divisible by ppqn
        - divisible by ticks_per_bar (if provided)
    """
    best = None

    for ge in ga_events:
        if ge.subtype != 0x10:
            continue

        payload = ge.payload

        for i in range(len(payload) - 3):
            val = int.from_bytes(payload[i:i+4], "big")

            if val <= 0:
                continue
            if val >= 10_000_000:
                continue
            if val % ppqn != 0:
                continue
            if ticks_per_bar and val % ticks_per_bar != 0:
                continue

            if best is None or val > best:
                best = val

    return best


def extract_bar_count_from_ga00(payload: bytes) -> Optional[int]:
    """
    Decode Ga-00 bar count from the first 4 bytes of the payload.

    From comparison of lastgood.sxq (8 bars) and lastgood-4bars.sxq (4 bars):

      lastgood-4bars:
        payload[0:4] = 00 04 00 01  -> high 16 bits = 0x0004 = 4 bars

      lastgood (8 bars):
        payload[0:4] = 00 08 00 01  -> high 16 bits = 0x0008 = 8 bars

    So:
      bar_count = (payload[0:4] >> 16)
    """
    if len(payload) < 4:
        return None

    raw_val = int.from_bytes(payload[0:4], "big")
    bar_count = (raw_val >> 16) & 0xFFFF

    if bar_count <= 0 or bar_count >= 1000:
        return None

    return bar_count

###############################################################################
# SXQ parsing
###############################################################################

def parse_sxq(sxq_bytes: bytes, verbose = None) -> SXQMetadata:
    """
    Parse SXQ (MIDI-container) file into structured metadata:
    - Header (format, num tracks, ppqn)
    - Sequence meta (tempo, TS, length in ticks/bars)
    - Tracks with Ga events and Ga-11 notes
    """
    offset = 0
    file_len = len(sxq_bytes)

    # Header
    if sxq_bytes[0:4] != b"MThd":
        raise ValueError("Not an SXQ/MIDI-style file: missing MThd")
    offset += 4

    header_len, offset = read_uint32_be(sxq_bytes, offset)
    if header_len != 6:
        # Still skip, but this is unusual; we assume well-formed SXQ.
        pass

    format_type, offset = read_uint16_be(sxq_bytes, offset)
    num_tracks, offset = read_uint16_be(sxq_bytes, offset)
    division, offset = read_uint16_be(sxq_bytes, offset)

    if division & 0x8000:
        raise ValueError("SMPTE division not supported for SXQ parsing.")
    ppqn = division

    seq_meta = SXQSequenceMeta()
    sxq_tracks: List[SXQTrack] = []
    track_index = 0

    while offset < file_len and len(sxq_tracks) < num_tracks:
        if sxq_bytes[offset:offset+4] != b"MTrk":
            break

        offset += 4
        track_len, offset = read_uint32_be(sxq_bytes, offset)
        track_end = offset + track_len

        track = SXQTrack(index=track_index)
        track_offset = offset

        while track_offset < track_end:
            event_delta, track_offset = read_vlq(sxq_bytes, track_offset)
            current_event_delta = event_delta
            if track_offset >= track_end:
                break

            status = sxq_bytes[track_offset]
            track_offset += 1

            if status == 0xFF:
                if track_offset >= track_end:
                    break
                meta_type = sxq_bytes[track_offset]
                track_offset += 1

                meta_len, track_offset = read_vlq(sxq_bytes, track_offset)
                meta_data_start = track_offset
                meta_data_end = meta_data_start + meta_len
                meta_data = sxq_bytes[meta_data_start:meta_data_end]
                track_offset = meta_data_end

                # Track name
                if meta_type == 0x03:
                    try:
                        name = meta_data.decode("utf-8", errors="replace")
                    except Exception:
                        name = None
                    track.name = name
                    if track_index == 0 and seq_meta.name is None:
                        seq_meta.name = name

                # Tempo
                elif meta_type == 0x51 and meta_len == 3:
                    mpq = int.from_bytes(meta_data, "big")
                    seq_meta.mpq = mpq
                    if mpq > 0:
                        seq_meta.tempo_bpm = 60_000_000 / mpq

                # Time signature
                elif meta_type == 0x58 and meta_len >= 2:
                    nn = meta_data[0]
                    dd_power = meta_data[1]
                    denominator = 2 ** dd_power
                    seq_meta.time_signature = (nn, denominator)
                    if denominator != 0:
                        # ticks_per_bar = nn * quarter_notes_per_bar * ppqn
                        # quarter_notes_per_bar = 4 / denominator
                        seq_meta.ticks_per_bar = int(nn * (ppqn * 4 / denominator))

                # Vendor-specific (Ga)
                elif meta_type == 0x7F:
                    if len(meta_data) >= 3 and meta_data[0:2] == b"Ga":
                        subtype = meta_data[2]
                        payload = meta_data[3:]
                        track.ga_events.append(GaEvent(subtype=subtype, payload=payload))

                        # Ga-00 in Track 0: bar count
                        if track_index == 0 and subtype == 0x00:
                            bar_count = extract_bar_count_from_ga00(payload)
                            if bar_count is not None:
                                seq_meta.bar_count_from_ga00 = bar_count

                        # Ga-11: note definitions
                        elif subtype == 0x11:
                            # Ga-11: note
                            # Mapping confirmed from multiple SXQs:
                            #  payload[1]  = pitch_byte
                            #  payload[2]  = velocity
                            #  payload[6]  = rhythmic_class byte 1 (0x40)
                            #  payload[7]  = rhythmic_class byte 2 (grid id)
                            #  payload[8]  = rhythmic_class byte 3 (subdivision)
                            if len(payload) >= 9:
                                pitch_byte = payload[1]
                                velocity = payload[2]
                                midi_note = pitch_byte
                                rhythmic_class = (payload[6], payload[7], payload[8])

                                note = Ga11Note(
                                    pitch=midi_note,
                                    velocity=velocity,
                                    rhythmic_class=rhythmic_class,
                                    event_delta=current_event_delta
                                )
                                track.ga11_notes.append(note)
                                if verbose : print(f"    [Ga11] pitch={midi_note}, vel={velocity}, "
                                      f"rhythmic_class={rhythmic_class}, payload_len={len(payload)}")

                        # other Ga subtypes: we just keep them raw for now.

            elif status in (0xF0, 0xF7):
                # SysEx: read length and skip payload
                sysex_len, track_offset2 = read_vlq(sxq_bytes, track_offset)
                track_offset = track_offset2 + sysex_len

            else:
                # MIDI channel event: skip data bytes
                high_nibble = status & 0xF0
                if high_nibble in (0xC0, 0xD0):  # Program Change / Channel Pressure
                    track_offset += 1
                else:
                    track_offset += 2

        if verbose : print(
            f"[Track {track_index}] done: name={track.name}, "
            f"Ga events={len(track.ga_events)}, Ga-11 notes={len(track.ga11_notes)}"
        )
        sxq_tracks.append(track)
        track_index += 1
        offset = track_end

    # --- Derive sequence length in ticks and bar count ---

    seq_ticks = None

    # 1) Prefer Ga-10 in Track 1 (sequence/program metadata track)
    if len(sxq_tracks) > 1 and seq_meta.ticks_per_bar:
        ga10_events = [ge for ge in sxq_tracks[1].ga_events if ge.subtype == 0x10]
        seq_ticks = extract_sequence_ticks_from_ga10(
            ga10_events,
            ppqn,
            seq_meta.ticks_per_bar,
        )

    # 2) Use Ga-00 bar count as backup or cross-check
    if seq_meta.bar_count_from_ga00 and seq_meta.ticks_per_bar:
        bars_from_ga00 = seq_meta.bar_count_from_ga00
        ticks_from_ga00 = bars_from_ga00 * seq_meta.ticks_per_bar

        if seq_ticks is None:
            seq_ticks = ticks_from_ga00
        else:
            # Optional: cross-check; you can tighten this if you want strict equality
            if abs(seq_ticks - ticks_from_ga00) > seq_meta.ticks_per_bar:
                # For now, keep Ga-10 as primary; you could log/print here.
                pass

    if seq_ticks is not None and seq_meta.ticks_per_bar:
        seq_meta.sequence_ticks = seq_ticks
        seq_meta.bars = seq_ticks / seq_meta.ticks_per_bar

    return SXQMetadata(
        ppqn=ppqn,
        format_type=format_type,
        num_tracks=num_tracks,
        sequence=seq_meta,
        tracks=sxq_tracks,
    )

FAMILY_DEFS_RC1_64 = {
    # 16th-based micro family
    # rc2 + 8*sub == 59
    # quarters(s) = (s + 4) / 16  [you can tweak if you refine this ladder]
    59: {
        "denominator": 16,
        "offset": 4,
    },

    # whole-note extension family
    # rc2 + 8*sub == 359
    # quarters(s) = (s + 3) / 8
    359: {
        "denominator": 8,
        "offset": 3,
    },

    # dotted-whole extension family
    # rc2 + 8*sub == 479
    # quarters(s) = (s + 4) / 8
    479: {
        "denominator": 8,
        "offset": 4,
    },
}

def note_length_from_ga11_formula(rc, ppqn):
    """
    Formula-based resolver for rc1=64 rhythmic classes.
    Returns ticks or None if the rc doesn't fit a known linear family.
    """
    rc1, rc2, subdivision = rc

    # Currently we only understand the rc1=64 'linear grid' mode.
    if rc1 != 64:
        return None

    family_const = rc2 + 8 * subdivision
    family = FAMILY_DEFS_RC1_64.get(family_const)
    if family is None:
        # Unknown family constant – fall back to table-based logic
        return None

    denom = family["denominator"]
    offset = family["offset"]

    # Duration in quarter notes:
    # quarters = (subdivision + offset) / denom
    # ticks = quarters * ppqn
    numerator = subdivision + offset
    ticks = (ppqn * numerator) // denom
    return ticks

def resolve_long_duration(rc, ppqn) -> None | int:
    """
    Handles rc2 == 127 (long-duration family):
    whole, dotted whole, 2 bars, 3 bars, 4 bars, etc.
    """
    rc1, rc2, subdivision = rc

    if rc1 != 64 or rc2 != 127:
        return None  # not in this family

    # Valid known subvalues: 14, 29, 44, 59, 74, 89, 104, 119, ...
    # Each +15 subdivision corresponds to +2 quarter notes.
    if subdivision < 14:
        return None  # out of range for this family

    delta = subdivision - 14
    if delta % 15 != 0:
        return None  # not on the expected grid; let table handle it

    steps = delta // 15          # number of +2-quarter increments from half
    quarter_units = 2 + steps * 2  # base half = 2 quarters

    return quarter_units * ppqn

def note_length_table(ppqn):
    return {
        (64, 3, 7):   (ppqn * 15) // 16,# dotted eighth tied dotted 32nd
        (64, 3, 22):  (ppqn * 47) // 16,# half tied dotted 8th tied dotted 32nd
        (64, 3, 37):  (ppqn * 79) // 16,# whole tied dotted 8th tied dotted 32nd
        (64, 7, 14):   (ppqn * 15) // 8,# dotted quarter tied dotted sixteenth
        (64, 7, 29):   (ppqn * 31) // 8,# dotted half tied dotted eighth tied 32nd
        (64, 7, 44):   (ppqn * 47) // 8,# whole tied dotted quarter tied dotted 16th
        (64, 7, 59):   (ppqn * 63) // 8,# dotted whole tied dotted quarter tied dotted 16th
        (64, 11, 6):  (ppqn * 13) // 16,# dotted eighth tied 64th
        (64, 11, 21): (ppqn * 45) // 16,# half tied dotted 8th tied 64th
        (64, 11, 36): (ppqn * 77) // 16,# whole tied dotted 8th tied 64th
        (64, 15, 13):  (ppqn * 7) // 4, # quarter tied dotted eighth (7x16ths)
        (64, 15, 28):  (ppqn * 15) // 4,# half tied quarter tied dotted eighth
        # expecting (64, 15, 58)
        (64, 19, 5):  (ppqn * 11) // 16,# eighth tied dotted 32nd
        (64, 19, 20): (ppqn * 43) // 16,# half tied 8th tied dotted 32nd
        (64, 19, 35): (ppqn * 75) // 16,# whole tied 8th tied dotted 32nd
        (64, 23, 12):  (ppqn * 13) // 8,# dotted quarter tied 32nd
        (64, 23, 27):  (ppqn * 29) // 8,# dotted half tied 8th tied 32nd
        (64, 23, 42):  (ppqn * 45) // 8,# whole tied dotted quarter tied 32nd
        (64, 23, 57):  (ppqn * 61) // 8,# dotted whole tied dotted quarter tied 32nd
        (64, 27, 4):   (ppqn * 9) // 16,# eighth tied 64th
        (64, 27, 19): (ppqn * 41) // 16,# half tied 8th tied 64th
        (64, 27, 34): (ppqn * 73) // 16,# whole tied 8th tied 64th
        (64, 31, 11):  (ppqn * 3) // 2, # dotted quarter
        (64, 31, 26):  (ppqn * 7) // 2, # half tied dotted quarter
        (64, 35, 3):   (ppqn * 7) // 16,# dotted 16th tied 64th
        (64, 35, 18): (ppqn * 39) // 16,# half tied 16th tied dotted 32nd
        (64, 35, 33): (ppqn * 71) // 16,# whole tied 16th tied dotted 32nd
        # expecting (64, 35, 23)
        (64, 39, 10):  (ppqn * 11) // 8,# quarter tied dotted sixteenth
        (64, 39, 25):  (ppqn * 27) // 8,# dotted half tied dotted sixteenth
        (64, 39, 40):  (ppqn * 43) // 8,# whole tied quarter tied dotted 16th
        (64, 39, 55):  (ppqn * 59) // 8,# dotted whole tied quarter tied dotted 16th
        (64, 43, 2):   (ppqn * 5) // 16,# 16th tied 64th
        (64, 43, 17): (ppqn * 37) // 16,# half tied 16th tied 64th
        (64, 43, 32): (ppqn * 69) // 16,# whole tied 16th tied 64th
        # expecting (64, 46, 23)
        (64, 47, 9):   (ppqn * 5) // 4, # quarter tied sixteenth (5x16ths)
        (64, 47, 24):  (ppqn * 13) // 4,# half tied quarter tied sixteenth
        # (64, 49, 12):  (ppqn * 3) // 4, # what is a 49, 12 (31, 0C)?  AI thinks it a dotted quarter tied 32nd (but this would be the same as 23, 12)...
        (64, 51, 1):  (ppqn * 3) // 16, # dotted 32nd
        (64, 51, 16): (ppqn * 35) // 16,# half tied dotted 32nd
        (64, 51, 31): (ppqn * 67) // 16,# whole tied dotted 32nd
        (64, 51, 46): (ppqn * 99) // 16,# whole tied half tied dotted 32nd
        (64, 55, 8):  (ppqn * 9) // 8,  # quarter tied 32nd
        (64, 55, 23): (ppqn * 25) // 8, # dotted half tied 32nd
        (64, 55, 38): (ppqn * 41) // 8, # whole tied quarter tied 32nd
        (64, 55, 53): (ppqn * 57) // 8, # dotted whole tied quarter tied 32nd
        (64, 59, 0):   ppqn // 16,      # 64th
        (64, 59, 15): (ppqn * 33) // 16,# half tied 64th
        (64, 59, 30): (ppqn * 65) // 16,# whole tied 64th
        (64, 59, 45): (ppqn * 97) // 16,# whole tied half tied 64th
        (64, 63, 7):   ppqn,            # quarter
        (64, 63, 22):  ppqn * 3,        # dotted half
        (64, 67, 14): (ppqn * 31) // 16,# dotted quarter tied dotted 16th tied 64th
        (64, 67, 29): (ppqn * 63) // 16,# dotted half tied dotted 8th tied dotted 32nd
        (64, 67, 44): (ppqn * 95) // 16,# whole tied dotted quarter tied 16th tied dotted 32nd
        # expecting (64, 70, 23)
        (64, 71, 6):  (ppqn * 7) // 8,  # eighth tied dotted sixteenth
        # expecting (64, 71, 7)
        (64, 71, 21): (ppqn * 23) // 8, # half tied dotted eighth tied 32nd
        (64, 71, 36): (ppqn * 39) // 8, # whole tied dotted eighth tied 32nd
        (64, 71, 51): (ppqn * 55) // 8, # dotted whole tied dotted eighth tied 32nd
        # expecting (64, 73, 10)
        (64, 75, 13): (ppqn * 29) // 16,# dotted quarter tied 16th tied 64th
        (64, 75, 28): (ppqn * 61) // 16,# dotted half tied dotted 8th tied 64th
        (64, 75, 43): (ppqn * 93) // 16,# whole tied dotted quarter tied 16th tied 64th
        (64, 79, 5):  (ppqn * 3) // 4,  # dotted eighth
        (64, 79, 20): (ppqn * 11) // 4, # half tied dotted eighth (11x16ths)
        (64, 83, 12): (ppqn * 27) // 16,# dotted quarter tied dotted 32nd
        (64, 83, 27): (ppqn * 59) // 16,# dotted half tied 8th tied dotted 32nd
        (64, 83, 42): (ppqn * 91) // 16,# whole tied dotted quarter tied dotted 32nd
        # expecting (64, 84, 11)
        (64, 87, 4):  (ppqn * 5) // 8,  # eighth tied 32nd
        (64, 87, 19): (ppqn * 21) // 8, # half tied eighth tied 32nd
        (64, 87, 34): (ppqn * 37) // 8, # whole tied eighth tied 32nd
        (64, 87, 49): (ppqn * 53) // 8, # dotted whole tied eighth tied 32nd
        (64, 91, 11): (ppqn * 25) // 16,# dotted quarter tied 64th
        (64, 91, 26): (ppqn * 57) // 16,# dotted half tied 8th tied 64th
        (64, 91, 41): (ppqn * 89) // 16,# whole tied dotted quarter tied 64th
        (64, 95, 3):   ppqn // 2,       # eighth
        (64, 95, 18):  (ppqn * 5) // 2, # half tied eighth (10x16ths)
        (64, 99, 10): (ppqn * 23) // 16,# quarter tied 16th tied dotted 32nd
        (64, 99, 25): (ppqn * 55) // 16,# dotted half tied 16th tied dotted 32nd
        (64, 99, 40): (ppqn * 87) // 16,# whole tied quarter tied 16th tied dotted 32nd
        # expecting (64, 100, 10)
        (64, 103, 2):  (ppqn * 3) // 8, # dotted sixteenth
        (64, 103, 17): (ppqn * 19) // 8,# half tied dotted sixteenth
        (64, 103, 32): (ppqn * 35) // 8,# whole tied dotted 16th
        (64, 103, 47): (ppqn * 51) // 8,# dotted whole tied dotted 16th
        (64, 107, 9): (ppqn * 21) // 16,# quarter tied 16th tied 64th
        (64, 107, 24):(ppqn * 53) // 16,# dotted half tied 16th tied 64th
        (64, 107, 39):(ppqn * 85) // 16,# whole tied quarter tied 16th tied 64th
        (64, 111, 1):  ppqn // 4,       # sixteenth
        (64, 111, 16): (ppqn * 9) // 4, # half tied sixteenth (9x16ths)
        (64, 115, 8): (ppqn * 19) // 16,# quarter tied dotted 32nd
        (64, 115, 23):(ppqn * 51) // 16,# dotted half tied dotted 32nd
        (64, 115, 38):(ppqn * 83) // 16,# whole tied quarter tied dotted 32nd
        (64, 119, 0):  ppqn // 8,       # 32nd
        (64, 119, 15): (ppqn * 17) // 8,# half tied 32nd
        (64, 119, 30): (ppqn * 33) // 8,# whole tied 32nd
        (64, 119, 45): (ppqn * 49) // 8,# dotted whole tied 32nd
        (64, 123, 7): (ppqn * 17) // 16,# quarter tied 64th
        (64, 123, 22):(ppqn * 49) // 16,# dotted half tied 64th
        (64, 123, 37):(ppqn * 81) // 16,# whole tied quarter tied 64th
        # handled in resolve_long_duration
        # (64, 127, 14): ppqn * 2,        # half
        # (64, 127, 29): ppqn * 4,        # whole
        # (64, 127, 44): ppqn * 6,        # dotted whole
        # (64, 127, 59): ppqn * 8,        # 2-bar note (8 quarters)
        # (64, 127, 89): ppqn * 12,       # 3 bars
        # (64, 127, 119): ppqn * 16,      # 4 bars
    }

def note_length_from_ga11_table(rc, ppqn) -> None | int:
    """
    Resolve note length using the full 3-byte rhythmic class:
        (rc1, rc2, rc3)
    """
    length = resolve_long_duration(rc, ppqn)
    if length is not None:
        return length

    table = note_length_table(ppqn)
    if rc in table:
        return table[rc]

    return None

def note_length_from_ga11(rc, ppqn, verbose = None) -> int:
    """
    Combined resolver:
    1. Try existing lookup-table resolver.
    2. If that fails, try the formula-based resolver.
    """
    # 1. Your existing table-based resolver
    length = note_length_from_ga11_table(rc, ppqn)  # whatever your current function is called
    if length is not None:
        # if verbose: print(f"  + note length of {length} retrieved from table for rc {rc}")
        return length

    # 2. Formula-based fallback
    length = note_length_from_ga11_formula(rc, ppqn)
    if length is not None:
        if verbose: print(f"  * note length of {length} calculated from formula for rc {rc}")
        return length

    # 3. Final crude fallback (your current default behavior, if any)
    print(f"  !! Unrecognized note length: {rc}, falling back to a 32nd note length")
    return ppqn // 8     # fallback to a 32nd

###############################################################################
# Build MIDI from parsed SXQ
###############################################################################

def build_midi_from_sxq_meta(meta: SXQMetadata, verbose = None) -> bytes:
    """
    Build a Standard MIDI File (Format 1) from parsed SXQ metadata.
    - Track 0: master tempo + time signature + sequence name
    - One track per SXQ track, containing Ga-11 → MIDI notes
    """
    ppqn = meta.ppqn

    # Tempo
    if meta.sequence.mpq is not None:
        mpq = meta.sequence.mpq
    else:
        mpq = int(60_000_000 / 120)  # default 120 BPM

    midi_tracks: List[bytearray] = []

    # Track 0: Conductor
    t0 = bytearray()

    # Sequence / track name
    t0 += write_vlq(0)
    t0 += bytes([0xFF, 0x03])
    if meta.sequence.name:
        name_bytes = meta.sequence.name.encode("ascii", errors="replace")
    else:
        name_bytes = b"SXQ Sequence"
    t0 += write_vlq(len(name_bytes))
    t0 += name_bytes

    # Tempo
    t0 += write_vlq(0)
    t0 += bytes([0xFF, 0x51, 0x03])
    t0 += mpq.to_bytes(3, "big")

    # Time signature
    if meta.sequence.time_signature:
        nn, dd = meta.sequence.time_signature
        dd_power = 0
        while (1 << dd_power) < dd and dd_power < 7:
            dd_power += 1
        t0 += write_vlq(0)
        t0 += bytes([0xFF, 0x58, 0x04, nn, dd_power, 0x18, 0x08])
    else:
        # Default 4/4
        t0 += write_vlq(0)
        t0 += bytes([0xFF, 0x58, 0x04, 0x04, 0x02, 0x18, 0x08])

    # End of Track 0
    t0 += write_vlq(0)
    t0 += bytes([0xFF, 0x2F, 0x00])
    midi_tracks.append(t0)

    # One MIDI track per SXQ track (Ga-11 → notes)
    for tr in meta.tracks:
        track_bytes = bytearray()

        # Track name
        track_bytes += write_vlq(0)
        track_bytes += bytes([0xFF, 0x03])
        if tr.name:
            tn_bytes = tr.name.encode("ascii", errors="replace")
        else:
            tn_bytes = f"SXQ Track {tr.index}".encode("ascii", errors="replace")
        track_bytes += write_vlq(len(tn_bytes))
        track_bytes += tn_bytes

        if not tr.ga11_notes:
            # No Ga-11 → no notes, just end-of-track
            track_bytes += write_vlq(0)
            track_bytes += bytes([0xFF, 0x2F, 0x00])
            midi_tracks.append(track_bytes)
            continue

        events = []  # (tick, is_on, pitch, velocity)

        #
        # NEW: Each Ga-11 event is ONE NOTE, not a lane.
        #
        abs_time = 0

        for note in tr.ga11_notes:
            # event_delta is the VLQ before the FF 7F meta
            # We must accumulate it to get absolute time.
            # parse_sxq() already read event_delta, but we need to
            # re-accumulate it here.
            abs_time += note.event_delta

            start = abs_time
            note_len = note_length_from_ga11(note.rhythmic_class, ppqn, verbose)
            end = start + note_len

            if verbose: print(
                f"[Ga11 note] pitch={note.pitch}, vel={note.velocity}, "
                f"start={start}, len={note_len}, rc={note.rhythmic_class}"
            )

            events.append((start, True, note.pitch, note.velocity))
            events.append((end, False, note.pitch, 0))

        # Sort events: time, then note-off before note-on at same tick
        events.sort(key=lambda e: (e[0], 0 if not e[1] else 1))

        last_tick = 0
        running_status = None

        for tick, is_on, pitch, vel in events:
            dt = tick - last_tick
            last_tick = tick

            track_bytes += write_vlq(dt)
            status = 0x90 if is_on else 0x80  # channel 0

            if status != running_status:
                track_bytes.append(status)
                running_status = status

            track_bytes.append(pitch & 0x7F)
            track_bytes.append(vel & 0x7F)

        # End of this track
        track_bytes += write_vlq(0)
        track_bytes += bytes([0xFF, 0x2F, 0x00])

        midi_tracks.append(track_bytes)

    # Build SMF (Format 1)
    midi_bytes = bytearray()
    midi_bytes += b"MThd"
    midi_bytes += struct.pack(">I", 6)
    midi_bytes += struct.pack(">H", 1)  # format 1
    midi_bytes += struct.pack(">H", len(midi_tracks))
    midi_bytes += struct.pack(">H", ppqn)

    for trk in midi_tracks:
        midi_bytes += b"MTrk"
        midi_bytes += struct.pack(">I", len(trk))
        midi_bytes += trk

    return bytes(midi_bytes)


###############################################################################
# Top-level convenience
###############################################################################

def sxq_bytes_to_midi_bytes(sxq_bytes: bytes, verbose = None) -> bytes:
    meta = parse_sxq(sxq_bytes, verbose)
    return build_midi_from_sxq_meta(meta, verbose)

def sxq_to_midi_full(sxq_path: str, midi_path: str):
    with open(sxq_path, "rb") as f:
        sxq_bytes = f.read()

    meta = parse_sxq(sxq_bytes, verbose = True)

    note_lengths = note_length_table(960)
    sorted_note_lengths = sorted(note_lengths.items(), key=lambda x: x[1])
    print("Note length table @960 PPQN:")
    print("rc             Pulses  Subdivision_diff  Alternative  Alternative_mismatch")
    last_subdivision = -1
    min_pulses_for_subdivsion = 0
    subdivison_pulse_diff = 0
    for (rc1, rc2, subdivision), val in sorted_note_lengths:
        # subdivision are 120 pulses apart for 64th notes
        # except every 7-ish subdivisions: 7 (before 8), 15 (before  16), 22, 29, 36(?), 43(?)
        # which are 180 pulses apart!
        alternative = (subdivision*120)+(60 if rc2 < 60 else 120)
        if subdivision != last_subdivision:
            subdivison_pulse_diff = val - min_pulses_for_subdivsion
            min_pulses_for_subdivsion = val
        last_subdivision = subdivision
        print(f"({rc1:2}, {rc2:3}, {subdivision:2}):  {val:4}        {'' if subdivision == 0 else subdivison_pulse_diff:4}           {alternative:4}           {'*' if val != alternative else ''}")
    print("")

    print("SXQ parsed:")
    print(f"  Format: {meta.format_type}")
    print(f"  Tracks: {meta.num_tracks}")
    print(f"  PPQN:   {meta.ppqn}")
    print("  Sequence:")
    print(f"    Name:   {meta.sequence.name}")
    print(f"    Tempo:  {meta.sequence.tempo_bpm} BPM (mpq={meta.sequence.mpq})")
    print(f"    TimeSig:{meta.sequence.time_signature}")
    print(f"    Ticks/bar: {meta.sequence.ticks_per_bar}")
    print(f"    Bar count (Ga-00): {meta.sequence.bar_count_from_ga00}")
    print(f"    Seq ticks (Ga-10/Ga-00): {meta.sequence.sequence_ticks}")
    print(f"    Bars (computed):         {meta.sequence.bars}")

    for tr in meta.tracks:
        print(f"  Track {tr.index}: name={tr.name}, Ga-11 notes={len(tr.ga11_notes)}, Ga events={len(tr.ga_events)}")

    midi_bytes = build_midi_from_sxq_meta(meta, verbose = True)

    with open(midi_path, "wb") as f:
        f.write(midi_bytes)

    print(f"\nWrote MIDI: {midi_path}")

def main():
    sxq_to_midi_full(sys.argv[1], sys.argv[2])

if __name__ == '__main__':
    main()