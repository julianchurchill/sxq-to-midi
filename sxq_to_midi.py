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
class Ga11Lane:
    pitch: int
    velocity: int
    delta_ticks: int
    rhythmic_class: Tuple[int, int]


@dataclass
class SXQTrack:
    index: int
    name: Optional[str] = None
    ga_events: List[GaEvent] = field(default_factory=list)
    ga11_lanes: List[Ga11Lane] = field(default_factory=list)


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

def lane_note_length_ticks_from_spacing(lane, ppqn, ticks_per_bar):
    delta = lane.delta_ticks
    if delta <= 0:
        return ticks_per_bar // 16, None

    # Compute steps per bar
    steps_per_bar = ticks_per_bar / delta

    # Candidate grids
    grids = [1, 2, 3, 4, 6, 8, 12, 16, 24, 32]

    # Snap to nearest grid
    best = min(grids, key=lambda g: abs(steps_per_bar - g))

    # Compute note length
    note_len = ticks_per_bar // best

    # Prevent overlap
    note_len = min(note_len, delta)

    return note_len, steps_per_bar

def is_musical_lane(lane, ticks_per_bar):
    # Must have positive spacing
    if lane.delta_ticks <= 0:
        return False

    # Must be shorter than a bar
    if lane.delta_ticks >= ticks_per_bar:
        return False

    # Must divide the bar evenly (quarters, 8ths, 16ths, triplets, etc.)
    if ticks_per_bar % lane.delta_ticks != 0:
        return False

    # Must have a real velocity
    if lane.velocity <= 0:
        return False

    # Must have a real pitch (after subtracting 12)
    if lane.pitch < 0:
        return False

    return True

def log_lane_rhythm_info(lane: Ga11Lane,
                         ticks_per_bar: int,
                         note_len: int,
                         steps_per_bar: float):
    print(
        f"[Ga11] pitch={lane.pitch:3d}  vel={lane.velocity:3d}  "
        f"delta={lane.delta_ticks:4d}  "
        f"rhythmic_class={lane.rhythmic_class}  "
        f"steps_per_bar={steps_per_bar:5.2f}  "
        f"note_len={note_len:4d}"
    )

###############################################################################
# SXQ parsing
###############################################################################

def parse_sxq(sxq_bytes: bytes) -> SXQMetadata:
    """
    Parse SXQ (MIDI-container) file into structured metadata:
    - Header (format, num tracks, ppqn)
    - Sequence meta (tempo, TS, length in ticks/bars)
    - Tracks with Ga events and Ga-11 lanes
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

                        # Ga-11: lane definitions
                        elif subtype == 0x11:
                            # Known mapping from your experiments:
                            #  payload[1] = pitch_byte
                            #  payload[2] = velocity
                            #  payload[6:8] = rhythmic_class
                            if len(payload) >= 8:
                                pitch_byte = payload[1]
                                velocity = payload[2]
                                midi_note = pitch_byte - 12
                                rhythmic_class = (payload[6], payload[7])

                                # delta_ticks is stored in the last 4 bytes of the payload
                                delta_ticks = int.from_bytes(payload[-4:], "big")

                                lane = Ga11Lane(
                                    pitch=midi_note,
                                    velocity=velocity,
                                    delta_ticks=delta_ticks,
                                    rhythmic_class=rhythmic_class,
                                )
                                track.ga11_lanes.append(lane)
                                print(f"    [Ga11] pitch={midi_note}, vel={velocity}, "
                                      f"delta={delta_ticks}, rhythmic_class={rhythmic_class}")


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


###############################################################################
# Build MIDI from parsed SXQ
###############################################################################

def build_midi_from_sxq_meta(meta: SXQMetadata) -> bytes:
    """
    Build a Standard MIDI File (Format 1) from parsed SXQ metadata.
    - Track 0: master tempo + time signature + sequence name
    - One track per SXQ track, containing Ga-11 → MIDI notes
    """
    ppqn = meta.ppqn

    # Determine sequence length in ticks
    if meta.sequence.sequence_ticks is not None:
        seq_len_ticks = meta.sequence.sequence_ticks
    else:
        # Fallback: if we somehow don't have sequence_ticks, assume 4 bars
        ticks_per_bar = meta.sequence.ticks_per_bar or (4 * ppqn)
        seq_len_ticks = 4 * ticks_per_bar

    ticks_per_bar = meta.sequence.ticks_per_bar or (4 * ppqn)

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

        if not tr.ga11_lanes:
            # No Ga-11 → no notes, just end-of-track
            track_bytes += write_vlq(0)
            track_bytes += bytes([0xFF, 0x2F, 0x00])
            midi_tracks.append(track_bytes)
            continue

        events = []  # (tick, is_on, pitch, velocity)

        for lane in tr.ga11_lanes:
            # Skip non-musical Ga-11 lanes
            if not is_musical_lane(lane, ticks_per_bar):
                continue

            pitch = lane.pitch
            vel = lane.velocity
            delta_ticks = lane.delta_ticks
            if delta_ticks <= 0:
                continue

            t = 0

            note_len, steps_per_bar = lane_note_length_ticks_from_spacing(
                lane,
                ppqn=ppqn,
                ticks_per_bar=ticks_per_bar,
            )

            log_lane_rhythm_info(
                lane,
                ticks_per_bar=ticks_per_bar,
                note_len=note_len,
                steps_per_bar=steps_per_bar if steps_per_bar else 0.0,
            )

            while t < seq_len_ticks:
                events.append((t, True, pitch, vel))
                off_tick = t + note_len
                if off_tick <= seq_len_ticks:
                    events.append((off_tick, False, pitch, 0))
                t += delta_ticks

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

def sxq_to_midi_full(sxq_path: str, midi_path: str):
    with open(sxq_path, "rb") as f:
        sxq_bytes = f.read()

    meta = parse_sxq(sxq_bytes)

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
        print(f"  Track {tr.index}: name={tr.name}, Ga-11 lanes={len(tr.ga11_lanes)}, Ga events={len(tr.ga_events)}")

    midi_bytes = build_midi_from_sxq_meta(meta)

    with open(midi_path, "wb") as f:
        f.write(midi_bytes)

    print(f"\nWrote MIDI: {midi_path}")

sxq_to_midi_full(sys.argv[1], sys.argv[2])