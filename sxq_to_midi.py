import struct
import sys
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any

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


@dataclass
class SXQMetadata:
    ppqn: int
    format_type: int
    num_tracks: int
    sequence: SXQSequenceMeta
    tracks: List[SXQTrack]


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

    # --- Header (MThd) ---
    if sxq_bytes[0:4] != b"MThd":
        raise ValueError("Not an SXQ/MIDI-style file: missing MThd")
    offset += 4

    header_len, offset = read_uint32_be(sxq_bytes, offset)
    if header_len != 6:
        # Still skip, but this is unusual
        pass

    format_type, offset = read_uint16_be(sxq_bytes, offset)
    num_tracks, offset = read_uint16_be(sxq_bytes, offset)
    division, offset = read_uint16_be(sxq_bytes, offset)

    if division & 0x8000:
        raise ValueError("SMPTE division not supported for SXQ parsing.")
    ppqn = division

    # Sequence-level metadata
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

        # Parse events within this track
        while track_offset < track_end:
            event_delta, track_offset = read_vlq(sxq_bytes, track_offset)
            if track_offset >= track_end:
                break

            status = sxq_bytes[track_offset]
            track_offset += 1

            if status == 0xFF:
                # Meta event
                if track_offset >= track_end:
                    break
                meta_type = sxq_bytes[track_offset]
                track_offset += 1

                meta_len, track_offset2 = read_vlq(sxq_bytes, track_offset)
                meta_data_start = track_offset2
                meta_data_end = meta_data_start + meta_len
                meta_data = sxq_bytes[meta_data_start:meta_data_end]
                track_offset = meta_data_end

                # --- Track name ---
                if meta_type == 0x03:  # Track Name
                    try:
                        name = meta_data.decode("utf-8", errors="replace")
                    except Exception:
                        name = None
                    track.name = name
                    if track_index == 0:
                        # Often sequence name lives here
                        if seq_meta.name is None:
                            seq_meta.name = name

                # --- Tempo ---
                elif meta_type == 0x51 and meta_len == 3:
                    mpq = int.from_bytes(meta_data, "big")
                    seq_meta.mpq = mpq
                    if mpq > 0:
                        seq_meta.tempo_bpm = 60_000_000 / mpq

                # --- Time Signature ---
                elif meta_type == 0x58 and meta_len >= 2:
                    nn = meta_data[0]  # numerator
                    dd = meta_data[1]  # denominator as power of 2
                    denominator = 2 ** dd
                    seq_meta.time_signature = (nn, denominator)
                    if seq_meta.time_signature and ppqn:
                        # ticks per bar = numerator * quarter-notes-per-bar * ppqn
                        # assuming 4/4 mapping: 4 quarter notes per bar
                        seq_meta.ticks_per_bar = nn * (ppqn * 4 // denominator)

                # --- Vendor-specific (Akai "Ga") ---
                elif meta_type == 0x7F:
                    # Vendor event. We expect payload: 47 61 <subtype> ...
                    if len(meta_data) >= 3 and meta_data[0:2] == b"Ga":
                        subtype = meta_data[2]
                        payload = meta_data[3:]
                        track.ga_events.append(GaEvent(subtype=subtype, payload=payload))

                        if subtype == 0x11:
                            # Ga-11 lane definition
                            # Known mapping from your experiments:
                            #   payload[0] = flag (0x02)
                            #   payload[1] = pitch_byte
                            #   payload[2] = velocity
                            #   payload[6:8] = rhythmic class (2 bytes)
                            if len(payload) >= 8:
                                pitch_byte = payload[1]
                                velocity = payload[2]
                                midi_note = pitch_byte - 12
                                rhythmic_class = (payload[6], payload[7])

                                # After this vendor event, there is a delta-time VLQ
                                # used by SXQ as spacing between hits.
                                delta_ticks, track_offset = read_vlq(sxq_bytes, track_offset)

                                lane = Ga11Lane(
                                    pitch=midi_note,
                                    velocity=velocity,
                                    delta_ticks=delta_ticks,
                                    rhythmic_class=rhythmic_class,
                                )
                                track.ga11_lanes.append(lane)

                        else:
                            # Other Ga subtypes (Ga-10, Ga-13, Ga-15, etc.)
                            # For now, we just store the raw payload.
                            pass

            elif status in (0xF0, 0xF7):
                # SysEx: read length and skip payload
                sysex_len, track_offset2 = read_vlq(sxq_bytes, track_offset)
                track_offset = track_offset2 + sysex_len

            else:
                # MIDI channel event; we just skip the data bytes.
                high_nibble = status & 0xF0
                if high_nibble in (0xC0, 0xD0):  # Program change / Channel pressure
                    track_offset += 1
                else:
                    track_offset += 2

        sxq_tracks.append(track)
        track_index += 1
        offset = track_end

    # --- Derive sequence length in ticks (from Ga-10 / Ga-15 if possible) ---

    # Commonly, sequence-level Ga events live in track 0:
    seq_ticks = None
    if sxq_tracks:
        t0 = sxq_tracks[0]
        for ge in t0.ga_events:
            # This is heuristic: in your files, some Ga-10 / Ga-15 payloads
            # contain a 4-byte big-endian sequence length in ticks.
            # We'll scan each payload for a plausible tick count.
            if len(ge.payload) >= 4:
                # Try each 4-byte window as candidate
                for i in range(len(ge.payload) - 3):
                    candidate = int.from_bytes(ge.payload[i:i+4], "big")
                    # Heuristics: must be non-zero, divisible by ppqn, and not insane
                    if candidate > 0 and candidate % ppqn == 0 and candidate < 10_000_000:
                        # Optional: prefer multiples of ticks_per_bar if known
                        if seq_meta.ticks_per_bar and candidate % seq_meta.ticks_per_bar == 0:
                            seq_ticks = candidate
                            break
                if seq_ticks is not None:
                    break

    if seq_ticks is not None:
        seq_meta.sequence_ticks = seq_ticks
        if seq_meta.ticks_per_bar:
            seq_meta.bars = seq_ticks / seq_meta.ticks_per_bar

    # Fallback: if we couldn't find sequence_ticks, leave bars as None
    return SXQMetadata(
        ppqn=ppqn,
        format_type=format_type,
        num_tracks=num_tracks,
        sequence=seq_meta,
        tracks=sxq_tracks,
    )


###############################################################################
# Build a multitrack MIDI file from parsed SXQ
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
        # Fallback: 4 bars if unknown
        ticks_per_bar = meta.sequence.ticks_per_bar or (4 * ppqn)
        seq_len_ticks = 4 * ticks_per_bar

    ticks_per_bar = meta.sequence.ticks_per_bar or (4 * ppqn)

    # Tempo
    if meta.sequence.mpq is not None:
        mpq = meta.sequence.mpq
    else:
        # Default 120 BPM
        mpq = int(60_000_000 / 120)

    midi_tracks: List[bytearray] = []

    # -------------------------------------------------------------------------
    # Track 0: Conductor
    # -------------------------------------------------------------------------
    t0 = bytearray()

    # Sequence/track name
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
    t0 += bytes([0xFF, 0x51, 0x03])  # Set Tempo
    t0 += mpq.to_bytes(3, "big")

    # Time signature
    if meta.sequence.time_signature:
        nn, dd = meta.sequence.time_signature
        # TS meta: nn, dd_power, clocks, 32nd_notes_per_24_clocks
        dd_power = 0
        while (1 << dd_power) < dd and dd_power < 7:
            dd_power += 1
        t0 += write_vlq(0)
        t0 += bytes([0xFF, 0x58, 0x04, nn, dd_power, 0x18, 0x08])
    else:
        # Default 4/4
        t0 += write_vlq(0)
        t0 += bytes([0xFF, 0x58, 0x04, 0x04, 0x02, 0x18, 0x08])

    # End of track 0
    t0 += write_vlq(0)
    t0 += bytes([0xFF, 0x2F, 0x00])
    midi_tracks.append(t0)

    # -------------------------------------------------------------------------
    # One MIDI track per SXQ track (Ga-11 → notes)
    # -------------------------------------------------------------------------
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

        # Collect note events for this track
        events = []  # (tick, is_on, pitch, velocity)

        for lane in tr.ga11_lanes:
            pitch = lane.pitch
            vel = lane.velocity
            delta_ticks = lane.delta_ticks
            if delta_ticks <= 0:
                continue

            t = 0
            # Note length heuristic: half spacing or min of 32nd note
            note_len = max(delta_ticks // 2, ppqn // 8)

            while t < seq_len_ticks:
                events.append((t, True, pitch, vel))
                off_tick = t + note_len
                if off_tick <= seq_len_ticks:
                    events.append((off_tick, False, pitch, 0))
                t += delta_ticks

        # Sort events by time, note-offs before note-ons at same tick
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

        # End of this MIDI track
        track_bytes += write_vlq(0)
        track_bytes += bytes([0xFF, 0x2F, 0x00])

        midi_tracks.append(track_bytes)

    # -------------------------------------------------------------------------
    # Build SMF (Format 1)
    # -------------------------------------------------------------------------
    midi_bytes = bytearray()
    # Header
    midi_bytes += b"MThd"
    midi_bytes += struct.pack(">I", 6)
    midi_bytes += struct.pack(">H", 1)  # Format 1
    midi_bytes += struct.pack(">H", len(midi_tracks))
    midi_bytes += struct.pack(">H", ppqn)

    # Tracks
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
    print(f"    Seq ticks: {meta.sequence.sequence_ticks}")
    print(f"    Bars:      {meta.sequence.bars}")

    for tr in meta.tracks:
        print(f"  Track {tr.index}: name={tr.name}, Ga-11 lanes={len(tr.ga11_lanes)}, Ga events={len(tr.ga_events)}")

    midi_bytes = build_midi_from_sxq_meta(meta)

    with open(midi_path, "wb") as f:
        f.write(midi_bytes)

    print(f"\nWrote MIDI: {midi_path}")

sxq_to_midi_full(sys.argv[1], sys.argv[2])